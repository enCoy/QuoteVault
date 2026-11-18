"""Second verification step for Turkish quotes: translate to English, search
for the passage in English sources, and compare by meaning.

A match here means "this quote very likely corresponds to that English
passage". It cannot confirm the Turkish wording, because translators differ."""
from __future__ import annotations

import html
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass

import httpx
from rapidfuzz import fuzz

from . import llm
from .config import SETTINGS
from .text import ascii_fold, fold_words, one_line
from .verify import HEADERS, TIMEOUT, SourceDown, _get, wiki_lines, wiki_search

DEADLINE = 15.0
_STOP = set("""the a an and or of to in is are was were be been that this it its for with as on at by from not no
but if so than then they them their he she his her you your we our i my me one all any who whom which what when
where how why do does did have has had will would can could should may might must there here very more most
only just also into out up about over such own same too""".split())

_TRANSLATE = {"type": "object", "properties": {"english": {"type": "string"}}, "required": ["english"]}
_JUDGE = {"type": "object", "properties": {"same": {"type": "boolean"}, "passage": {"type": "string"}},
          "required": ["same", "passage"]}


@dataclass
class Candidate:
    text: str
    source: str
    title: str
    url: str
    score: float = 0.0


def translate(text: str) -> str:
    answer = llm.chat_json(
        "Translate the Turkish quotation into natural, literal English. Keep it one-to-one: do not add, "
        'explain or omit anything. Answer with JSON: {"english": "<translation>"}.',
        text, _TRANSLATE, model=SETTINGS["translate_model"] or None)
    return one_line(str((answer or {}).get("english") or ""))


def keywords(english: str, limit: int = 7) -> list[str]:
    seen, out = set(), []
    for w in fold_words(english):
        if len(w) > 2 and w not in _STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return sorted(out, key=len, reverse=True)[:limit] if len(out) > limit else out


def _pieces(line: str) -> list[str]:
    """A long paragraph is cut into sentence windows so it can be compared with one quote."""
    line = one_line(line)
    if len(line) <= 400:
        return [line]
    sentences = re.split(r"(?<=[.!?…])\s+", line)
    return [" ".join(sentences[i:i + 3]) for i in range(0, len(sentences), 2)]


def _from_wikiquote(client: httpx.Client, english: str, author: str) -> list[Candidate]:
    host = "en.wikiquote.org"
    titles = []
    if author:
        titles += wiki_search(client, host, author, 1)
    for t in wiki_search(client, host, " ".join(keywords(english)), 2):
        if t not in titles:
            titles.append(t)
    out = []
    for title in titles[:3]:
        url = f"https://{host}/wiki/{title.replace(' ', '_')}"
        for _section, ln in wiki_lines(client, host, title):
            if len(ln.split()) >= 4:
                out += [Candidate(p, "Wikiquote", title, url) for p in _pieces(ln)]
    return out


def _from_open_library(client: httpx.Client, english: str, author: str) -> list[Candidate]:
    data = _get(client, "https://openlibrary.org/search/inside.json",
                {"q": " ".join(keywords(english)), "limit": 10})
    out = []
    for item in data.get("hits", {}).get("hits", []):
        fields = item.get("fields", {})
        title = (fields.get("meta_title") or [""])[0]
        creator = (fields.get("meta_creator") or [""])[0]
        url = "https://archive.org/details/" + str(item.get("_id", "")).split("|")[0]
        for snippet in item.get("highlight", {}).get("text", [])[:3]:
            text = one_line(snippet.replace("{{{", "").replace("}}}", ""))
            out.append(Candidate(text, "Open Library", f"{title} — {creator}" if creator else title, url))
    return out


def _from_google_books(client: httpx.Client, english: str, author: str) -> list[Candidate]:
    q = " ".join(keywords(english)) + (f' inauthor:"{author}"' if author else "")
    params = {"q": q, "maxResults": 10, "printType": "books", "langRestrict": "en",
              "fields": "items(volumeInfo(title,authors,infoLink),searchInfo/textSnippet)"}
    if SETTINGS.get("google_books_key"):
        params["key"] = SETTINGS["google_books_key"]
    data = _get(client, "https://www.googleapis.com/books/v1/volumes", params)
    out = []
    for item in data.get("items", []):
        snippet = re.sub(r"<[^>]+>", "", html.unescape(item.get("searchInfo", {}).get("textSnippet", "")))
        info = item.get("volumeInfo", {})
        if snippet:
            out.append(Candidate(one_line(snippet), "Google Books", info.get("title", ""), info.get("infoLink", "")))
    return out


def _from_web(english: str, author: str) -> list[Candidate]:
    try:
        from ddgs import DDGS
        results = DDGS(timeout=8).text(f"{author} quote {english}"[:300], region="us-en", max_results=10)
    except Exception as e:
        if "no results" in str(e).lower():
            return []
        raise SourceDown(str(e)) from e
    out = []
    for r in results or []:
        site = re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", r.get("href", ""))
        if r.get("body"):
            out.append(Candidate(one_line(r["body"]), site, one_line(r.get("title", ""))[:90], r.get("href", "")))
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def rank(english: str, turkish: str, candidates: list[Candidate], keep: int = 4) -> list[Candidate]:
    """Best candidates first: word overlap narrows the field, meaning (embeddings) orders it."""
    target = ascii_fold(english)
    seen, unique = set(), []
    for c in candidates:
        key = ascii_fold(c.text)
        if key not in seen:
            seen.add(key)
            c.score = fuzz.token_set_ratio(target, key) / 100
            unique.append(c)
    unique.sort(key=lambda c: c.score, reverse=True)
    shortlist = unique[:40]
    vectors = llm.embed([english, turkish] + [c.text for c in shortlist])
    if vectors:
        for c, v in zip(shortlist, vectors[2:]):
            c.score = max(_cosine(vectors[0], v), _cosine(vectors[1], v))
        shortlist.sort(key=lambda c: c.score, reverse=True)
    return shortlist[:keep]


def judge(turkish: str, english: str, cand: Candidate) -> str:
    """The matching passage copied from the candidate, or '' if it is a different passage."""
    answer = llm.chat_json(
        "You are given a Turkish quotation, its rough English translation, and an English text found in a "
        "source. Decide whether the source text contains the same passage: the same sentence in English, "
        "with the same meaning, not merely the same topic. If it does, copy the matching sentence or "
        'sentences exactly from the source text. Answer with JSON: {"same": true or false, "passage": "..."}.',
        f"Turkish quotation:\n{turkish}\n\nRough translation:\n{english}\n\nSource text:\n{cand.text}", _JUDGE)
    if not answer or answer.get("same") is not True:
        return ""
    passage = one_line(str(answer.get("passage") or ""))
    # The passage must really come from the source, not from the model's memory.
    if passage and ascii_fold(passage) in ascii_fold(cand.text):
        return passage
    return cand.text if len(cand.text) <= 400 else ""


def crosscheck(text: str, author: str = "", use_web: bool = True) -> dict:
    result = {"status": "not found", "original": "", "evidence": "", "translation": "", "note": ""}
    if not llm.available():
        result.update(status="skipped", note="The local model is not running.")
        return result
    english = translate(text)
    if not english:
        result.update(status="skipped", note="The quote could not be translated.")
        return result
    result["translation"] = english

    jobs = {"wikiquote": _from_wikiquote, "open library": _from_open_library, "google books": _from_google_books}

    def run(fn):
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
            return fn(client, english, author)

    pool = ThreadPoolExecutor(max_workers=4)
    futures = {pool.submit(run, fn): name for name, fn in jobs.items()}
    if use_web:
        futures[pool.submit(_from_web, english, author)] = "web"
    candidates: list[Candidate] = []
    failed = 0
    try:
        for fut in as_completed(futures, timeout=DEADLINE):
            try:
                candidates += fut.result()
            except SourceDown:
                failed += 1
    except FuturesTimeout:
        pass
    failed += sum(not fut.done() for fut in futures)       # too slow counts as unreachable
    pool.shutdown(wait=False, cancel_futures=True)
    if not candidates:
        if failed == len(futures):
            result["status"] = "offline"
        return result

    for cand in rank(english, text, candidates):
        passage = judge(text, english, cand)
        if passage:
            result.update(status="candidate", original=passage,
                          evidence=f"{cand.source}: {cand.title} — {cand.url}")
            break
    return result
