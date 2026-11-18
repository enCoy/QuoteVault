"""Checks a quote against free public sources and reports one of:
  yes            a source has this wording
  suggestion     a source has nearly this sentence, worded differently
  reader-posted  only found on reader-contributed sites (weaker evidence)
  not found      nothing matched
  offline        no source could be reached
Only outgoing searches are made; the quote text is the only thing sent."""
from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import quote as urlquote, urlparse

import httpx

from .config import SETTINGS, USER_AGENT
from .text import _WORD_RE, ascii_fold, one_line

TIMEOUT = httpx.Timeout(12.0, connect=4.0)
DEADLINE = 14.0     # seconds allowed for the whole check
HEADERS = {"User-Agent": USER_AGENT}
_DOUBTFUL = ("misattributed", "disputed", "incorrectly attributed", "wrongly attributed",
             "yanlis atfedilen", "yanlis atfedilenler", "atfedilenler", "tartismali")


# ------------------------------------------------------------------ comparing

@dataclass
class Match:
    matched: int          # words in common inside the overlapping stretch
    agreement: float      # 1.0 = the overlapping stretch is word-for-word identical
    coverage: float       # share of the quote that the overlap spans
    same_spelling: bool   # identical apart from capitals and punctuation
    suggestion: str       # the quote with the overlap replaced by the source's wording

    @property
    def exact(self) -> bool:
        # The source must contain the whole quote, or at least eight of its words in a row;
        # a snippet that stops one word short of a short quote proves nothing about that word.
        return self.agreement >= 0.97 and (self.coverage >= 0.999 or self.matched >= 8) and self.matched >= 3

    @property
    def close(self) -> bool:
        return self.agreement >= 0.6 and self.coverage >= 0.6 and self.matched >= 4

    @property
    def differs(self) -> bool:
        """The source has this sentence with some other words (not just a shorter piece of it)."""
        return self.close and self.agreement < 0.97

    @property
    def score(self) -> float:
        return self.agreement * min(1.0, self.coverage + 0.2) + min(self.matched, 30) / 1000


def _spell(w: str) -> str:
    return w.replace("İ", "i").replace("I", "ı").replace("’", "'").replace("‘", "'").lower()


def compare(quote: str, candidate: str) -> Match | None:
    """How well does `candidate` (a snippet or a line from a source) contain `quote`?"""
    q_spans = [m.span() for m in _WORD_RE.finditer(quote)]
    c_spans = [m.span() for m in _WORD_RE.finditer(candidate)]
    q_raw = [quote[s:e] for s, e in q_spans]
    c_raw = [candidate[s:e] for s, e in c_spans]
    if len(q_raw) < 3 or len(c_raw) < 3:
        return None
    qf, cf = [ascii_fold(w) for w in q_raw], [ascii_fold(w) for w in c_raw]
    blocks = [b for b in SequenceMatcher(None, qf, cf, autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return None
    # Build the cluster around the longest run, joining neighbours across small gaps.
    core = max(range(len(blocks)), key=lambda i: blocks[i].size)
    if blocks[core].size < min(3, len(qf)):
        return None
    lo = hi = core
    while lo > 0 and blocks[lo].a - (blocks[lo - 1].a + blocks[lo - 1].size) <= 4 \
            and blocks[lo].b - (blocks[lo - 1].b + blocks[lo - 1].size) <= 4:
        lo -= 1
    while hi < len(blocks) - 1 and blocks[hi + 1].a - (blocks[hi].a + blocks[hi].size) <= 4 \
            and blocks[hi + 1].b - (blocks[hi].b + blocks[hi].size) <= 4:
        hi += 1
    cluster = blocks[lo:hi + 1]
    q0, q1 = cluster[0].a, cluster[-1].a + cluster[-1].size
    c0, c1 = cluster[0].b, cluster[-1].b + cluster[-1].size
    matched = sum(b.size for b in cluster)
    # A wrong word at the very start or end of the quote: take the source's words there too.
    if 0 < q0 <= 3 and c0 >= q0:
        c0, q0 = c0 - q0, 0
    tail = len(qf) - q1
    if 0 < tail <= 3 and len(cf) - c1 >= tail:
        c1, q1 = c1 + tail, len(qf)
    agreement = matched / max(q1 - q0, c1 - c0)
    coverage = (q1 - q0) / len(qf)
    same = agreement == 1.0 and all(
        _spell(q_raw[b.a + k]) == _spell(c_raw[b.b + k]) for b in cluster for k in range(b.size))
    suggestion = (quote[:q_spans[q0][0]] + candidate[c_spans[c0][0]:c_spans[c1 - 1][1]]
                  + quote[q_spans[q1 - 1][1]:])
    suggestion = one_line(suggestion)
    if q0 == 0 and quote.lstrip()[:1].isupper():      # keep the card's opening capital
        suggestion = suggestion[:1].upper() + suggestion[1:]
    return Match(matched, agreement, coverage, same, suggestion)


def probes(text: str) -> list[str]:
    """Up to three short exact phrases taken from different parts of the quote."""
    ws = [text[m.start():m.end()] for m in _WORD_RE.finditer(text)]
    n = len(ws)
    if n < 3:
        return []
    if n <= 8:
        # Short quote: the whole of it, then its two ends, in case one word is wrong.
        part = max(3, -(-n * 3 // 5))
        out = [" ".join(ws)]
        for piece in (" ".join(ws[:part]), " ".join(ws[-part:])):
            if piece not in out:
                out.append(piece)
        return out
    size = 7
    starts = [0, max(0, n - size)]
    if n > 2 * size:
        starts.insert(1, (n - size) // 2)
    out = []
    for s in starts:
        p = " ".join(ws[s:s + size])
        if p not in out:
            out.append(p)
    return out


# -------------------------------------------------------------------- sources

@dataclass
class Hit:
    source: str       # "Wikiquote", "Google Books", "Vikikaynak", or a web site name
    title: str
    url: str
    match: Match
    trust: str = "curated"   # curated (wiki pages) | book (scanned text, may have OCR errors) | web
    doubtful: str = ""    # section heading such as "Misattributed", if the line sits under one
    line: str = ""
    own: bool = False     # found on the page of the quote's own author


class SourceDown(Exception):
    pass


def _get(client: httpx.Client, url: str, params: dict) -> dict:
    for attempt in (1, 2):
        try:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except httpx.TransportError as e:      # dropped connection: try once more
            if attempt == 2:
                raise SourceDown(str(e)) from e
        except (httpx.HTTPError, ValueError) as e:
            raise SourceDown(str(e)) from e
    raise SourceDown("unreachable")


def wiki_search(client: httpx.Client, host: str, query: str, limit: int = 4) -> list[str]:
    data = _get(client, f"https://{host}/w/api.php", {
        "action": "query", "list": "search", "srsearch": query, "srlimit": limit,
        "srnamespace": 0, "format": "json"})
    return [r["title"] for r in data.get("query", {}).get("search", [])]


def wiki_lines(client: httpx.Client, host: str, title: str) -> list[tuple[str, str]]:
    """Plain text of a wiki page as (section heading, line) pairs."""
    data = _get(client, f"https://{host}/w/api.php", {
        "action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "wiki",
        "titles": title, "redirects": 1, "format": "json"})
    out, section = [], ""
    for page in data.get("query", {}).get("pages", {}).values():
        for ln in (page.get("extract") or "").split("\n"):
            ln = ln.strip()
            m = re.fullmatch(r"=+\s*(.*?)\s*=+", ln)
            if m:
                section = m.group(1)
            elif ln:
                out.append((section, ln))
    return out


def _wiki(client: httpx.Client, host: str, label: str, text: str, author: str, seen: dict) -> list[Hit]:
    """Search a wiki for the quote. The author's own page is always read, and read first."""
    titles: list[str] = [author] if author else []
    for p in probes(text):
        for t in wiki_search(client, host, f'"{p}"', 3):
            if ascii_fold(t) not in [ascii_fold(x) for x in titles]:
                titles.append(t)
        if len(titles) >= 4:
            break
    hits = []
    for title in titles[:4]:
        own = bool(author) and ascii_fold(title) == ascii_fold(author)
        lines = wiki_lines(client, host, title)
        if own and lines:
            seen["own_page"] = True
        best: tuple[Match, str, str] | None = None
        for section, ln in lines:
            m = compare(text, ln)
            if m and m.close and (best is None or m.score > best[0].score):
                best = (m, section, ln)
        if best:
            m, section, ln = best
            doubtful = section if any(k in ascii_fold(section) for k in _DOUBTFUL) else ""
            url = f"https://{host}/wiki/{urlquote(title.replace(' ', '_'))}"
            hits.append(Hit(label, title, url, m, "curated", doubtful, ln, own))
    return hits


def _google_books(client: httpx.Client, text: str, lang: str) -> list[Hit]:
    """Search inside Google's scanned books. Several phrases are searched side by side,
    so that books with a slightly different wording are found too."""
    def search(phrase: str) -> list[Hit]:
        params = {"q": f'"{phrase}"', "maxResults": 10, "printType": "books",
                  "fields": "items(volumeInfo(title,authors,infoLink),searchInfo/textSnippet)"}
        if lang == "tr":
            params["langRestrict"] = "tr"
        if SETTINGS.get("google_books_key"):
            params["key"] = SETTINGS["google_books_key"]
        data = _get(client, "https://www.googleapis.com/books/v1/volumes", params)
        found = []
        for item in data.get("items", []):
            snippet = re.sub(r"<[^>]+>", "", html.unescape(item.get("searchInfo", {}).get("textSnippet", "")))
            m = compare(text, snippet)
            if m and m.close:
                info = item.get("volumeInfo", {})
                title = info.get("title", "")
                title = f"“{title}”"
                if info.get("authors"):
                    title += " by " + ", ".join(info["authors"][:2])
                found.append(Hit("Google Books", title, info.get("infoLink", ""), m, "book", "", snippet))
        return found

    phrases = probes(text)[:3]
    hits: dict[str, Hit] = {}
    failures = 0
    with ThreadPoolExecutor(max_workers=len(phrases) or 1) as pool:
        for fut in [pool.submit(search, p) for p in phrases]:
            try:
                for h in fut.result():
                    if h.title not in hits or h.match.score > hits[h.title].match.score:
                        hits[h.title] = h
            except SourceDown:
                failures += 1
    if phrases and failures == len(phrases):
        raise SourceDown("google books")
    return list(hits.values())


def _open_library(client: httpx.Client, text: str) -> list[Hit]:
    """Full-text search inside the Internet Archive's scanned books. The phrases are searched
    side by side, so that books with a slightly different wording are found too."""
    def search(phrase: str) -> list[Hit]:
        data = _get(client, "https://openlibrary.org/search/inside.json", {"q": f'"{phrase}"', "limit": 8})
        found = []
        for item in data.get("hits", {}).get("hits", []):
            fields = item.get("fields", {})
            title = (fields.get("meta_title") or [""])[0]
            creator = (fields.get("meta_creator") or [""])[0]
            url = "https://archive.org/details/" + str(item.get("_id", "")).split("|")[0]
            best = None
            for snippet in item.get("highlight", {}).get("text", []):
                snippet = one_line(snippet.replace("{{{", "").replace("}}}", ""))
                m = compare(text, snippet)
                if m and m.close and (best is None or m.score > best[0].score):
                    best = (m, snippet)
            if best:
                label = f"“{title}” by {creator}" if creator else f"“{title}”"
                found.append(Hit("Open Library", label, url, best[0], "book", "", best[1]))
        return found

    phrases = probes(text)[:3]
    hits: dict[str, Hit] = {}
    failures = 0
    with ThreadPoolExecutor(max_workers=len(phrases) or 1) as pool:
        for fut in [pool.submit(search, p) for p in phrases]:
            try:
                for h in fut.result():
                    if h.url not in hits or h.match.score > hits[h.url].match.score:
                        hits[h.url] = h
            except SourceDown:
                failures += 1
    if phrases and failures == len(phrases):
        raise SourceDown("open library")
    return list(hits.values())


def _web(text: str, lang: str) -> list[Hit]:
    try:
        from ddgs import DDGS
    except ImportError as e:
        raise SourceDown("ddgs is not installed") from e
    ps = probes(text)
    if not ps:
        return []
    try:
        results = DDGS(timeout=8).text(f'"{ps[0]}"', region="tr-tr" if lang == "tr" else "us-en", max_results=10)
    except Exception as e:            # the package raises its own error types for blocks and timeouts
        if "no results" in str(e).lower():
            return []
        raise SourceDown(str(e)) from e
    hits = []
    for r in results or []:
        m = compare(text, r.get("body", ""))
        if m and m.close:
            site = urlparse(r.get("href", "")).netloc.removeprefix("www.")
            hits.append(Hit(site, r.get("title", ""), r.get("href", ""), m, "web", "", r.get("body", "")))
    return hits


# -------------------------------------------------------------------- verdict

def _evidence(h: Hit) -> str:
    title = one_line(h.title)
    if len(title) > 90:
        title = title[:89].rstrip() + "…"
    if h.trust == "book":       # say plainly that this is a book containing the quote, not its author
        return f"Found in the book {title} ({h.source}) — {h.url}"
    if h.trust == "web":
        return f"Found on {h.source}: {title} — {h.url}"
    return f"{h.source}: {title} — {h.url}"


def _related(page: str, names: list[str]) -> bool:
    p = ascii_fold(page)
    return any(n and (ascii_fold(n) in p or p in ascii_fold(n)) for n in names)


def check(text: str, lang: str = "en", author: str = "", title: str = "", use_web: bool = True) -> dict:
    text = one_line(text)
    result = {"status": "not found", "suggestion": "", "evidence": "", "note": "", "source": "", "unreachable": []}
    if len(_WORD_RE.findall(text)) < 3:
        result["note"] = "Too short to check."
        return result
    seen: dict = {}           # set by the wiki lookup: did the author's own page exist?
    host = "tr.wikiquote.org" if lang == "tr" else "en.wikiquote.org"
    label = "Vikisöz" if lang == "tr" else "Wikiquote"
    jobs = {
        "wikiquote": lambda c: _wiki(c, host, label, text, author, seen),
        "google books": lambda c: _google_books(c, text, lang),
        "open library": lambda c: _open_library(c, text),
    }
    if lang == "tr":
        jobs["wikisource"] = lambda c: _wiki(c, "tr.wikisource.org", "Vikikaynak", text, "", {})
    if use_web:
        jobs["web"] = lambda c: _web(text, lang)

    def run(fn):
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
            return fn(client)

    # Every source gets the same overall time limit; slow ones are counted as unreachable.
    hits: list[Hit] = []
    down: list[str] = []
    pool = ThreadPoolExecutor(max_workers=len(jobs))
    futures = {pool.submit(run, fn): name for name, fn in jobs.items()}
    try:
        for fut in as_completed(futures, timeout=DEADLINE):
            try:
                found = fut.result()
            except SourceDown:
                down.append(futures[fut])
                continue
            hits += found
            if any(h.trust == "curated" and h.match.exact and h.match.same_spelling for h in found):
                break                      # a curated page has the exact wording: no need to wait
    except FuturesTimeout:
        pass
    down += [name for fut, name in futures.items() if not fut.done()]
    pool.shutdown(wait=False, cancel_futures=True)
    result["unreachable"] = sorted(set(down))
    if not hits and len(result["unreachable"]) == len(jobs):
        result["status"] = "offline"
        return result

    # A source that only has a shorter piece of the quote says nothing about its wording: drop it.
    by_score = sorted((h for h in hits if h.match.exact or h.match.differs),
                      key=lambda h: h.match.score, reverse=True)
    curated = [h for h in by_score if h.trust == "curated"]
    own = [h for h in curated if h.own]
    printed = [h for h in by_score if h.trust in ("curated", "book")]
    web = [h for h in by_score if h.trust == "web"]
    exact = next((h for h in printed if h.match.exact), None)
    best = None
    if own:
        # The author's own page is the best witness, whether it agrees with the card or not.
        best = own[0]
        if best.match.exact and best.match.same_spelling:
            result.update(status="yes", evidence=_evidence(best), source=best.source)
        else:
            result.update(status="suggestion", suggestion=best.match.suggestion,
                          evidence=_evidence(best), source=best.source)
    elif exact:
        best = exact
        result.update(status="yes", evidence=_evidence(best), source=best.source)
        # Misquotes get printed too. If more sources carry one other wording than carry the
        # card's wording, offer that wording instead of calling the card verified.
        same = {h.title or h.url for h in printed if h.match.exact}
        other: dict[str, list[Hit]] = {}
        for h in printed:
            if h.match.differs:
                other.setdefault(ascii_fold(h.match.suggestion), []).append(h)
        if other:
            majority = max(other.values(), key=lambda hs: len({h.title or h.url for h in hs}))
            count = len({h.title or h.url for h in majority})
            vetted = next((h for h in majority if h.trust == "curated"), None)
            # A quote page outweighs books when no quote page has the card's wording.
            if (count >= 2 and count > len(same)) or (vetted and exact.trust != "curated"):
                best = vetted or majority[0]
                result.update(status="suggestion", suggestion=best.match.suggestion,
                              evidence=_evidence(best), source=best.source,
                              note=f"{count} source{'s' if count != 1 else ''} with this wording; {len(same)} with yours.")
        # A curated page has these words; offer its spelling if accents differ from what was typed.
        spelled = next((h for h in curated if h.match.exact and h.match.coverage >= 0.8), None)
        if result["status"] == "yes" and spelled and not spelled.match.same_spelling:
            best = spelled
            result.update(status="suggestion", suggestion=best.match.suggestion,
                          evidence=_evidence(best), source=best.source)
    elif curated:
        best = curated[0]
        result.update(status="suggestion", suggestion=best.match.suggestion,
                      evidence=_evidence(best), source=best.source)
    else:
        exact_web = [h for h in web if h.match.exact]
        if exact_web:
            best = exact_web[0]
            sites = sorted({h.source for h in exact_web})
            result.update(status="reader-posted", evidence=_evidence(best), source=best.source)
            result["note"] = "Found on " + ", ".join(sites[:3]) + " (reader-posted)."
        elif by_score:
            # Scanned books and web pages can carry typos of their own, so a different
            # wording from them counts only when two separate sources agree on it.
            wording: dict[str, list[Hit]] = {}
            for h in by_score:
                wording.setdefault(ascii_fold(h.match.suggestion), []).append(h)
            agreed = max(wording.values(), key=lambda hs: len({h.title or h.url for h in hs}))
            if len({h.title or h.url for h in agreed}) >= 2:
                best = agreed[0]
                result.update(status="suggestion", suggestion=best.match.suggestion,
                              evidence=_evidence(best), source=best.source)
                if best.trust == "web":
                    result["note"] = "Wording from reader-posted pages."
    if best and best.trust == "curated" and best.source in ("Wikiquote", "Vikisöz"):
        if best.doubtful:
            result["note"] = f'Listed under "{best.doubtful}" on the {best.source} page "{best.title}".'
        elif author and not best.own and not result["note"] and not _related(best.title, [author, title]):
            result["note"] = (f'Not on the {best.source} page for {author}; this is from the page "{best.title}".'
                              if seen.get("own_page") else f'From the {best.source} page "{best.title}".')
    # Same words as the card, differing only in capitals or punctuation: nothing to suggest.
    if result["status"] == "suggestion" and \
            [_spell(w) for w in _WORD_RE.findall(result["suggestion"])] == [_spell(w) for w in _WORD_RE.findall(text)]:
        result.update(status="yes", suggestion="")
    return result
