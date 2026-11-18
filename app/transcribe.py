"""Voice input: speech to text with Whisper, running on this Mac."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import threading

from .config import SETTINGS

_lock = threading.Lock()

# ffmpeg decodes the browser's recording. When the app is started from the Dock
# the Homebrew folder is not on PATH, so add it.
for _dir in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _dir not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = os.environ.get("PATH", "") + ":" + _dir


def available() -> bool:
    return importlib.util.find_spec("mlx_whisper") is not None


def transcribe(audio: bytes, suffix: str = ".webm", lang: str = "auto") -> dict:
    """Returns {"text", "lang"}. `lang` is "tr", "en" or "auto"."""
    import mlx_whisper

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio)
        path = f.name
    try:
        with _lock:
            def run(language):
                return mlx_whisper.transcribe(path, path_or_hf_repo=SETTINGS["whisper_model"],
                                              language=language, condition_on_previous_text=False)
            result = run(lang if lang in ("tr", "en") else None)
            if result.get("language") not in ("tr", "en"):
                result = run("tr")       # only Turkish and English are expected
        return {"text": (result.get("text") or "").strip(), "lang": result.get("language", "")}
    finally:
        os.unlink(path)
