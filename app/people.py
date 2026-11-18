"""Person details from Wikipedia and Wikidata (free, no account)."""
from __future__ import annotations

import httpx

from .config import USER_AGENT

HEADERS = {"User-Agent": USER_AGENT}


def _year(claims: dict, prop: str):
    try:
        t = claims[prop][0]["mainsnak"]["datavalue"]["value"]["time"]     # "+1913-11-07T00:00:00Z"
        year = int(t[1:].split("-")[0])
        return -year if t.startswith("-") else year
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def lookup(q: str, lang: str = "en") -> dict:
    """People matching a typed name, with a one-line description and life dates. Never raises."""
    q = q.strip()
    if not q:
        return {"results": [], "online": True}
    host = f"{'tr' if lang == 'tr' else 'en'}.wikipedia.org"
    try:
        with httpx.Client(headers=HEADERS, timeout=8, follow_redirects=True) as c:
            r = c.get(f"https://{host}/w/api.php", params={
                "action": "query", "generator": "search", "gsrsearch": q, "gsrlimit": 5, "gsrnamespace": 0,
                "prop": "pageprops|description|pageimages", "ppprop": "wikibase_item",
                "pithumbsize": 200, "format": "json"})
            r.raise_for_status()
            pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
            ids = [p["pageprops"]["wikibase_item"] for p in pages if p.get("pageprops", {}).get("wikibase_item")]
            entities = {}
            if ids:
                r = c.get("https://www.wikidata.org/w/api.php", params={
                    "action": "wbgetentities", "ids": "|".join(ids), "props": "claims", "format": "json"})
                r.raise_for_status()
                entities = r.json().get("entities", {})
    except (httpx.HTTPError, ValueError, KeyError):
        return {"results": [], "online": False}
    results = []
    for p in pages:
        claims = entities.get(p.get("pageprops", {}).get("wikibase_item", ""), {}).get("claims", {})
        is_human = any(c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") == "Q5"
                       for c in claims.get("P31", []))
        if claims and not is_human:
            continue
        results.append({
            "name": p.get("title", ""),
            "description": p.get("description", ""),
            "born": _year(claims, "P569"),
            "died": _year(claims, "P570"),
            "image": p.get("thumbnail", {}).get("source", ""),
            "from": "Wikipedia",
        })
    return {"results": results, "online": True}
