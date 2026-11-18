"""Starts Quote Vault.

    python -m app.serve            server only; stop with Ctrl+C (used by run.sh)
    python -m app.serve --window   server plus a desktop window; closing the window
                                   stops everything (used by Quote Vault.app)

Nothing is installed to run at login. The local model server (Ollama) is
started here if it is not already running, and stopped again on exit."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx
import uvicorn

from .config import CERT_DIR, SETTINGS

for _dir in ("/opt/homebrew/bin", "/usr/local/bin"):          # not on PATH when started from the Dock
    if _dir not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = os.environ.get("PATH", "") + ":" + _dir

PORT = int(SETTINGS["port"])
LOCAL_URL = f"http://127.0.0.1:{PORT}"


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_ollama() -> subprocess.Popen | None:
    """Start the local model server unless one is already running."""
    try:
        httpx.get(SETTINGS["ollama_url"].rstrip("/") + "/api/version", timeout=1).raise_for_status()
        return None
    except httpx.HTTPError:
        pass
    binary = shutil.which("ollama")
    if not binary or not SETTINGS["llm_model"]:
        return None
    env = dict(os.environ, OLLAMA_FLASH_ATTENTION="1", OLLAMA_KV_CACHE_TYPE="q8_0")
    # A small watcher stops the model server as soon as Quote Vault is gone, however it was closed
    # (window closed, Quit, or Force Quit), so nothing is left running in the background.
    watcher = ('"$1" serve >/dev/null 2>&1 & child=$!; '
               'while kill -0 "$2" 2>/dev/null && kill -0 $child 2>/dev/null; do sleep 1; done; '
               'kill $child 2>/dev/null')
    return subprocess.Popen(["/bin/sh", "-c", watcher, "sh", binary, str(os.getpid())], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def build_servers() -> list[uvicorn.Server]:
    common = dict(app="app.main:app", host=SETTINGS["host"], log_level="warning")
    servers = [uvicorn.Server(uvicorn.Config(port=PORT, **common))]
    cert, key = CERT_DIR / "cert.pem", CERT_DIR / "key.pem"
    if cert.exists() and key.exists():          # made by scripts/setup-phone-https.sh, for the phone's microphone
        servers.append(uvicorn.Server(uvicorn.Config(port=int(SETTINGS["https_port"]), ssl_certfile=str(cert),
                                                     ssl_keyfile=str(key), **common)))
    return servers


def _allow_microphone() -> None:
    """Let pages served by this app use the microphone inside the desktop window.
    Without this the window asks again on every start, or refuses."""
    import objc
    from webview.platforms.cocoa import BrowserView

    name = b"webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:"
    objc.registerMetaDataForSelector(b"NSObject", name, {"arguments": {6: {"callable": {
        "retval": {"type": b"v"}, "arguments": {0: {"type": b"^v"}, 1: {"type": b"q"}}}}}})

    def handler(self, webview, origin, frame, kind, decide):
        own = str(origin.host()) in ("127.0.0.1", "localhost") and int(origin.port()) == PORT
        decide(1 if own else 0)        # 1 = grant, 0 = let the system ask

    objc.classAddMethods(BrowserView.BrowserDelegate,
                         [objc.selector(handler, selector=name, signature=b"v@:@@@q@?")])


def _enable_media() -> None:
    """Switch on the microphone feature of the desktop window. The window toolkit leaves it
    off, and then pages cannot even ask for the microphone (the mic button stays grey)."""
    import WebKit
    from webview.platforms import cocoa

    real = WebKit.WKWebViewConfiguration

    class _Init:
        @staticmethod
        def init():
            config = real.alloc().init()
            prefs = config.preferences()
            prefs.setValue_forKey_(True, "mediaDevicesEnabled")
            prefs.setValue_forKey_(True, "mediaStreamEnabled")
            return config

    class _Configuration:
        @staticmethod
        def alloc():
            return _Init

    cocoa.WebKit.WKWebViewConfiguration = _Configuration


def open_window() -> bool:
    """Show the interface in its own window and block until it is closed. False if that is not possible."""
    try:
        import webview
    except ImportError:
        return False
    for step in (_enable_media, _allow_microphone):
        try:
            step()
        except Exception as e:                 # the window still works, without voice input
            print(f"Quote Vault: {step.__name__} failed: {e!r}", file=sys.stderr, flush=True)
    storage = Path.home() / "Library" / "Application Support" / "Quote Vault"
    storage.mkdir(parents=True, exist_ok=True)
    webview.create_window("Quote Vault", LOCAL_URL, width=1180, height=880, min_size=(400, 560),
                          text_select=True)
    webview.start(private_mode=False, storage_path=str(storage))
    return True


def main() -> None:
    window = "--window" in sys.argv
    if _listening(PORT):                       # already running: just show it
        if window and open_window():
            return
        webbrowser.open(LOCAL_URL)
        return

    start_ollama()
    servers = build_servers()
    try:
        if not window:
            print(f"Quote Vault is running at {LOCAL_URL}  (Ctrl+C to stop)")
            for extra in servers[1:]:
                threading.Thread(target=extra.run, daemon=True).start()
            servers[0].run()
            return
        for server in servers:
            threading.Thread(target=server.run, daemon=True).start()
        for _ in range(100):
            if _listening(PORT):
                break
            time.sleep(0.1)
        if not open_window():
            webbrowser.open(LOCAL_URL)         # no window toolkit: stay up until the process is stopped
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.should_exit = True
        time.sleep(0.4)          # the watcher started in start_ollama() stops the model server


if __name__ == "__main__":
    main()
