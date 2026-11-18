"""The only module that talks to the language model. It uses a local Ollama
server. To use a different AI, replace chat_json() and embed() here."""
from __future__ import annotations

import json
import time

import httpx

from .config import SETTINGS

_state = {"checked": 0.0, "models": set()}


def _url(path: str) -> str:
    return SETTINGS["ollama_url"].rstrip("/") + path


def installed_models(max_age: float = 15.0) -> set[str]:
    """Names of the models the local Ollama server has; empty if it is not running."""
    now = time.time()
    if now - _state["checked"] > max_age:
        try:
            r = httpx.get(_url("/api/tags"), timeout=1.5)
            r.raise_for_status()
            _state["models"] = {m["name"] for m in r.json().get("models", [])}
        except (httpx.HTTPError, ValueError, KeyError):
            _state["models"] = set()
        _state["checked"] = now
    return _state["models"]


def _has(model: str) -> bool:
    if not model:
        return False
    names = installed_models()
    return model in names or f"{model}:latest" in names


def available() -> bool:
    return _has(SETTINGS["llm_model"])


def embed_available() -> bool:
    return _has(SETTINGS["embed_model"])


def chat_json(system: str, user: str, schema: dict, model: str | None = None,
              timeout: float = 90.0) -> dict | None:
    """Ask the model for an answer shaped like `schema`. None if it fails."""
    model = model or SETTINGS["llm_model"]
    if not _has(model):
        return None
    payload = {
        "model": model,
        "stream": False,
        "format": schema,
        "keep_alive": SETTINGS.get("llm_keep_alive", "5m"),
        "options": {"temperature": 0},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if SETTINGS.get("llm_think") is not None:
        payload["think"] = SETTINGS["llm_think"]
    if model in _no_schema:
        del payload["format"]
    try:
        r = httpx.post(_url("/api/chat"), json=payload, timeout=timeout)
        if r.status_code == 501 and "format" in payload:
            # Some model runners cannot force the answer's shape; ask in words only.
            _no_schema.add(model)
            del payload["format"]
            r = httpx.post(_url("/api/chat"), json=payload, timeout=timeout)
        r.raise_for_status()
        return _parse(r.json()["message"]["content"])
    except (httpx.HTTPError, ValueError, KeyError):
        return None


_no_schema: set[str] = set()


def _parse(content: str) -> dict | None:
    """The JSON object in a model answer, tolerating code fences and stray text around it."""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(content[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def embed(texts: list[str], timeout: float = 90.0) -> list[list[float]] | None:
    if not texts or not embed_available():
        return None
    try:
        r = httpx.post(_url("/api/embed"), json={"model": SETTINGS["embed_model"], "input": texts,
                                                 "keep_alive": SETTINGS.get("llm_keep_alive", "5m")}, timeout=timeout)
        r.raise_for_status()
        vectors = r.json()["embeddings"]
        return vectors if len(vectors) == len(texts) else None
    except (httpx.HTTPError, ValueError, KeyError):
        return None
