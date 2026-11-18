"""Web server: the JSON API under /api and the interface from static/."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import books, crosscheck, llm, people, textfix, transcribe, verify
from .config import CERT_DIR, LIBRARY, ROOT, SETTINGS
from .storage import KIND_DIRS, Library

app = FastAPI(title="Quote Vault", docs_url=None, redoc_url=None)
_library: Library | None = None


def lib() -> Library:
    global _library
    if _library is None:
        _library = Library(LIBRARY)
    else:
        _library.refresh()
    return _library


@app.exception_handler(KeyError)
async def _not_found(_: Request, exc: KeyError):
    return JSONResponse({"detail": str(exc.args[0]) if exc.args else "Not found"}, status_code=404)


@app.exception_handler(ValueError)
async def _bad_request(_: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.middleware("http")
async def _no_stale_files(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _kind(kind: str) -> str:
    if kind not in KIND_DIRS:
        raise HTTPException(404, "kind must be 'book', 'person' or 'topic'")
    return kind


# ------------------------------------------------------------------ overview

def _phone_addresses() -> list[str]:
    """Addresses another device on the same Wi-Fi can open."""
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True,
                              timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = ""
    if not name:
        return []
    out = [f"http://{name}.local:{SETTINGS['port']}"]
    if (CERT_DIR / "cert.pem").exists() and (CERT_DIR / "key.pem").exists():
        out.insert(0, f"https://{name}.local:{SETTINGS['https_port']}")
    return out


@app.get("/api/status")
def status():
    return {
        "llm": llm.available(), "model": SETTINGS["llm_model"],
        "voice": transcribe.available(),
        "crosscheck": llm.available(),
        "library": str(LIBRARY),
        "phone": _phone_addresses(),
    }


@app.get("/api/overview")
def overview():
    """Everything the interface needs to draw its lists, in one call."""
    L = lib()
    return {
        "sources": [s.summary() for s in L.sources()],
        "tags": L.tags(),
        "names": L.names(),
        "total": sum(len(s.quotes) for s in L.sources()),
        "facts": sum(q.type == "fact" for s in L.sources() for q in s.quotes),
    }


# ------------------------------------------------------------------- sources

@app.post("/api/sources")
def create_source(kind: str = Body(...), meta: dict = Body(...)):
    return lib().create_source(_kind(kind), meta).summary()


@app.get("/api/sources/{kind}/{slug}")
def get_source(kind: str, slug: str):
    L = lib()
    src = L.source(_kind(kind), slug)
    return {**src.summary(), "quotes": L.quotes(kind=kind, slug=src.slug)}


@app.patch("/api/sources/{kind}/{slug}")
def update_source(kind: str, slug: str, meta: dict = Body(..., embed=True)):
    return lib().update_source(_kind(kind), slug, meta).summary()


@app.delete("/api/sources/{kind}/{slug}")
def delete_source(kind: str, slug: str):
    lib().delete_source(_kind(kind), slug)
    return {"ok": True}


# -------------------------------------------------------------------- quotes

@app.get("/api/quotes")
def list_quotes(kind: str | None = None, slug: str | None = None, tag: str | None = None,
                name: str | None = None, favorite: bool | None = None, verified: str | None = None,
                q: str | None = None, type: str | None = None):
    return lib().quotes(kind=kind, slug=slug, tag=tag, name=name, favorite=favorite, verified=verified, q=q,
                        card_type=type)


@app.post("/api/quotes")
def add_quote(kind: str = Body(...), slug: str = Body(...), fields: dict = Body(...)):
    return lib().add_quote(_kind(kind), slug, fields)


@app.patch("/api/quotes/{qid}")
def update_quote(qid: str, fields: dict = Body(..., embed=True)):
    return lib().update_quote(qid, fields)


@app.delete("/api/quotes/{qid}")
def delete_quote(qid: str):
    lib().delete_quote(qid)
    return {"ok": True}


@app.post("/api/quotes/{qid}/move")
def move_quote(qid: str, kind: str = Body(...), slug: str = Body(...)):
    return lib().move_quote(qid, _kind(kind), slug)


# ------------------------------------------------- tidy up, tag, verify

@app.post("/api/process")
def process(text: str = Body(...), lang: str = Body("auto")):
    """Language, corrected text and suggested tags for a quote being entered."""
    return textfix.process(text, lang, [t["tag"] for t in lib().tags()])


@app.post("/api/verify")
def verify_text(text: str = Body(...), lang: str = Body("en"), author: str = Body(""), title: str = Body("")):
    """Look a quote up in the web sources before it is saved."""
    return verify.check(text, lang if lang in ("tr", "en") else textfix.detect_lang(text), author, title)


def _evidence(result: dict) -> str:
    return " | ".join(p for p in (result.get("evidence"), result.get("note")) if p)


def _check_saved(L: Library, q: dict) -> tuple[dict, str]:
    lang = q["lang"] if q["lang"] in ("tr", "en") else textfix.detect_lang(q["text"])
    title = q["title"] if q["kind"] == "book" else ""
    result = verify.check(q["text"], lang, q["author"], title)
    if result["status"] == "offline":
        return q, "offline"
    q = L.update_quote(q["id"], {"verified": result["status"], "suggestion": result["suggestion"],
                                 "evidence": _evidence(result), "lang": lang})
    return q, result["status"]


@app.post("/api/quotes/{qid}/check")
def check_quote(qid: str):
    """Run the web check on a saved quote and store the outcome on it."""
    L = lib()
    q = L.quote(qid)
    if q["type"] == "fact":       # the check compares wording with sources; a fact has no wording to match
        return {"quote": q, "outcome": "skipped"}
    q, outcome = _check_saved(L, q)
    return {"quote": q, "outcome": outcome}


@app.post("/api/quotes/{qid}/crosscheck")
def crosscheck_quote(qid: str):
    """Turkish quotes only: look for the matching English passage."""
    L = lib()
    q = L.quote(qid)
    src = L.source(q["kind"], q["slug"])
    if q["lang"] != "tr" or q["type"] == "fact":
        return {"quote": q, "outcome": "skipped", "note": "Only Turkish quotes are cross-checked."}
    if str(src.meta.get("original_language") or "").lower() in ("tr", "turkish", "türkçe"):
        return {"quote": q, "outcome": "skipped", "note": "This work was written in Turkish."}
    result = crosscheck.crosscheck(q["text"], q["author"])
    if result["status"] == "candidate":
        q = L.update_quote(qid, {"verified": "candidate", "original": result["original"],
                                 "evidence": result["evidence"]})
    return {"quote": q, "outcome": result["status"], "note": result["note"],
            "translation": result["translation"]}


@app.post("/api/recheck")
def recheck(limit: int = Body(8, embed=True)):
    """Check quotes that were saved while offline. Stops at the first sign of being offline."""
    L = lib()
    pending = L.quotes(verified="unchecked", card_type="quote")
    done = 0
    for q in reversed(pending[-limit:] if limit else pending):
        _, outcome = _check_saved(L, q)
        if outcome == "offline":
            return {"checked": done, "remaining": len(pending) - done, "online": False}
        done += 1
    return {"checked": done, "remaining": len(pending) - done, "online": True}


# ------------------------------------------------------------------- lookups

@app.get("/api/lookup/books")
def lookup_books(q: str):
    return books.lookup(q)


@app.get("/api/lookup/people")
def lookup_people(q: str, lang: str = "en"):
    return people.lookup(q, lang)


# --------------------------------------------------------------------- voice

@app.post("/api/transcribe")
def transcribe_audio(audio: UploadFile = File(...), lang: str = Form("auto")):
    if not transcribe.available():
        raise HTTPException(503, "Voice input is not installed")
    data = audio.file.read()
    if len(data) < 1000:
        raise ValueError("The recording is empty")
    suffix = Path(audio.filename or "").suffix or ".webm"
    return transcribe.transcribe(data, suffix, lang)


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
