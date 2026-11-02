"""Photo posts, carousels and slideshows, with gallery-dl.

gallery-dl always runs in a separate process: Dlr starting itself with --gallery-dl (see
child_main). So a download can be stopped at once, a newly installed gallery-dl is used
straight away, and gallery-dl's global settings never mix with the app's.

The child gets an argument list (never a shell), "--" before the link, no user config
files (--config-ignore), and a private config file in the download's temp folder: no cache
on disk (":memory:"), no archive, no post-processors, nothing written outside that folder.
What it prints is read in memory only.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif", "heic", "heif", "avif", "bmp", "tif", "tiff"}
VIDEO_EXT = {"mp4", "m4v", "mov", "webm", "mkv", "flv", "ts"}
AUDIO_EXT = {"mp3", "m4a", "aac", "opus", "ogg", "wav", "flac"}
MAX_LISTING = 16 * 1024 * 1024
MAX_ITEMS = 500


class GalleryError(Exception):
    """gallery-dl failed; the message is gallery-dl's own last error line."""


def self_command() -> list[str]:
    """How to start Dlr itself: the app's binary, or app.py when running from source."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().with_name("app.py"))]


def child_main(argv: list[str]) -> int:
    """Dlr --gallery-dl ARGS: run gallery-dl (the newest verified one) with ARGS."""
    # A windowed app may start without standard output (Windows): gallery-dl prints to it.
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name) is None:
            setattr(sys, name, open(fd, "w", encoding="utf-8", closefd=False))
    import updater
    updater.activate()  # gallery-dl hands some videos to yt-dlp
    updater.activate_gallery_dl()
    import yt_dlp.globals
    yt_dlp.globals.plugin_dirs.value = []  # never load yt-dlp plugins
    import gallery_dl
    sys.argv = ["gallery-dl", *argv]
    return gallery_dl.main()


def _config(work: str, ffmpeg_dir) -> dict:
    ytdl = {"cachedir": False, "noplaylist": True}
    if ffmpeg_dir:
        ytdl["ffmpeg_location"] = ffmpeg_dir
    return {
        "cache": {"file": ":memory:"},
        "extractor": {
            "base-directory": work,
            "directory": [],
            "skip": False,
            "archive": None,
            "postprocessors": None,
            "write-pages": False,
            "tiktok": {"photos": True, "audio": True},
            "instagram": {"videos": True, "previews": False},
            "reddit": {"videos": True},
            "ytdl": {"module": "yt_dlp", "config-file": None, "raw-options": ytdl},
        },
        "downloader": {"part-directory": work, "mtime": False, "retries": 2, "timeout": 30,
                       "progress": None, "ytdl": {"module": "yt_dlp", "config-file": None, "raw-options": ytdl}},
        "output": {"mode": "pipe", "progress": False, "skip": False, "log": "[{name}][{levelname}] {message}",
                   "logfile": None, "unsupportedfile": None, "errorfile": None},
    }


def command(url: str, work: str, ffmpeg_dir, browser: str = "", extra=()) -> list[str]:
    """The child's argument list. The link always comes last, after "--"."""
    config = os.path.join(work, ".gallery-dl.json")
    with open(config, "w", encoding="utf-8") as f:
        json.dump(_config(work, ffmpeg_dir), f)
    args = [*self_command(), "--gallery-dl", "--config-ignore", "--config-json", config]
    if browser:
        args += ["--cookies-from-browser", browser]
    return [*args, *extra, "--", url]


def _env() -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    return env


_RUN = {"stdin": subprocess.DEVNULL, "env": None}
if sys.platform == "win32":
    _RUN["creationflags"] = subprocess.CREATE_NO_WINDOW


def _last_error(stderr: str) -> str:
    """gallery-dl's most useful error line, without its "[name][error]" prefix."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines if "][error]" in line] or lines
    return errors[-1].split("] ", 1)[-1] if errors else "gallery-dl couldn't read this post."


def kind_of(url: str, meta: dict) -> str:
    """"photo", "video" or "audio" for one item of a post."""
    ext = str(meta.get("extension") or "").lower()
    if meta.get("type") == "audio" or ext in AUDIO_EXT:
        return "audio"
    if url.startswith("ytdl:") or ext in VIDEO_EXT or meta.get("type") == "video":
        return "video"
    return "photo"


def _first(meta: dict, *keys) -> str:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, dict):
            value = value.get("uniqueId") or value.get("username") or value.get("name")
        if value:
            return str(value)
    return ""


def listing(url: str, work: str, ffmpeg_dir, browser: str = "", timeout: int = 120) -> dict:
    """What a post contains, without downloading it (gallery-dl -j). Raises GalleryError."""
    r = subprocess.run(command(url, work, ffmpeg_dir, browser, ["--dump-json"]),
                       capture_output=True, timeout=timeout, **{**_RUN, "env": _env()})
    out = r.stdout[:MAX_LISTING].decode("utf-8", "replace")
    try:
        messages = json.loads(out) if out.strip() else []
    except ValueError:
        messages = []
    items, external, meta0 = [], [], {}
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, list) or not message:
            continue
        if message[0] == -1:  # an error
            info = message[1] if len(message) > 1 and isinstance(message[1], dict) else {}
            raise GalleryError(f"{info.get('error', '')}: {info.get('message', '')}")
        if message[0] == 2 and len(message) > 1 and isinstance(message[1], dict):
            meta0 = meta0 or message[1]
        elif message[0] == 3 and len(message) > 2 and isinstance(message[2], dict):
            items.append({"url": str(message[1]), "kind": kind_of(str(message[1]), message[2]),
                          "ext": str(message[2].get("extension") or "")})
            meta0 = meta0 or message[2]
        elif message[0] == 6 and len(message) > 1:  # points to another site (e.g. an embedded video)
            external.append(str(message[1]))
    if not items and not external:
        raise GalleryError(_last_error(r.stderr.decode("utf-8", "replace")) if r.returncode else
                           "no photos or videos found")
    items = items[:MAX_ITEMS]
    description = _first(meta0, "description", "desc", "content", "title", "caption")
    return {
        "items": items,
        "external": external,
        "title": description.strip().splitlines()[0][:150] if description.strip() else "",
        "uploader": _first(meta0, "username", "author", "owner", "user", "fullname"),
        "id": _first(meta0, "post_shortcode", "shortcode", "post_id", "id"),
        "thumbnail": next((i["url"] for i in items if i["kind"] == "photo" and i["url"].startswith("http")), ""),
        "photos": sum(i["kind"] == "photo" for i in items),
        "videos": sum(i["kind"] == "video" for i in items),
        "audio": any(i["kind"] == "audio" for i in items),
    }


def download(url: str, work: str, ffmpeg_dir, *, browser: str = "", audio_only: bool = False,
             total: int = 0, progress=lambda done, total: None, cancelled=lambda: False) -> list[str]:
    """Download every item of a post into work, in the post's order. Returns the file paths.
    Raises GalleryError, or InterruptedError if cancelled."""
    extra = ["--filter", "extension in ('mp3', 'm4a', 'aac', 'opus', 'ogg', 'wav')"] if audio_only else []
    proc = subprocess.Popen(command(url, work, ffmpeg_dir, browser, extra), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **{**_RUN, "env": _env()})
    lines: queue.Queue = queue.Queue()
    errors: list[bytes] = []

    def read_out():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def read_err():
        errors.append(proc.stderr.read(1024 * 1024))

    threading.Thread(target=read_out, daemon=True).start()
    threading.Thread(target=read_err, daemon=True).start()
    paths: list[str] = []
    work_real = os.path.realpath(work)
    try:
        while True:
            if cancelled():
                raise InterruptedError
            try:
                line = lines.get(timeout=0.3)
            except queue.Empty:
                continue
            if line is None:
                break
            path = line.decode("utf-8", "replace").strip()
            if path.startswith("# "):  # gallery-dl marks skipped files like this
                path = path[2:]
            if (path and os.path.isfile(path) and os.path.dirname(os.path.realpath(path)) == work_real
                    and path not in paths):
                paths.append(path)
                progress(len(paths), max(total, len(paths)))
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    time.sleep(0.05)
    if not paths:
        stderr = b"".join(errors).decode("utf-8", "replace")
        raise GalleryError(_last_error(stderr) if stderr.strip() else "no photos or videos found")
    return paths
