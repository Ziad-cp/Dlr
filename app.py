"""Dlr: video and MP3 downloader for the Mac (Apple chips).

A pywebview window shows the HTML UI in ui/. Its JavaScript can call only the functions listed
in Api.PAGE_FUNCTIONS, through window.pywebview.api. They are registered one by one by exact
name (window.expose); the Api object itself is never handed to pywebview, so the page can't
reach its private parts (pywebview resolves "a.b.c" names with getattr).
"""
import sys

if __name__ == "__main__" and sys.argv[1:2] == ["--gallery-dl"]:
    # Dlr starting itself to run gallery-dl (see gallery.py): nothing else is loaded.
    import gallery
    sys.exit(gallery.child_main(sys.argv[2:]))

import atexit  # noqa: E402
import functools  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402

import webview  # noqa: E402

# Must run before anything imports yt_dlp: picks the verified downloaded yt-dlp if it's newer.
import updater

updater.activate()

import config  # noqa: E402

try:
    import downloader as dl  # noqa: E402
except ImportError as e:
    if getattr(e, "name", "") not in ("yt_dlp", "gallery_dl") or getattr(sys, "frozen", False):
        raise
    # Running from source without the requirements (the packaged app always has them inside).
    sys.exit(f"{e.name} isn't installed. Install everything in Terminal with:\n"
             "  .venv/bin/pip install -r requirements.txt")
import safety  # noqa: E402

# No logging or debug output: pywebview logs to the console by default.
logging.getLogger("pywebview").disabled = True

__version__ = "1.1.0"

# PyInstaller unpacks bundled files to _MEIPASS.
UI_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "ui"


def reveal(path: str):
    """Show a file in Finder (through macOS itself: no command is run)."""
    from AppKit import NSWorkspace
    from Foundation import NSURL
    from PyObjCTools import AppHelper

    url = NSURL.fileURLWithPath_(os.path.abspath(path))
    AppHelper.callAfter(NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_, [url])


def read_clipboard() -> str:
    """The clipboard's text (through macOS itself: no command is run)."""
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        return str(NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString) or "")
    except Exception:
        return ""


def clipboard_link(text: str) -> str:
    """Only a valid web link found in the clipboard's text, never its other text."""
    match = re.search(r"https?://[^\s<>\"']+", (text or "")[:20000], re.I)
    if not match:
        return ""
    try:
        return safety.check_url(match.group(0), resolve=False)
    except safety.UnsafeInput:
        return ""


class LaunchClipboard:
    """Links the page may fill in from the clipboard when the window comes to the front.

    A link that was already on the clipboard when Dlr opened (usually the last one
    downloaded) is never offered, so every launch starts with an empty link field.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._at_launch = clipboard_link(read_clipboard())

    def new_link(self) -> str:
        link = clipboard_link(read_clipboard())
        with self._lock:
            if self._at_launch is not None:
                if link == self._at_launch:
                    return ""
                self._at_launch = None  # copied something else: from now on every link counts
        return link


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
    """The only functions the page can call are the ones named in PAGE_FUNCTIONS.

    Everything coming from the page is checked here: types, lengths and allowed values. None of
    them runs a command or lets the page choose where a file goes: downloads go only into the
    download folder the user picked in the system's own folder window; the only other files
    written are Dlr's settings and its verified engine updates, at fixed places in
    ~/Library/Application Support/Dlr/.
    """

    PAGE_FUNCTIONS = ("info", "fetch", "set_browser", "add", "cancel", "jobs", "reveal", "clipboard",
                      "choose_folder", "update_ytdlp", "update_status")

    def __init__(self):
        self._cfg = config.load()
        self._lock = threading.Lock()
        self._downloader = dl.Downloader(browser_setting=lambda: self._cfg["cookies_browser"])
        # Leftovers of an interrupted run; in the background so the window opens at once.
        threading.Thread(target=dl.remove_stale_temp, args=(self._cfg["output_dir"],), daemon=True).start()
        # Update yt-dlp on its own (at most once a day); used from the next launch.
        threading.Thread(target=dl.auto_update, daemon=True).start()
        self._clipboard = LaunchClipboard()
        self._window = None

    def _save(self):
        with self._lock:
            config.save(self._cfg)

    def _page_functions(self) -> list:
        return [getattr(self, name) for name in self.PAGE_FUNCTIONS]

    # ---- called from JavaScript ----

    @_bridge(None)
    def info(self) -> dict:
        return {
            "kind": "desktop",
            "revealLabel": "Show in Finder",
            "outputDir": self._cfg["output_dir"],
            "ytdlp": dl.ytdlp_version(),
            "ytdlpSource": updater.active["source"],
            "ytdlpNote": updater.active["note"],
            "updateAvailable": updater.update_available(),
            "updatePending": updater.active["pending"],
            "missing": dl.missing_tools(),
            "browser": self._cfg["cookies_browser"],
            "defaultBrowser": dl.BROWSER_NAMES.get(dl.default_browser(), ""),
            "version": __version__,
        }

    @_bridge(None)
    def fetch(self, url) -> dict:
        url = _text(url, safety.MAX_URL_LENGTH)
        try:
            return dl.fetch_info(url, self._cfg["cookies_browser"])
        except dl.EngineError as e:
            return {"error": dl.with_update_note(str(e))}
        except dl.DownloaderError as e:
            return {"error": str(e)}

    @_bridge(None)
    def set_browser(self, browser) -> dict:
        """Whose login to use when a site asks for one: "auto", "off" or a browser."""
        browser = _text(browser, 20)
        if browser not in config.BROWSERS:
            raise _BadRequest
        self._cfg["cookies_browser"] = browser
        self._save()
        return {"ok": True}

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
        if mode != "mp3" and dl.spotify.is_spotify(url) and dl.spotify.is_collection(url):
            return {"error": dl.SPOTIFY_LIST_MP3}
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
        """A link copied since Dlr opened (see LaunchClipboard)."""
        return self._clipboard.new_link()

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
        changed, message = dl.update_all()  # yt-dlp and gallery-dl
        return {"changed": changed, "message": message, "updateAvailable": "" if changed else updater.update_available()}

    @_bridge("")
    def update_status(self) -> str:
        """A newer yt-dlp waiting for a restart, or one available (checked at most once a day), or ""."""
        return updater.active["pending"] or updater.update_available()


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


_quit_observer = None  # kept alive for the whole run


def _forget_webkit_data_on_every_quit():
    """Run _forget_webkit_data however the app quits. Closing the window returns from
    webview.start(), but ⌘Q, Dock › Quit, logging out and restarting the Mac go through
    NSApplication's terminate:, which ends the process before Python's own exit handlers;
    it announces NSApplicationWillTerminateNotification first, so clean up then too."""
    global _quit_observer
    atexit.register(_forget_webkit_data)
    try:
        from AppKit import NSApplicationWillTerminateNotification
        from Foundation import NSNotificationCenter, NSObject
    except ImportError:
        return

    class DlrQuitObserver(NSObject):
        def appWillTerminate_(self, notification):
            _forget_webkit_data()
            dl.forget_deno_cache()

    _quit_observer = DlrQuitObserver.alloc().init()
    NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        _quit_observer, "appWillTerminate:", NSApplicationWillTerminateNotification, None)


def create_window(api: Api):
    window = webview.create_window(
        "Dlr",
        # Load straight from disk: no local web server, so the app opens no network port.
        (UI_DIR / "index.html").as_uri(),
        # No js_api object: only the functions exposed below, by exact name, can be called.
        width=900,
        height=680,
        min_size=(480, 560),
        background_color="#0a0a0d",
    )
    window.expose(*api._page_functions())
    api._window = window
    return window


def download_cli(args: list[str]) -> int:
    """Command-line mode, no window:  Dlr --download LINK video|mp3|720 [FOLDER]
    Same download code, checks and rules as the app. Prints the saved file's (or, for a post
    with several files, folder's) path. DLR_LOGINS=off|auto|safari|... overrides the
    Logins from setting for this run."""
    quality = {"video": "best"}.get(args[1], args[1]) if len(args) > 1 else ""
    if len(args) not in (2, 3) or not dl.valid_quality(quality):
        print("Usage: --download LINK video|mp3|720 [FOLDER]")
        return 2
    cfg = config.load()
    folder = args[2] if len(args) == 3 else cfg["output_dir"]
    browser = os.environ.get("DLR_LOGINS", cfg["cookies_browser"])
    if browser not in config.BROWSERS:
        browser = cfg["cookies_browser"]
    ffmpeg_dir = dl.find_ffmpeg()
    try:
        if not ffmpeg_dir:
            raise dl.DownloaderError(dl.FFMPEG_MISSING)
        result = dl.download(args[0], quality, folder, ffmpeg_dir, browser_setting=browser)
    except dl.DownloaderError as e:
        print(f"ERROR: {safety.scrub(e)}")
        return 1
    except Exception as e:  # e.g. yt-dlp's own errors: a plain message, never a traceback
        print(f"ERROR: {dl.friendly_error(e)}")
        return 1
    print(result["path"])
    return 0


def _quiet_crashes():
    """The released app never prints a traceback (it would show file paths), whatever fails."""
    def hide(*_):
        try:
            sys.__stderr__.write("Dlr stopped because of an unexpected problem.\n")
        except Exception:
            pass
    sys.excepthook = hide
    threading.excepthook = lambda args: None


def main():
    # Every connection from this process goes only to public internet addresses.
    safety.install_network_guard()
    if getattr(sys, "frozen", False):
        _quiet_crashes()
    if len(sys.argv) > 1 and sys.argv[1] == "--download":
        sys.exit(download_cli(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--job":
        sys.exit(dl.job_child())  # a download in a fresh process, after an update (downloader.py)
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        note = f"\n{updater.active['note']}" if updater.active["note"] else ""
        print(f"Dlr {__version__}, yt-dlp {dl.ytdlp_version()} ({updater.active['source']}){note}")
        print(f"gallery-dl: {updater.gallery_dl_version() or 'not found'}")
        print(f"FFmpeg: {dl.find_ffmpeg() or 'not found'}")
        print(f"Deno: {dl.find_deno() or 'not found'}")
        print(f"Impersonation (TikTok): {'yes' if dl.IMPERSONATE else 'no'}")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--update-ytdlp":
        print(dl.update_all()[1])  # same as the Update button
        sys.exit(0)
    if getattr(sys, "frozen", False):
        # The released app prints nothing anywhere.
        sys.stdout = sys.stderr = open(os.devnull, "w")
    _forget_webkit_data()  # also covers a previous run that was force-quit
    _forget_webkit_data_on_every_quit()
    api = Api()
    create_window(api)
    webview.start(http_server=False, private_mode=True)
    _forget_webkit_data()


if __name__ == "__main__":
    main()
