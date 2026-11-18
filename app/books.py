"""Book details from Open Library and Google Books (free, no account)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx

from .config import SETTINGS, USER_AGENT
from .text import ascii_fold

HEADERS = {"User-Agent": USER_AGENT}
_LANGS = {"tur": "tr", "eng": "en", "ger": "de", "fre": "fr", "rus": "ru", "spa": "es", "ita": "it"}


def _open_library(q: str) -> list[dict]:
    r = httpx.get("https://openlibrary.org/search.json", headers=HEADERS, timeout=15, params={
        "q": q, "limit": 8,
        "fields": "title,author_name,first_publish_year,publisher,isbn,language,number_of_pages_median,cover_i"})
    r.raise_for_status()
    out = []
    for d in r.json().get("docs", []):
        langs = d.get("language") or []
        out.append({
            "title": d.get("title", ""),
            "author": ", ".join((d.get("author_name") or [])[:2]),
            "year": d.get("first_publish_year"),
            "publisher": (d.get("publisher") or [""])[0],
            "isbn": next((i for i in d.get("isbn") or [] if len(i) == 13), (d.get("isbn") or [""])[0]),
            "language": _LANGS.get(langs[0], langs[0]) if len(langs) == 1 else "",
            "pages": d.get("number_of_pages_median"),
            "cover": f"https://covers.openlibrary.org/b/id/{d['cover_i']}-M.jpg" if d.get("cover_i") else "",
            "from": "Open Library",
        })
    return out


def _google(q: str) -> list[dict]:
    params = {"q": q, "maxResults": 8, "printType": "books"}
    if SETTINGS.get("google_books_key"):
        params["key"] = SETTINGS["google_books_key"]
    r = httpx.get("https://www.googleapis.com/books/v1/volumes", headers=HEADERS, timeout=8, params=params)
    r.raise_for_status()
    out = []
    for item in r.json().get("items", []):
        v = item.get("volumeInfo", {})
        ids = {i.get("type"): i.get("identifier") for i in v.get("industryIdentifiers", [])}
        year = (v.get("publishedDate") or "")[:4]
        out.append({
            "title": v.get("title", ""),
            "author": ", ".join((v.get("authors") or [])[:2]),
            "year": int(year) if year.isdigit() else None,
            "publisher": v.get("publisher", ""),
            "isbn": ids.get("ISBN_13") or ids.get("ISBN_10") or "",
            "language": v.get("language", ""),
            "pages": v.get("pageCount"),
            "cover": (v.get("imageLinks") or {}).get("thumbnail", "").replace("http://", "https://"),
            "from": "Google Books",
        })
    return out


def lookup(q: str) -> dict:
    """Candidate editions for a typed title (and author). Never raises."""
    q = q.strip()
    if not q:
        return {"results": [], "online": True}
    results, failures = [], 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        for fut in [pool.submit(_open_library, q), pool.submit(_google, q)]:
            try:
                results += fut.result()
            except (httpx.HTTPError, ValueError, KeyError):
                failures += 1
    seen, unique = set(), []
    for b in results:
        key = (ascii_fold(b["title"]), ascii_fold(b["author"]), b["year"])
        if b["title"] and key not in seen:
            seen.add(key)
            unique.append(b)
    return {"results": unique[:12], "online": failures < 2}
