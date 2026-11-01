"""Dlr: video and MP3 downloader, desktop app (macOS and Windows).

A pywebview window shows the HTML UI in ui/. Its JavaScript calls the public
methods of Api below through window.pywebview.api.
"""
import functools
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import webview

# Must run before anything imports yt_dlp: picks the verified downloaded yt-dlp if it's newer.
import updater

updater.activate()

import config  # noqa: E402
import downloader as dl  # noqa: E402
import safety  # noqa: E402

# No logging or debug output: pywebview logs to the console by default.
logging.getLogger("pywebview").disabled = True

__version__ = "1.1.0"

# PyInstaller unpacks bundled files to _MEIPASS.
UI_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "ui"


def reveal(path: str):
    """Show a file in Finder / Explorer."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def _windows_clipboard() -> str:
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ptr) if ptr else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def read_clipboard() -> str:
    try:
        if sys.platform == "darwin":
            env = dict(os.environ, LANG="en_US.UTF-8")
            return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2, env=env).stdout
        if sys.platform == "win32":
            return _windows_clipboard()
        return subprocess.run(["xclip", "-o", "-selection", "clipboard"],
                              capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return ""


def _bridge(fallback):
    """Wrap a method the page can call: bad arguments or unexpected errors never
    reach the page as Python error text, only as a plain message."""
    def wrap(fn):
        @functools.wraps(fn)
        def safe(self, *args):
            try:
                return fn(self, *args)
            except _BadRequest:
                return {"error": "That request isn't valid."} if fallback is None else fallback
            except Exception:
                return {"error": "Something went wrong."} if fallback is None else fallback
        return safe
    return wrap


class _BadRequest(Exception):
    pass


def _text(value, max_length: int) -> str:
    if not isinstance(value, str) or len(value) > max_length:
        raise _BadRequest
    return value


def _job_id(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 1_000_000:
        raise _BadRequest
    return value


class Api:
    """The only functions the page can call (names starting with _ are not exposed).

    Everything coming from the page is checked here: types, lengths and allowed values.
    """

    def __init__(self):
        self._cfg = config.load()
        self._lock = threading.Lock()
        self._downloader = dl.Downloader()
        # Leftovers of an interrupted run; in the background so the window opens at once.
        threading.Thread(target=dl.remove_stale_temp, args=(self._cfg["output_dir"],), daemon=True).start()
        # Look for a new yt-dlp (at most once a day). Nothing is installed without a click.
        threading.Thread(target=updater.check_latest, daemon=True).start()
        self._window = None

    def _save(self):
        with self._lock:
            config.save(self._cfg)

    # ---- called from JavaScript ----

    @_bridge(None)
    def info(self) -> dict:
        label = {"darwin": "Show in Finder", "win32": "Show in Explorer"}.get(sys.platform, "Show file")
        return {
            "kind": "desktop",
            "revealLabel": label,
            "outputDir": self._cfg["output_dir"],
            "ytdlp": dl.ytdlp_version(),
            "ytdlpSource": updater.active["source"],
            "ytdlpNote": updater.active["note"],
            "updateAvailable": updater.update_available(),
            "version": __version__,
        }

    @_bridge(None)
    def fetch(self, url) -> dict:
        url = _text(url, safety.MAX_URL_LENGTH)
        try:
            return dl.fetch_info(url)
        except dl.DownloaderError as e:
            return {"error": str(e)}

    @_bridge(None)
    def add(self, url, mode, title="", label="") -> dict:
        url = _text(url, safety.MAX_URL_LENGTH)
        mode = _text(mode, 8)
        title, label = _text(title or "", 1000), _text(label or "", 100)
        if not dl.valid_quality(mode):
            raise _BadRequest
        try:
            url = safety.check_url(url)
        except safety.UnsafeInput as e:
            return {"error": str(e)}
        job = self._downloader.add(url, mode, self._cfg["output_dir"], title, label)
        return {"id": job.id}

    @_bridge(None)
    def cancel(self, job_id) -> dict:
        return {"ok": self._downloader.cancel(_job_id(job_id))}

    @_bridge([])
    def jobs(self) -> list:
        return self._downloader.snapshot()

    @_bridge(None)
    def reveal(self, path):
        path = _text(path, 4096)
        known = {j["filepath"] for j in self._downloader.snapshot()}  # this session's downloads
        if not path or path not in known:
            return {"error": "Unknown file."}
        if not os.path.exists(path):
            return {"error": "That file was moved or deleted."}
        reveal(path)
        return {"ok": True}

    @_bridge("")
    def clipboard(self) -> str:
        """Only a valid web link found on the clipboard, never the clipboard's other text."""
        match = re.search(r"https?://[^\s<>\"']+", read_clipboard()[:20000], re.I)
        if not match:
            return ""
        try:
            return safety.check_url(match.group(0), resolve=False)
        except safety.UnsafeInput:
            return ""

    @_bridge(None)
    def choose_folder(self):
        folder_dialog = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(folder_dialog, directory=self._cfg["output_dir"])
        chosen = result[0] if isinstance(result, (list, tuple)) and result else result
        if isinstance(chosen, str) and os.path.isdir(chosen):
            self._cfg["output_dir"] = os.path.realpath(chosen)
            self._save()
        return self._cfg["output_dir"]

    @_bridge(None)
    def update_ytdlp(self) -> dict:
        changed, message = dl.update_ytdlp()
        return {"changed": changed, "message": message, "updateAvailable": "" if changed else updater.update_available()}

    @_bridge("")
    def update_status(self) -> str:
        """The newer yt-dlp version available (checked at most once a day), or ""."""
        return updater.update_available()


def _forget_webkit_data():
    """WebKit creates its own (empty) data folders even in private mode. The packaged app
    removes them, so that its settings file is the only thing it leaves on disk. Only the
    app's own bundle folders: never the ones Python shares with other apps."""
    try:
        from Foundation import NSBundle
    except ImportError:
        return
    bundle_id = str(NSBundle.mainBundle().bundleIdentifier() or "")
    if not getattr(sys, "frozen", False) or not bundle_id or bundle_id.startswith(("org.python", "com.apple")):
        return
    folders = []
    for bid in (bundle_id, "com.local.videodownloader"):  # also the app's old name, if left over
        folders += [Path.home() / "Library" / "WebKit" / bid, Path.home() / "Library" / "Caches" / bid]
    for folder in folders:
        if folder.is_dir() and not folder.is_symlink():
            shutil.rmtree(folder, ignore_errors=True)


def create_window(api: Api):
    window = webview.create_window(
        "Dlr",
        # Load straight from disk: no local web server, so the app opens no network port.
        (UI_DIR / "index.html").as_uri(),
        js_api=api,
        width=900,
        height=680,
        min_size=(480, 560),
        background_color="#0a0a0d",
    )
    api._window = window
    return window


def download_cli(args: list[str]) -> int:
    """Command-line mode, no window:  Dlr --download LINK video|mp3 [FOLDER]
    Same download code, checks and rules as the app. Prints the saved file's path."""
    if len(args) not in (2, 3) or args[1] not in ("video", "mp3"):
        print("Usage: --download LINK video|mp3 [FOLDER]")
        return 2
    folder = args[2] if len(args) == 3 else config.load()["output_dir"]
    ffmpeg_dir = dl.find_ffmpeg()
    try:
        if not ffmpeg_dir:
            raise dl.DownloaderError(dl.FFMPEG_MISSING)
        result = dl.download(args[0], "mp3" if args[1] == "mp3" else "best", folder, ffmpeg_dir)
    except dl.DownloaderError as e:
        print(f"ERROR: {e}")
        return 1
    print(result["path"])
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--download":
        sys.exit(download_cli(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        note = f"\n{updater.active['note']}" if updater.active["note"] else ""
        print(f"Dlr {__version__}, yt-dlp {dl.ytdlp_version()} ({updater.active['source']}){note}")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--update-ytdlp":
        print(dl.update_ytdlp()[1])  # same as the Update button
        sys.exit(0)
    if getattr(sys, "frozen", False):
        # The released app prints nothing anywhere.
        sys.stdout = sys.stderr = open(os.devnull, "w")
    _forget_webkit_data()  # also covers a previous run that was force-quit
    api = Api()
    create_window(api)
    webview.start(http_server=False, private_mode=True)
    _forget_webkit_data()


if __name__ == "__main__":
    main()
