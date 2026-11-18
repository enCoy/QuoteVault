"""Settings. Defaults can be overridden in settings.json at the project root
or with QUOTE_VAULT_* environment variables."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "library": str(ROOT / "library"),
    "host": "0.0.0.0",
    "port": 8765,
    "https_port": 8766,
    "ollama_url": "http://127.0.0.1:11434",
    "llm_model": "gemma4:e4b",   # best of the models compared with scripts/eval_models.py; empty = AI pass off
    "llm_think": False,          # this model is 10x slower, and no more accurate, when it reasons out loud first
    "llm_keep_alive": "5m",      # how long the model stays in memory after its last use
    "translate_model": "",       # empty = use llm_model
    "embed_model": "bge-m3",     # compares sentences by meaning; empty = cross-language check uses the LLM only
    "whisper_model": "mlx-community/whisper-large-v3-turbo",
    "contact": "",            # contact detail Wikimedia asks automated clients to send; empty = not sent
    "google_books_key": "",   # optional free Google API key; without it Google Books is often over quota
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    path = ROOT / "settings.json"
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    for key in DEFAULTS:
        env = os.environ.get(f"QUOTE_VAULT_{key.upper()}")
        if env is not None and type(DEFAULTS[key]) in (str, int):
            cfg[key] = type(DEFAULTS[key])(env)
    return cfg


SETTINGS = load()
LIBRARY = Path(SETTINGS["library"])
CERT_DIR = ROOT / "certs"
USER_AGENT = (f"QuoteVault/0.1 ({SETTINGS['contact']})" if SETTINGS["contact"]
              else "QuoteVault/0.1 (personal quote notebook)")
