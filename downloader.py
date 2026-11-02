"""Download logic: fetching info, the download queue, and friendly errors.

Videos go through yt-dlp (as a library). Photo posts, carousels and slideshows go through
gallery-dl (gallery.py), and Spotify songs, albums and playlists through spotify.py.
"""
import atexit
import base64
import importlib.util
import io
import itertools
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

import yt_dlp
import yt_dlp.globals
from yt_dlp.networking.impersonate import ImpersonateTarget

import gallery
import links
import safety
import spotify
import updater

# Never load yt-dlp plugins: they are Python code picked up from folders in the user's
# home (and next to the app) and would run inside this app. Same as --no-plugin-dirs.
yt_dlp.globals.plugin_dirs.value = []
# yt-dlp runs the bundled Deno (sandboxed: no network, no files) for YouTube. Stop it phoning
# home for updates, and give it a private, temporary folder for its own cache files, so it
# leaves nothing behind. Dlr's child processes share their parent's folder.
os.environ["DENO_NO_UPDATE_CHECK"] = "1"
os.environ["DENO_NO_PROMPT"] = "1"
if not os.environ.get("DLR_DENO_DIR"):
    # Leftovers of a Dlr that was force-quit (only our own names, at least a day old).
    for _old in Path(tempfile.gettempdir()).glob("dlr-deno-*"):
        try:
            if _old.is_dir() and not _old.is_symlink() and time.time() - _old.stat().st_mtime > 86400:
                shutil.rmtree(_old, ignore_errors=True)
        except OSError:
            pass
    _deno_dir = tempfile.mkdtemp(prefix="dlr-deno-")
    os.environ["DLR_DENO_DIR"] = os.environ["DENO_DIR"] = _deno_dir
    atexit.register(shutil.rmtree, _deno_dir, True)


class DownloaderError(Exception):
    """An error with a message that is safe to show to the user."""


class JobCancelled(yt_dlp.utils.DownloadCancelled):
    """The user stopped the download (yt-dlp lets this pass straight through)."""

    msg = "The download was cancelled."


# Running from source, FFmpeg may come from the computer (apps launched from Finder don't
# get Homebrew's PATH, so the usual places are checked too). The app uses its own.
_FFMPEG_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]

REINSTALL = "Reinstall Dlr from its download page."
NEEDS_FFMPEG = ("This site only sends picture and sound separately, and Dlr's FFmpeg, which combines "
                f"them, is missing. {REINSTALL}")
FFMPEG_MISSING = f"Dlr's FFmpeg is missing, so nothing was downloaded. {REINSTALL}"


def _bundled_dir(name: str) -> str:
    """Where the app keeps a bundled tool (packaging/get_ffmpeg.py, get_deno.py): inside the
    app, or in packaging/ when running from source."""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "packaging", name)


def find_ffmpeg():
    """Folder that holds both ffmpeg and ffprobe, or None. The app's own copy comes first."""
    for d in [_bundled_dir("ffmpeg"), None, *_FFMPEG_DIRS]:
        ffmpeg = shutil.which("ffmpeg", path=d)
        if ffmpeg and shutil.which("ffprobe", path=os.path.dirname(ffmpeg)):
            return os.path.dirname(ffmpeg)
    return None


def find_deno():
    """Path to Deno, or None. yt-dlp runs it to solve YouTube's challenges. The app uses only
    its own copy; running from source, packaging/deno/ (get_deno.py) comes first."""
    dirs = [_bundled_dir("deno")]
    if not getattr(sys, "frozen", False):
        dirs += [None, *_FFMPEG_DIRS, os.path.expanduser("~/.deno/bin")]
    for d in dirs:
        deno = shutil.which("deno", path=d)
        if deno:
            return deno
    return None


def missing_tools() -> list[dict]:
    """Bundled tools that are somehow missing, with how to get them back.
    (yt-dlp and gallery-dl are inside the app, or checked by app.py when running from source.)"""
    missing = []
    if not find_ffmpeg():
        missing.append({"name": "FFmpeg", "why": "needed to combine picture and sound"})
    if not find_deno():
        missing.append({"name": "Deno", "why": "needed for YouTube"})
    for tool in missing:
        if getattr(sys, "frozen", False):
            tool["fix"] = REINSTALL
        else:
            tool["command"] = f"python packaging/get_{tool['name'].lower()}.py"
    return missing


# ---- logins from the browser (only when a site asks for one) ----

BROWSER_NAMES = {"safari": "Safari", "chrome": "Chrome", "firefox": "Firefox", "brave": "Brave",
                 "edge": "Edge", "opera": "Opera", "vivaldi": "Vivaldi", "chromium": "Chromium"}
_MAC_BROWSERS = {"com.apple.safari": "safari", "com.google.chrome": "chrome", "org.mozilla.firefox": "firefox",
                 "com.brave.browser": "brave", "com.microsoft.edgemac": "edge", "com.operasoftware.opera": "opera",
                 "com.vivaldi.vivaldi": "vivaldi", "org.chromium.chromium": "chromium"}
_WINDOWS_BROWSERS = {"chromehtml": "chrome", "msedgehtm": "edge", "firefoxurl": "firefox", "bravehtml": "brave",
                     "operastable": "opera", "vivaldihtm": "vivaldi"}


def default_browser() -> str:
    """The default browser, as yt-dlp names it, or "" if unknown or one yt-dlp can't read."""
    try:
        if sys.platform == "darwin":
            import plistlib
            prefs = os.path.expanduser(
                "~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist")
            with open(prefs, "rb") as f:
                handlers = plistlib.load(f).get("LSHandlers", [])
            bundle = next((h.get("LSHandlerRoleAll", "") for h in handlers
                           if h.get("LSHandlerURLScheme") == "https"), "com.apple.safari")
            return _MAC_BROWSERS.get(bundle.lower(), "")
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations"
                                 r"\UrlAssociations\https\UserChoice")
            prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            return next((b for p, b in _WINDOWS_BROWSERS.items() if prog_id.startswith(p)), "")
    except Exception:
        pass
    return ""


def login_browser(setting: str) -> str:
    """The browser whose login to use for a setting ("auto", "off" or a browser), or ""."""
    if setting == "auto":
        return default_browser()
    return setting if setting in BROWSER_NAMES else ""


def _tool(ffmpeg_dir: str, name: str) -> str:
    return shutil.which(name, path=ffmpeg_dir) or os.path.join(ffmpeg_dir, name)


# Options for every FFmpeg/ffprobe run: no input (a windowed Windows app has none, which can
# make starting a program fail), UTF-8 output whatever the system language, and on Windows
# no console window flashing up for each run.
RUN_OPTS = {"stdin": subprocess.DEVNULL, "encoding": "utf-8", "errors": "replace"}
if sys.platform == "win32":
    RUN_OPTS["creationflags"] = subprocess.CREATE_NO_WINDOW


# FFmpeg may only read local files, and only real audio/video containers: a downloaded
# "video" that is really a playlist (HLS, concat ...) could otherwise make FFmpeg
# open other files or web addresses.
LOCAL_ONLY = ["-protocol_whitelist", "file"]
_MEDIA_FORMATS = {"mov", "matroska", "mp3", "aac", "ogg", "flv", "mpegts", "wav"}


def probe_streams(ffmpeg_dir: str, path: str) -> list[dict]:
    """The audio/video streams in a file, ignoring cover art. Empty if it isn't a media file."""
    r = subprocess.run(
        [_tool(ffmpeg_dir, "ffprobe"), *LOCAL_ONLY, "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,bit_rate"
         ":stream_disposition=attached_pic:format=format_name", "-of", "json", os.path.abspath(path)],
        capture_output=True, text=True, timeout=120, **RUN_OPTS)
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        return []
    container = (data.get("format") or {}).get("format_name", "").split(",")[0]
    if container not in _MEDIA_FORMATS:
        return []
    return [s for s in data.get("streams", []) if s.get("codec_type") in ("video", "audio")
            and not s.get("disposition", {}).get("attached_pic")]


def frame_timing(ffmpeg_dir: str, path: str, stream_index: int) -> dict:
    """Frame timing of a video stream, read from its packets.

    "junk" counts empty placeholder samples that last almost no time (some TikTok
    uploads have thousands). QuickTime counts them as frames, sees a huge frame
    rate and opens the video as slow motion.
    """
    r = subprocess.run(
        [_tool(ffmpeg_dir, "ffprobe"), *LOCAL_ONLY, "-v", "error", "-select_streams", str(stream_index),
         "-show_entries", "packet=duration_time,size", "-of", "csv=p=0", os.path.abspath(path)],
        capture_output=True, text=True, timeout=600, **RUN_OPTS)
    durations, junk = [], 0
    for line in r.stdout.splitlines():
        try:
            duration, size = (float(x) for x in line.split(",")[:2])
        except ValueError:
            continue
        if duration < _JUNK_SECONDS and size < _JUNK_BYTES:
            junk += 1
        else:
            durations.append(duration)
    body = sorted(durations[:-1] or durations)  # the last frame's duration is often a stub
    if not body:
        return {"junk": junk, "fps": 0.0, "too_fast": False, "vfr": False}
    median = body[len(body) // 2]
    fps = 1 / median if median else 0.0
    uneven = sum(1 for d in body if abs(d - median) > 0.25 * median)
    very_short = sum(1 for d in body if d < 1 / 120)
    total = sum(durations)
    return {
        "junk": junk,
        "fps": fps,
        "avg_fps": len(durations) / total if total else fps,
        "peak_fps": 1 / body[len(body) // 10] if body[len(body) // 10] else fps,  # fastest common rate
        # Above 60fps, or many frames shorter than 1/120s, QuickTime treats as slow motion.
        "too_fast": fps > 60.5 or very_short > 0.01 * len(body),
        "vfr": uneven > 0.05 * len(body),
    }


_JUNK_SECONDS = 0.001
_JUNK_BYTES = 64


def make_apple_compatible(ffmpeg_dir: str, path: str, expect_audio: bool) -> str:
    """Rewrite a downloaded video as an MP4 that QuickTime and iPhone play normally.

    Keeps exactly one video and one audio stream and drops all source metadata,
    chapters and data/timecode streams. H.264/HEVC are copied (HEVC tagged hvc1)
    with empty placeholder frames removed; VP9/AV1, variable frame rate and
    anything above 60fps is re-encoded at a constant frame rate (max 60fps) so it
    never opens as slow motion. Audio that isn't AAC is converted to AAC. Raises
    CheckFailed if the picture or sound is missing. Returns the final file path.
    """
    streams = probe_streams(ffmpeg_dir, path)
    video = [s for s in streams if s["codec_type"] == "video"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    if not video:
        raise CheckFailed("picture")
    if expect_audio and not audio:
        raise CheckFailed("sound")

    v = max(video, key=lambda s: (s.get("width") or 0) * (s.get("height") or 0))
    timing = frame_timing(ffmpeg_dir, path, v["index"])
    final = os.path.splitext(path)[0] + ".mp4"
    a = audio[0] if audio else None

    if v["codec_name"] in ("h264", "hevc") and not (timing["too_fast"] or timing["vfr"]):
        tag = "avc1" if v["codec_name"] == "h264" else "hvc1"
        copy = ["-c:v", "copy", "-tag:v", tag]
        if timing["junk"]:
            copy += ["-bsf:v", f"noise=drop=lt(duration*tb\\,{_JUNK_SECONDS})*lt(size\\,{_JUNK_BYTES})"]
        _remux(ffmpeg_dir, path, final, v, a, [copy])
        timing = frame_timing(ffmpeg_dir, final, 0)
        if timing["too_fast"] or timing["vfr"]:
            # Copying wasn't enough: fix the speed by re-encoding at a constant rate.
            _remux(ffmpeg_dir, final, final, {"index": 0}, a and {"index": 1, "codec_name": "aac"},
                   _encode_args(timing))
    else:
        _remux(ffmpeg_dir, path, final, v, a, _encode_args(timing))

    if final != path:
        safety.remove_inside(os.path.dirname(os.path.abspath(path)), path)
    streams = probe_streams(ffmpeg_dir, final)
    kinds = [s["codec_type"] for s in streams]
    if "video" not in kinds:
        raise CheckFailed("picture")
    if a and "audio" not in kinds:
        raise CheckFailed("sound")
    timing = frame_timing(ffmpeg_dir, final, next(s["index"] for s in streams if s["codec_type"] == "video"))
    if timing["junk"] or timing["too_fast"] or timing["vfr"]:
        raise CheckFailed("speed")
    return final


def _encode_args(timing: dict) -> list[list[str]]:
    """Encoder options to try in order, at a constant frame rate of at most 60fps."""
    # Use the fastest rate the video really has so motion stays smooth, capped at 60.
    fps = min(60, round(timing.get("peak_fps") or timing["fps"] or 30)) or 30
    encoders = [["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-tag:v", "avc1"]]
    if sys.platform == "darwin":
        # The Mac's hardware encoder is much faster.
        encoders.insert(0, ["-c:v", "hevc_videotoolbox", "-q:v", "70", "-tag:v", "hvc1", "-pix_fmt", "yuv420p"])
    # "-fps_mode" needs FFmpeg 5.1+; older builds only know "-vsync".
    return [["-vf", f"fps={fps}", option, "cfr", *encoder]
            for option in ("-fps_mode", "-vsync") for encoder in encoders]


def _remux(ffmpeg_dir: str, src: str, dst: str, v: dict, a, video_attempts: list[list[str]]):
    """Write src to dst with one video + one audio stream and no source metadata."""
    folder = os.path.dirname(os.path.abspath(dst))
    # Empty placeholder frames count as decode errors; don't let them stop a re-encode.
    base = [_tool(ffmpeg_dir, "ffmpeg"), "-v", "error", "-y", *LOCAL_ONLY, "-i", os.path.abspath(src),
            "-max_error_rate", "1",
            "-map", f"0:{v['index']}", "-map_metadata", "-1", "-map_chapters", "-1", "-dn"]
    tail = []
    if a:
        tail += ["-map", f"0:{a['index']}"]
        tail += ["-c:a", "copy"] if a["codec_name"] == "aac" else ["-c:a", "aac", "-b:a", "192k"]
    tail += ["-movflags", "+faststart", "-f", "mp4"]
    for video_args in video_attempts:
        tmp = safety.temp_file(folder, ".mp4")
        r = subprocess.run(base + video_args + tail + [tmp], capture_output=True, text=True, **RUN_OPTS)
        if r.returncode == 0 and os.path.getsize(tmp):
            os.replace(tmp, dst)
            return
        safety.remove_inside(folder, tmp)
    raise CheckFailed("convert")


class CheckFailed(Exception):
    """The downloaded file is missing its picture or sound (or couldn't be converted)."""

    def __init__(self, missing: str):
        super().__init__(missing)
        self.missing = missing  # "picture", "sound", "convert" or "speed"


FAILED_TEXT = {
    "picture": "Failed: no picture. Different versions of this video were tried and none "
               "had a picture, so nothing was saved.",
    "sound": "Failed: no sound. Different versions of this video were tried and none "
             "had sound, so nothing was saved.",
    "speed": "Failed: the video kept playing at the wrong speed (slow motion) even after fixing it, "
             "so nothing was saved.",
    "convert": "Failed: the video couldn't be converted to a format your Mac and iPhone can play, "
               "so nothing was saved.",
}


def _fps(rate) -> float:
    try:
        num, _, den = str(rate).partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def video_label(width, height, fps) -> str:
    """e.g. "1080p · 60fps". Uses the shorter side so vertical videos read right."""
    side = min(width, height) if width and height else height
    if not side:
        return ""
    return f"{side}p · {round(fps)}fps" if fps else f"{side}p"


def file_label(ffmpeg_dir: str, path: str, mp3: bool) -> str:
    """The quality actually saved, read from the file."""
    for s in probe_streams(ffmpeg_dir, path):
        if mp3 and s["codec_type"] == "audio":
            kbps = round(int(s.get("bit_rate") or 0) / 1000)
            return f"MP3 · {kbps} kbps" if kbps else "MP3"
        if not mp3 and s["codec_type"] == "video":
            # The average is skewed by empty filler frames some uploads contain
            # (a 60fps TikTok read as 398fps), so cap it at the stream's nominal rate.
            avg, nominal = _fps(s.get("avg_frame_rate")), _fps(s.get("r_frame_rate"))
            fps = avg if 0 < avg <= nominal * 1.01 else nominal
            return video_label(s.get("width"), s.get("height"), fps if fps <= 240 else 0)
    return ""


def _side(label: str) -> int:
    m = re.match(r"(\d+)p", label or "")
    return int(m.group(1)) if m else 0


# (pattern in yt-dlp's or gallery-dl's message, what to tell the user). First match wins.
NETWORK_ERROR = "Network error. Check your internet connection and try again."
DRM_ERROR = "This video is copy-protected, so it can't be downloaded."
LOGIN_ERROR = "This site needs login — turn on logins in settings"
STORIES_LOGIN = "Stories need login — turn on logins in settings"
NO_SOUND = "This post has no sound to save as MP3."
NO_MEDIA = "This post has no photos or videos that can be saved."
SPOTIFY_LIST_MP3 = "Spotify albums and playlists are saved as MP3. Use the MP3 button."
RATE_LIMITED = "This site is limiting downloads right now. Wait a few minutes and try again."
NO_FORMAT = "No version of this video can be saved this way. Try the other button, or another link."
FORBIDDEN = "The site refused the download. Try again in a few minutes."
FFMPEG_FAILED = f"Dlr's FFmpeg is missing or failed. {REINSTALL}"

_ERRORS = [
    (r"\bdrm\b|copy[- ]protect", DRM_ERROR),
    # Reading the browser's login failed (macOS privacy settings or Keychain).
    (r"full disk access|binarycookies|cookies?.*operation not permitted|operation not permitted.*cookies"
     r"|cookies? database|failed to (decrypt|load) cookies|keychain|keyring|could not find .* cookies",
     "Dlr couldn't read your browser's login. For Safari, allow Dlr in System Settings › Privacy & "
     "Security › Full Disk Access. For other browsers, click Allow when your Mac asks about the keychain."),
    (r"private video|video is private|this account is private",
     "This video is private. Only the owner or approved accounts can watch it."),
    (r"not a bot",
     "YouTube wants to confirm you're not a bot. Turn on logins in Settings and log in to YouTube in your browser."),
    (r"age[- ]restricted|confirm your age|inappropriate for some users|certain audiences",
     "This video is age-restricted. Turn on logins in Settings and log in to the site in your browser."),
    (r"too many requests|http error 429|rate[- ]?limit|please wait a few minutes", RATE_LIMITED),
    (r"login required|log in|sign in|logged[- ]in|requires authentication|account authentication|use --cookies"
     r"|authorizationerror|authenticationerror|redirect to login|login page|blocked by network security",
     LOGIN_ERROR),
    (r"available in your country|geo[- ]?restrict|from your location",
     "This video isn't available in your country."),
    (r"no photos or videos found|no media found|there is no video in this post|no video formats found",
     NO_MEDIA),
    (r"unsupported url|no video could be found|is not a valid url|no suitable extractor",
     "This site or link isn't supported. Make sure it's a link to a single video or post."),
    (r"requested format is not available", NO_FORMAT),
    (r"video unavailable|is unavailable|not available|has been removed|does not exist|http error 404"
     r"|404 not found|notfounderror|this post is unavailable",
     "This video is unavailable. It may have been deleted."),
    (r"javascript runtime|js runtime|\bdeno\b|n challenge|signature solving",
     f"Dlr's YouTube helper (Deno) is missing or failed. {REINSTALL}"),
    (r"http error 403|forbidden", FORBIDDEN),
    (r"http error 5\d\d|\b50[0234] ", "The site had a problem sending this. Try again in a few minutes."),
    (r"cannot parse data|unable to extract|please report this issue",
     "Dlr couldn't read this page: the site may have changed. Try again later (Dlr updates itself)."),
    (r"unable to download webpage|getaddrinfo|timed out|connection|network is unreachable|nodename nor servname",
     NETWORK_ERROR),
    (r"ffmpeg|ffprobe", FFMPEG_FAILED),
]

# Errors a logged-in browser can fix: retried once with the browser's login.
_NEEDS_LOGIN = re.compile(r"not a bot|log ?in|sign in|logged[- ]in|requires authentication|account authentication"
                          r"|use --cookies|too many requests|http error 429|rate[- ]?limit|private|age[- ]restricted"
                          r"|confirm your age|authorizationerror|authenticationerror|blocked by network security", re.I)
_RATE_LIMITED = re.compile(r"too many requests|http error 429|\b429\b|rate[- ]?limit|please wait a few minutes", re.I)
_FORBIDDEN = re.compile(r"http error 403|\b403\b|forbidden", re.I)
INSTAGRAM_WAIT = 30  # seconds to wait before retrying when Instagram is rate-limiting


def login_message(url: str) -> str:
    """What to say when a link needs a login and logins are off (Settings › Logins from)."""
    name = {"reddit": "Reddit", "instagram": "This Instagram post"}.get(links.site(url), "This site")
    return f"{name} needs login — turn on logins in settings"


def is_login_message(message: str) -> bool:
    """A message about a missing or failed login: a newer yt-dlp can't fix those."""
    return "needs login" in message or message.startswith("This site needs you to be logged in")


def needs_login(exc: Exception, url: str = "") -> bool:
    if _NEEDS_LOGIN.search(str(exc)):
        return True
    # Reddit answers 403 to logged-out downloads it doesn't like.
    return links.site(url) == "reddit" and bool(_FORBIDDEN.search(str(exc)))


def friendly_error(exc: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    msg = re.sub(r"^ERROR:\s*", "", msg).strip()
    msg = re.sub(r"^\[[\w:]+\] [^:]*: ", "", msg)  # drop "[youtube] abc123: "
    low = msg.lower()
    for pattern, text in _ERRORS:
        if re.search(pattern, low):
            return text
    if not msg or len(msg) > 200 or "Traceback" in msg:
        return "Something went wrong. Try again in a few minutes."
    return msg


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


IMPERSONATE = importlib.util.find_spec("curl_cffi") is not None  # yt-dlp's --impersonate needs it
# Sites that block requests that don't look like a real browser.
_IMPERSONATE_SITES = ("tiktok",)


def _base_opts(url: str = "") -> dict:
    opts = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
        "windowsfilenames": True,
        "cachedir": False,  # yt-dlp keeps nothing on disk between downloads
    }
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    deno = find_deno()
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}  # the bundled one, never another
    if IMPERSONATE and links.site(url) in _IMPERSONATE_SITES:
        opts["impersonate"] = ImpersonateTarget("chrome")  # like --impersonate chrome
    return opts


def build_opts(quality: str, out_dir: str, url: str = "") -> dict:
    opts = _base_opts(url)
    opts["outtmpl"] = os.path.join(out_dir, "%(title).150B [%(id)s].%(ext)s")
    if quality == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": MP3_KBPS,  # constant bitrate, like --audio-quality 320K
        }]
    else:
        # "res" is the shorter side, so 1080p also works for vertical videos. With a
        # limit, yt-dlp picks the best format up to it, or the closest above if none fit.
        res = "res" if quality == "best" else f"res:{quality}"
        opts["format"] = _pick_video
        # Highest resolution and frame rate first, whatever the codec (HEVC gets tagged
        # hvc1 afterwards); between equal ones, prefer H.264 + AAC.
        opts["format_sort"] = [res, "fps", "vcodec:h264", "acodec:m4a"]
        opts["merge_output_format"] = "mp4"
    return opts


_H264 = re.compile(r"^(avc|h264)")


def _merged(video: dict, audio: dict) -> dict:
    """A video stream and an audio stream to download and merge into one MP4."""
    return {
        "format_id": f"{video['format_id']}+{audio['format_id']}",
        "ext": "mp4",
        "requested_formats": [video, audio],
        "protocol": f"{video.get('protocol')}+{audio.get('protocol')}",
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("fps"),
        "vcodec": video.get("vcodec"),
        "acodec": audio.get("acodec"),
    }


def _pick_video(ctx):
    """yt-dlp format selector: the best video, with the video's own sound.

    H.264 + M4A (AAC) comes first, as it plays everywhere without converting, like
    -f "bv*[vcodec^=avc1]+ba[ext=m4a]", but only when it is as sharp and smooth as the
    best version: a 4K VP9 video isn't swapped for a 1080p H.264 one (it gets converted
    to an Apple-friendly MP4 after downloading instead).

    TikTok sometimes serves its top quality without audio, next to lower-quality
    versions that have it, plus a separate MP3 "audio" track that can be the
    music rather than the video's own sound. So when the best video is silent,
    take the sound from an audio-only stream, else from another version of the
    video, and only as a last resort from the MP3 track.
    """
    formats = _without_watermark(ctx["formats"])  # already sorted, worst to best
    videos = [f for f in formats if f.get("vcodec") != "none"]
    if not videos:
        if formats:
            yield formats[-1]
        return
    best = videos[-1]
    audio_only = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in ("none", None)]

    def rank(f):
        return min(f.get("height") or 0, f.get("width") or f.get("height") or 0), f.get("fps") or 0

    h264 = [f for f in videos if _H264.match(f.get("vcodec") or "") and rank(f) >= rank(best)]
    m4a = [f for f in audio_only if f.get("ext") == "m4a"]
    if h264 and h264[-1].get("acodec") not in ("none", None):
        yield h264[-1]
        return
    if h264 and m4a:
        yield _merged(h264[-1], m4a[-1])
        return

    if best.get("acodec") != "none":
        yield best
        return
    own = [f for f in audio_only if f.get("acodec") != "mp3"]
    with_sound = [f for f in videos if f.get("acodec") not in ("none", None)]
    if own:
        audio = own[-1]
    elif with_sound:
        audio = dict(with_sound[-1], vcodec="none")  # only its sound gets merged in
    elif audio_only:
        audio = audio_only[-1]
    else:
        yield best
        return
    yield _merged(best, audio)


def _watermarked(f: dict) -> bool:
    return "watermark" in f"{f.get('format_note') or ''} {f.get('format_id') or ''}".lower()


def _without_watermark(formats: list) -> list:
    """TikTok also offers a version with its logo burned in: never pick it if there's another."""
    clean = [f for f in formats if not _watermarked(f)]
    return clean if any(f.get("vcodec") != "none" for f in clean) else formats


def retry_format(tried: list[str]) -> str:
    """Format for the second attempt: the H.264 + AAC version, avoiding what was tried."""
    avoid = "".join(f"[format_id!={f}]" for f in tried)
    h264, aac = "[vcodec~='^(avc|h264)']", "[acodec~='^(mp4a|aac)']"
    return "/".join([
        f"bv*{h264}{avoid}+ba{aac}", f"b{h264}{aac}{avoid}",  # a different H.264 + AAC version
        f"bv*{avoid}+ba[acodec!=mp3]", f"b{avoid}",            # any different version
        f"bv*{h264}+ba{aac}", f"b{h264}{aac}", "bv*+ba/b",      # same as before, downloaded again
    ])


MP3_KBPS = "320"
MP3_LABEL = f"MP3 · {MP3_KBPS} kbps"


def fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_speed(bps) -> str:
    if not bps:
        return ""
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024:
            return f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} TB/s"


def fetch_image(url) -> bytes:
    """Download a small image from a public web address (never a local file or network)."""
    url = safety.check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        safety.check_url(r.geturl())  # also after redirects
        return safety.read_limited(r)


def thumbnail_data_url(url: str, size: int = 480) -> str:
    """Download a thumbnail as a small JPEG data URL ("" on failure).

    Some sites refuse thumbnails loaded directly by another page.
    """
    try:
        data = fetch_image(url)
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse "decompression bomb" images
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((size, size))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


# Sites whose media is DRM-protected; yt-dlp can't download from them.
_DRM_SITES = [
    (r"(^|\.)netflix\.com$", "Netflix"),
    (r"(^|\.)disneyplus\.com$|(^|\.)disney\.com$", "Disney+"),
    (r"^music\.apple\.com$", "Apple Music"),
    (r"^tv\.apple\.com$", "Apple TV+"),
    (r"(^|\.)primevideo\.com$", "Amazon Prime Video"),
    (r"^music\.amazon\.", "Amazon Music"),
    (r"(^|\.)hulu\.com$", "Hulu"),
    (r"(^|\.)max\.com$|(^|\.)hbomax\.com$", "Max"),
    (r"(^|\.)paramountplus\.com$", "Paramount+"),
    (r"(^|\.)peacocktv\.com$", "Peacock"),
    (r"(^|\.)tidal\.com$", "Tidal"),
    (r"(^|\.)deezer\.com$", "Deezer"),
    (r"(^|\.)crunchyroll\.com$", "Crunchyroll"),
]


def drm_site(url: str) -> str:
    """Name of the copy-protected service a link belongs to, or ""."""
    m = re.match(r"(?:[a-z][a-z0-9+.-]*://)?([^/?#:]+)(/[^?#]*)?", url.strip(), re.I)
    if not m:
        return ""
    host = m.group(1).lower().removeprefix("www.")
    path = m.group(2) or ""
    if re.match(r"amazon\.[a-z.]+$", host) and path.startswith("/gp/video"):
        return "Amazon Prime Video"
    return next((name for pattern, name in _DRM_SITES if re.search(pattern, host)), "")


class EngineError(DownloaderError):
    """yt-dlp or gallery-dl couldn't get it (the message is already plain English)."""


def with_login_retry(run, browser_setting: str, on_retry=lambda: None, url: str = "", wait=time.sleep):
    """Call run(opts_extra). If the site wants a login, call it once more with the browser's
    login; if Instagram is limiting downloads, wait a little and try once more. yt-dlp and
    gallery-dl read the cookies straight from the browser each time and keep them in memory
    only: Dlr never copies or saves them."""
    try:
        return run({})
    except (yt_dlp.utils.DownloadCancelled, InterruptedError):
        raise
    except Exception as e:
        first = e
    browser = login_browser(browser_setting)
    login = {"cookiesfrombrowser": (browser,)} if browser else {}
    if links.site(url) == "instagram" and _RATE_LIMITED.search(str(first)):
        on_retry()
        wait(INSTAGRAM_WAIT)
        return run(login)
    if not needs_login(first, url):
        raise first
    if not browser:
        if friendly_error(first) == LOGIN_ERROR:
            raise EngineError(login_message(url)) from None
        raise first
    on_retry()
    try:
        return run(login)
    except (yt_dlp.utils.DownloadCancelled, InterruptedError):
        raise
    except Exception as e:
        if needs_login(e, url) and friendly_error(e) == friendly_error(first):
            name = BROWSER_NAMES[browser]
            if friendly_error(e) == LOGIN_ERROR:
                raise EngineError(f"This site needs you to be logged in. Dlr tried your {name} login: "
                                  f"make sure you're logged in to this site in {name}.") from None
            raise EngineError(f"{friendly_error(e)} (Dlr tried your {name} login: make sure you're "
                              f"logged in to this site in {name}.)") from None
        raise


def _browser_of(extra: dict) -> str:
    return (extra.get("cookiesfrombrowser") or ("",))[0]


# ---- what a link is, and how to download it ----

PLAYLIST_ERROR = "That's a playlist or profile. Paste a link to a single video or post."
_NO_VIDEO = re.compile(r"no video formats|no media found|there is no video|unsupported url"
                       r"|no video could be found|no suitable extractor", re.I)
_SITE_NAMES = {"tiktok": "TikTok", "instagram": "Instagram", "reddit": "Reddit", "x": "X",
               "facebook": "Facebook", "youtube": "YouTube"}

# How each recent link is downloaded, so the download does what the card showed. In memory
# only, and only the last few: never saved.
_routes: dict[str, dict] = {}
_routes_lock = threading.Lock()


def _remember(url: str, route: dict) -> dict:
    with _routes_lock:
        while len(_routes) >= 30:
            _routes.pop(next(iter(_routes)))
        _routes[url] = route
    return route


def _checked(url: str) -> str:
    try:
        url = safety.check_url(url)
    except safety.UnsafeInput as e:
        raise DownloaderError(str(e)) from None
    protected = drm_site(url)
    if protected:
        raise DownloaderError(f"{protected} is copy-protected, so it can't be downloaded.")
    return url


def _resolved(url: str, browser_setting: str) -> str:
    """The link a share link points to, without tracking parameters."""
    try:
        url = links.resolve(url)
    except safety.UnsafeInput as e:
        raise DownloaderError(str(e)) from None
    if links.is_story(url) and not login_browser(browser_setting):
        raise DownloaderError(STORIES_LOGIN)
    return url


def _has_video(info: dict) -> bool:
    return any(f.get("vcodec") != "none" for f in info.get("formats") or [])


def _lookup(url: str, browser_setting: str) -> tuple[dict, dict | None]:
    """yt-dlp's info for a link: (raw info, info with formats chosen) or (raw, None) when
    it's a post with several items or no video, which gallery-dl handles."""
    gallery_site = links.site(url) in links.GALLERY_SITES

    def run(extra):
        # Same format rules as the download, so we know what quality it will get.
        with yt_dlp.YoutubeDL({**build_opts("best", ".", url), **extra}) as ydl:
            raw = ydl.extract_info(url, download=False, process=False)
            if raw.get("_type") in ("playlist", "multi_video") or raw.get("entries") is not None:
                # A post with several items comes as a list; a profile or playlist as pages.
                if not gallery_site or not isinstance(raw.get("entries"), list):
                    raise DownloaderError(PLAYLIST_ERROR)
                raw["entries"] = [e for e in raw["entries"] if isinstance(e, dict)][:gallery.MAX_ITEMS]
                return raw, None
            if gallery_site and raw.get("_type") in (None, "video") and not _has_video(raw):
                return raw, None
            return raw, ydl.process_ie_result(raw, download=False)

    return with_login_retry(run, browser_setting, url=url)


def _media_from(raw: dict) -> list[dict]:
    """The photos and videos of a post as yt-dlp sees them, for when gallery-dl can't read
    it (Instagram shows yt-dlp public posts without a login, but not gallery-dl)."""
    media = []
    for entry in raw.get("entries") if raw.get("entries") is not None else [raw]:
        if _has_video(entry):
            media.append({"kind": "video", "entry": entry})
            continue
        thumbs = [t for t in entry.get("thumbnails") or [] if t.get("url")]
        if thumbs:
            best = max(thumbs, key=lambda t: ((t.get("width") or 0) * (t.get("height") or 0),
                                              t.get("preference") or 0))
            media.append({"kind": "photo", "url": best["url"], "headers": entry.get("http_headers") or {}})
    return media


def _gallery_route(url: str, browser_setting: str, raw: dict | None = None) -> dict:
    """A photo post, carousel or slideshow: gallery-dl's list of its items (or yt-dlp's)."""
    media = _media_from(raw) if raw and links.site(url) == "instagram" else []
    work = tempfile.mkdtemp(prefix="dlr-")  # holds only gallery-dl's private settings file
    try:
        listing = with_login_retry(
            lambda extra: gallery.listing(url, work, find_ffmpeg(), _browser_of(extra)), browser_setting, url=url)
    except Exception as e:
        if not media:
            if isinstance(e, DownloaderError):
                raise
            raise EngineError(friendly_error(e)) from None
        listing = None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if listing and not listing["items"]:
        # A post that only links to a video elsewhere (e.g. Reddit -> YouTube): follow it.
        for target in listing["external"]:
            try:
                target = links.resolve(target)
            except safety.UnsafeInput:
                continue
            return {"kind": "video", "url": target}
        raise DownloaderError(NO_MEDIA)
    if listing:
        summary = {k: listing[k] for k in ("title", "uploader", "id", "thumbnail", "photos", "videos", "audio")}
    else:
        description = str(raw.get("description") or raw.get("title") or "").strip()
        first_photo = next((m["url"] for m in media if m["kind"] == "photo"), "")
        summary = {
            "title": description.splitlines()[0][:150] if description else "",
            "uploader": raw.get("channel") or raw.get("uploader") or "",
            "id": str(raw.get("id") or ""),
            "thumbnail": first_photo or raw.get("thumbnail") or "",
            "photos": sum(m["kind"] == "photo" for m in media),
            "videos": sum(m["kind"] == "video" for m in media),
            "audio": False,
        }
    if not summary["photos"] and not summary["videos"] and not summary["audio"]:
        raise DownloaderError(NO_MEDIA)
    return {"kind": "gallery", "listing": listing, "media": media, **summary}


def _route(url: str, browser_setting: str) -> dict:
    """How to download a link: {"kind": "video", "info": ...} or {"kind": "gallery", ...}."""
    with _routes_lock:
        if url in _routes:
            return _routes[url]
    if links.is_photo_link(url):
        return _remember(url, _gallery_route(url, browser_setting))
    try:
        raw, info = _lookup(url, browser_setting)
    except DownloaderError:
        raise
    except Exception as e:
        if links.site(url) in links.GALLERY_SITES and _NO_VIDEO.search(str(e)):
            return _remember(url, _gallery_route(url, browser_setting))
        raise EngineError(friendly_error(e)) from None
    if info is None:
        route = _gallery_route(url, browser_setting, raw)
        if route["kind"] == "video":  # a post linking to a video elsewhere
            return _remember(url, _route(route["url"], browser_setting))
        return _remember(url, route)
    return _remember(url, {"kind": "video", "info": info, "url": url})


def count_label(photos: int, videos: int) -> str:
    """e.g. "3 photos · 1 video"."""
    parts = [f"{n} {word}{'s' if n != 1 else ''}" for n, word in ((photos, "photo"), (videos, "video")) if n]
    return " · ".join(parts)


def fetch_info(url: str, browser_setting: str = "off") -> dict:
    """Look up a link without downloading. Raises DownloaderError."""
    url = _checked(url)
    if spotify.is_spotify(url):
        return _fetch_spotify(url, browser_setting)
    url = _resolved(url, browser_setting)
    route = _route(url, browser_setting)
    if route["kind"] == "gallery":
        site = _SITE_NAMES.get(links.site(url), "")
        return {
            "url": url,
            "kind": "gallery",
            "title": route["title"] or f"{site or 'Photo'} post",
            "thumbnail": route["thumbnail"],
            "thumbData": thumbnail_data_url(route["thumbnail"]),
            "duration": "",
            "uploader": route["uploader"],
            "site": site,
            "label": count_label(route["photos"], route["videos"]) or "Sound only",
            "qualities": [],
            "lowOnly": False,
            "mp3Label": MP3_LABEL if route["audio"] or route["videos"] else "No sound",
        }
    info = route["info"]
    url = route.get("url") or url
    chosen = next((f for f in info.get("requested_formats") or [] if f.get("vcodec") != "none"), info)
    # yt-dlp copies an MP3 source as is, so its bitrate is what gets saved.
    audio = [f for f in info.get("formats") or [] if f.get("vcodec") == "none" and f.get("acodec") not in ("none", None)]
    mp3_label = MP3_LABEL
    if audio and audio[-1].get("acodec") == "mp3":
        kbps = audio[-1].get("abr") or audio[-1].get("tbr")
        mp3_label = f"MP3 · {round(kbps)} kbps" if kbps else "MP3"
    return {
        "url": url,
        "kind": "video",
        "title": info.get("title") or url,
        "thumbnail": info.get("thumbnail") or "",
        "thumbData": thumbnail_data_url(info.get("thumbnail")),
        "duration": fmt_duration(info.get("duration")),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "site": info.get("extractor_key") or "",
        "label": video_label(chosen.get("width"), chosen.get("height"), chosen.get("fps")),
        **quality_options(info.get("formats") or []),
        "mp3Label": mp3_label,
    }


def quality_options(formats: list) -> dict:
    """The video qualities this video really has, highest first, one per resolution, none
    below 480p. If nothing reaches 480p, only the best one is listed and "lowOnly" is set."""
    best_fps: dict[int, float] = {}
    for f in _without_watermark(formats):
        # Only real video: not sound-only, storyboards (preview images) or images.
        if (f.get("vcodec") == "none" or not f.get("height") or f.get("ext") in ("mhtml", "jpg", "png", "webp")
                or "storyboard" in str(f.get("format_note") or "").lower()):
            continue
        side = min(f["height"], f.get("width") or f["height"])
        best_fps[side] = max(best_fps.get(side, 0), f.get("fps") or 0)
    sides = sorted(best_fps, reverse=True)
    good = [s for s in sides if s >= 480]
    picked = good or sides[:1]
    return {
        "qualities": [{"height": s, "label": f"{s}p · {round(best_fps[s])}fps" if best_fps[s] >= 50 else f"{s}p"}
                      for s in picked],
        "lowOnly": not good and bool(sides),
    }


def valid_quality(quality: str) -> bool:
    """"best", "mp3", or a resolution such as "720"."""
    return quality in ("best", "mp3") or (str(quality).isdigit() and 100 <= int(quality) <= 4320)


def _fetch_spotify(url: str, browser_setting: str) -> dict:
    """Spotify song: Spotify's info, with the matching YouTube upload's qualities.
    Album or playlist: its info and number of songs (each is matched when downloading)."""
    try:
        kind, _ = spotify.parse(url)
        if kind != "track":
            c = spotify.collection(url)
        else:
            track, youtube_url = spotify.resolve(url)
    except spotify.SpotifyError as e:
        raise DownloaderError(str(e)) from None
    if kind != "track":
        n = len(c["tracks"])
        return {
            "url": url,
            "kind": "spotify-list",
            "title": c["name"],
            "uploader": c["owner"],
            "thumbnail": c["cover"],
            "thumbData": thumbnail_data_url(c["cover"]),
            "duration": fmt_duration(sum(t["duration"] for t in c["tracks"])),
            "site": "Spotify",
            # Spotify's public playlist page lists at most 100 songs.
            "label": "First 100 songs" if kind == "playlist" and n >= 100 else f"{n} song{'s' if n != 1 else ''}",
            "qualities": [],
            "lowOnly": False,
            "mp3Label": MP3_LABEL,
        }
    info = fetch_info(youtube_url, browser_setting)
    info.update({
        "url": url,
        "title": track["name"],
        "uploader": ", ".join(track["artists"]),
        "thumbnail": track["cover"] or info["thumbnail"],
        "thumbData": thumbnail_data_url(track["cover"]) or info["thumbData"],
        "duration": fmt_duration(track["duration"]) or info["duration"],
        "site": "Spotify",
        "source": youtube_url,
    })
    return info


def tag_audio(ffmpeg_dir: str, path: str, track: dict):
    """Give an MP3 Spotify's title, artist, album, year, track number and cover art."""
    folder = os.path.dirname(os.path.abspath(path))
    cover = ""
    try:
        data = fetch_image(track["cover"])
        cover = safety.temp_file(folder, ".jpg")
        with open(cover, "wb") as f:
            f.write(data)
    except (OSError, ValueError, KeyError):
        pass
    tmp = safety.temp_file(folder, ".mp3")
    args = [_tool(ffmpeg_dir, "ffmpeg"), "-v", "error", "-y", *LOCAL_ONLY, "-i", os.path.abspath(path)]
    if cover:
        args += [*LOCAL_ONLY, "-i", cover, "-map", "0:a", "-map", "1:v", "-c:v", "copy", "-disposition:v", "attached_pic",
                 "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    else:
        args += ["-map", "0:a"]
    artists = ", ".join(track["artists"])
    args += ["-c:a", "copy", "-map_metadata", "-1", "-id3v2_version", "3",
             "-metadata", f"title={track['name']}", "-metadata", f"artist={artists}"]
    if track.get("album"):
        args += ["-metadata", f"album={track['album']}"]
        if track.get("album_artist"):
            args += ["-metadata", f"album_artist={track['album_artist']}"]
    if track.get("number"):
        number = f"{track['number']}/{track['total']}" if track.get("total") else str(track["number"])
        args += ["-metadata", f"track={number}"]
    if track.get("year"):
        args += ["-metadata", f"date={track['year']}"]
    r = subprocess.run(args + ["-f", "mp3", tmp], capture_output=True, text=True, **RUN_OPTS)
    if r.returncode == 0 and os.path.getsize(tmp):
        os.replace(tmp, path)
    safety.remove_inside(folder, tmp)
    safety.remove_inside(folder, cover)


MAX_ATTEMPTS = 3


def _try_other_format(exc: Exception) -> bool:
    """Could another version of the video work? Yes for a refused or broken version or an
    unknown error; no for a known reason such as a login, the network or a deleted video."""
    msg = friendly_error(exc)
    return msg in (FORBIDDEN, NO_FORMAT, FFMPEG_FAILED) or msg not in {text for _, text in _ERRORS}


def download(url: str, quality: str, folder: str, ffmpeg_dir, *, expected_label: str = "",
             prefer_ready_file: bool = False, progress=None, status=None, title=None,
             cancelled=lambda: False, browser_setting: str = "off") -> dict:
    """Download one link into folder.

    ffmpeg_dir: folder holding ffmpeg/ffprobe, "" to call them by name, or None if
    there is no FFmpeg (fallback: only ready-made MP4 files, nothing to merge).
    browser_setting: whose login to retry with if the site wants one (see with_login_retry).
    Work happens in a private temp folder inside `folder`, removed afterwards whatever
    happens; the result is moved out under a name that never replaces an existing file
    (a folder for posts with several files).
    Returns {"path", "title", "label", "fallback"}. Raises DownloaderError or JobCancelled.
    """
    calls = {"progress": progress or (lambda d: None), "status": status or (lambda s: None),
             "cancelled": cancelled, "browser_setting": browser_setting}
    title = title or (lambda t: None)
    url = _checked(url)
    try:
        folder = safety.real_folder(folder)
    except safety.UnsafeInput as e:
        raise DownloaderError(str(e)) from None

    if spotify.is_spotify(url):
        try:
            kind, _ = spotify.parse(url)
            if kind != "track":
                return _download_spotify_list(url, quality, folder, ffmpeg_dir, title=title, **calls)
            track, source = spotify.resolve(url)
        except spotify.SpotifyError as e:
            raise DownloaderError(str(e)) from None
        title(track["name"])
        return _download_ytdlp(source, quality, folder, ffmpeg_dir, track=track,
                               expected_label=expected_label, prefer_ready_file=prefer_ready_file, **calls)

    url = _resolved(url, browser_setting)
    if links.site(url) in links.GALLERY_SITES or links.is_photo_link(url):
        route = _route(url, browser_setting)
        if route["kind"] == "gallery":
            return _download_gallery(url, route, quality, folder, ffmpeg_dir, title=title, **calls)
        url = route.get("url") or url
    return _download_ytdlp(url, quality, folder, ffmpeg_dir, expected_label=expected_label,
                           prefer_ready_file=prefer_ready_file, **calls)


def _download_ytdlp(source: str, quality: str, folder: str, ffmpeg_dir, *, track=None, name: str = "",
                    expected_label: str = "", prefer_ready_file: bool = False, progress, status,
                    cancelled, browser_setting: str) -> dict:
    """One video or song with yt-dlp, checked, converted for Apple devices, and moved into
    folder. A version that fails is replaced by another, up to MAX_ATTEMPTS times."""
    mp3 = quality == "mp3"

    def check_cancel():
        if cancelled():
            raise JobCancelled()

    def on_progress(d):
        check_cancel()
        progress(d)

    def on_postprocess(d):
        check_cancel()
        if d["status"] == "started":
            status("processing")

    work = tempfile.mkdtemp(prefix=".vd-", dir=folder)  # private: nothing else is in it
    try:
        tried: list[str] = []
        login: dict = {}  # the browser login, once a site has needed it
        plain_best = False  # the preferred formats weren't available: fall back to -f "b"
        attempt = 0
        while True:
            attempt += 1
            _empty(work)
            opts = build_opts(quality, work, source)
            opts["outtmpl"] = os.path.join(work, "download.%(ext)s")
            opts["progress_hooks"] = [on_progress]
            opts["postprocessor_hooks"] = [on_postprocess]
            if ffmpeg_dir:
                opts["ffmpeg_location"] = ffmpeg_dir
            if prefer_ready_file and not mp3:
                # A ready-made file with picture and sound beats merging, at equal quality.
                opts["format_sort"] = [opts["format_sort"][0], "fps", "hasaud", "vcodec:h264", "acodec:m4a"]
            if ffmpeg_dir is None:
                # No FFmpeg: only formats that need no merging or converting.
                opts.pop("postprocessors", None)
                opts.pop("merge_output_format", None)
                # (HEVC tagged "hev1" won't play on Apple devices and can't be re-tagged here.)
                opts["format"] = "ba[ext=m4a]/ba[acodec^=mp4a]" if mp3 else "b[ext=mp4][vcodec!^=hev1]"
            if attempt > 1:
                avoid = "".join(f"[format_id!={f}]" for f in tried)
                if ffmpeg_dir is None:
                    opts["format"] = (f"ba[ext=m4a]{avoid}/ba[acodec^=mp4a]{avoid}" if mp3
                                      else f"b[ext=mp4][vcodec!^=hev1]{avoid}/b[ext=mp4][vcodec!^=hev1]")
                elif attempt == 2:
                    opts["format"] = f"ba{avoid}/b{avoid}/ba/b" if mp3 else ("b" if plain_best else retry_format(tried))
                else:  # last try: whatever the site has
                    opts["format"] = "ba/b" if mp3 else "bv*+ba/b"
                status("downloading")

            def fetch(extra, opts=opts):
                login.update(extra)
                _empty(work)
                with yt_dlp.YoutubeDL({**opts, **login}) as ydl:
                    return ydl.extract_info(source, download=True)

            try:
                info = with_login_retry(fetch, "off" if login else browser_setting,
                                        on_retry=lambda: status("downloading"), url=source)
            except yt_dlp.utils.DownloadCancelled:
                raise
            except yt_dlp.utils.DownloadError as e:
                no_format = "requested format is not available" in str(e).lower()
                if ffmpeg_dir is None and no_format:
                    raise DownloaderError(NEEDS_FFMPEG) from None
                if attempt < MAX_ATTEMPTS and ffmpeg_dir is not None and (no_format or _try_other_format(e)):
                    # This version failed: try a different one rather than giving up.
                    plain_best = plain_best or no_format
                    continue
                raise
            check_cancel()
            if info.get("entries") is not None:
                raise DownloaderError(PLAYLIST_ERROR)
            tried += str(info.get("format_id") or "").split("+")
            downloads = info.get("requested_downloads") or []
            path = downloads[-1].get("filepath") if downloads else ""
            if not path or not safety.is_inside(work, path) or not os.path.isfile(path):
                raise DownloaderError("The download finished but no file was saved. Try again.")

            # Check what actually ended up in the file before calling it done.
            status("processing")
            try:
                if ffmpeg_dir is None:
                    # Nothing to inspect the file with: rely on what the site says it contains.
                    picked = info.get("requested_formats") or [info]
                    if not mp3 and not any(f.get("vcodec") not in (None, "none") for f in picked):
                        raise CheckFailed("picture")
                    if not any(f.get("acodec") not in (None, "none") for f in picked):
                        raise CheckFailed("sound")
                elif mp3:
                    if not any(s["codec_type"] == "audio" for s in probe_streams(ffmpeg_dir, path)):
                        raise CheckFailed("sound")
                else:
                    # Some videos (e.g. GIF-style posts on X) really have no sound.
                    expect_audio = any(f.get("acodec") not in (None, "none")
                                       for f in info.get("formats") or [info])
                    path = make_apple_compatible(ffmpeg_dir, path, expect_audio)
                check_cancel()
                break
            except CheckFailed as e:
                if attempt >= MAX_ATTEMPTS:
                    raise DownloaderError(FAILED_TEXT[e.missing]) from None

        if track and mp3 and ffmpeg_dir is not None:
            tag_audio(ffmpeg_dir, path, {**track, "album": track.get("album") or info.get("album") or ""})
        check_cancel()
        label = file_label(ffmpeg_dir, path, mp3) if ffmpeg_dir is not None else expected_label
        fallback = attempt > 1 and not mp3 and _side(label) < _side(expected_label)
        if fallback:
            label = f"{label} (fallback)"

        # Named after the Spotify song or the video's title, never replacing an existing file.
        if not name:
            if track:
                name = safety.safe_filename(f"{', '.join(track['artists'])} - {track['name']}")
            else:
                name = (f"{safety.safe_filename(info.get('title'), 120, 'video')} "
                        f"[{safety.safe_filename(info.get('id'), 30, 'id')}]")
        final = safety.move_into(folder, path, name, os.path.splitext(path)[1])
        return {"path": final, "title": track["name"] if track else str(info.get("title") or "")[:300],
                "label": label or expected_label, "fallback": fallback}
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- photo posts, carousels and slideshows ----

def _fetch_file(url: str, dest: str, headers: dict, limit: int = 200 * 1024 * 1024):
    """Save one photo from a public web address (checked, also after redirects, size-capped)."""
    url = safety.check_url(url)
    safe_headers = {k: v for k, v in (headers or {}).items() if k.lower() in ("referer", "user-agent")}
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **safe_headers})
    opener = urllib.request.build_opener(links._CheckedRedirects)
    with opener.open(req, timeout=60) as r, open(dest, "wb") as f:
        safety.check_url(r.geturl())
        total = 0
        for chunk in iter(lambda: r.read(1 << 20), b""):
            total += len(chunk)
            if total > limit:
                raise safety.UnsafeInput("The file is too large.")
            f.write(chunk)


def _download_media(media: list, url: str, work: str, ffmpeg_dir, on_files, check_cancel) -> list[str]:
    """Download a post's items as yt-dlp listed them (photos directly, videos with yt-dlp)."""
    paths = []
    for n, item in enumerate(media, 1):
        check_cancel()
        if item["kind"] == "photo":
            ext = os.path.splitext(urllib.parse.urlsplit(item["url"]).path)[1].lower()
            dest = os.path.join(work, f"item{n:03}{ext if ext[1:] in gallery.IMAGE_EXT else '.jpg'}")
            _fetch_file(item["url"], dest, item["headers"])
            paths.append(dest)
        else:
            opts = build_opts("best", work, url)
            opts["outtmpl"] = os.path.join(work, f"item{n:03}.%(ext)s")
            opts["progress_hooks"] = [lambda d: check_cancel()]
            if ffmpeg_dir:
                opts["ffmpeg_location"] = ffmpeg_dir
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.process_ie_result(dict(item["entry"]), download=True)
            downloads = info.get("requested_downloads") or []
            path = downloads[-1].get("filepath") if downloads else ""
            if path and safety.is_inside(work, path) and os.path.isfile(path):
                paths.append(path)
        on_files(len(paths), len(media))
    return paths


def _to_mp3(ffmpeg_dir: str, path: str) -> str:
    """The sound of an audio or video file as an MP3 (320 kbps), or "" if it has none."""
    streams = probe_streams(ffmpeg_dir, path)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    if not audio:
        return ""
    if audio.get("codec_name") == "mp3" and not any(s["codec_type"] == "video" for s in streams):
        return path  # already an MP3: re-encoding can't make it better
    # (The source may itself be named .mp3 while holding AAC, as TikTok's sounds do.)
    folder = os.path.dirname(os.path.abspath(path))
    tmp = safety.temp_file(folder, ".mp3")
    r = subprocess.run([_tool(ffmpeg_dir, "ffmpeg"), "-v", "error", "-y", *LOCAL_ONLY, "-i", os.path.abspath(path),
                        "-map", f"0:{audio['index']}", "-vn", "-map_metadata", "-1", "-c:a", "libmp3lame",
                        "-b:a", f"{MP3_KBPS}k", "-f", "mp3", tmp], capture_output=True, text=True, **RUN_OPTS)
    if r.returncode != 0 or not os.path.getsize(tmp):
        safety.remove_inside(folder, tmp)
        return ""
    out = os.path.splitext(path)[0] + ".mp3"
    os.replace(tmp, out)
    return out


def _download_gallery(url: str, route: dict, quality: str, folder: str, ffmpeg_dir, *, title,
                      progress, status, cancelled, browser_setting: str) -> dict:
    """All photos and videos of a post (and a slideshow's sound as MP3), into a new folder.
    MP3: only the post's sound."""
    mp3 = quality == "mp3"
    if mp3 and not (route["audio"] or route["videos"]):
        raise DownloaderError(NO_SOUND)
    post_title = route["title"] or f"{_SITE_NAMES.get(links.site(url), 'Photo')} post"
    title(post_title)

    def check_cancel():
        if cancelled():
            raise JobCancelled()

    def on_files(done, total):
        check_cancel()
        progress({"status": "downloading", "downloaded_bytes": done, "total_bytes": total})

    work = tempfile.mkdtemp(prefix=".vd-", dir=folder)
    try:
        paths = None
        if route["listing"]:
            items = route["listing"]["items"]
            audio_only = mp3 and route["audio"] and not route["videos"]
            total = sum(i["kind"] == "audio" for i in items) if audio_only else len(items)

            def run(extra):
                _empty(work)
                return gallery.download(url, work, ffmpeg_dir, browser=_browser_of(extra), audio_only=audio_only,
                                        total=total, progress=on_files, cancelled=cancelled)
            try:
                paths = with_login_retry(run, browser_setting, on_retry=lambda: status("downloading"), url=url)
            except InterruptedError:
                raise JobCancelled() from None
            except Exception as e:
                if not route["media"]:
                    if isinstance(e, DownloaderError):
                        raise
                    raise EngineError(friendly_error(e)) from None
        if paths is None:
            _empty(work)
            paths = _download_media(route["media"], url, work, ffmpeg_dir, on_files, check_cancel)

        status("processing")
        files = []  # (path, "photo" | "video" | "audio")
        for path in paths:
            check_cancel()
            ext = os.path.splitext(path)[1].lstrip(".").lower()
            if ext in gallery.AUDIO_EXT or (mp3 and ext in gallery.VIDEO_EXT):
                sound = _to_mp3(ffmpeg_dir, path) if ffmpeg_dir else (path if ext == "mp3" else "")
                if sound:
                    files.append((sound, "audio"))
            elif mp3:
                continue
            elif ext in gallery.VIDEO_EXT:
                try:
                    files.append((make_apple_compatible(ffmpeg_dir, path, False) if ffmpeg_dir else path, "video"))
                except CheckFailed:
                    continue
            elif ext in gallery.IMAGE_EXT:
                files.append((path, "photo"))
        if not files:
            raise DownloaderError(NO_SOUND if mp3 else NO_MEDIA)

        base = (f"{safety.safe_filename(post_title, 100, 'post')} "
                f"[{safety.safe_filename(route['id'] or 'post', 30, 'post')}]")
        photos = sum(kind == "photo" for _, kind in files)
        videos = sum(kind == "video" for _, kind in files)
        if len(files) == 1:
            path = files[0][0]
            final = safety.move_into(folder, path, base, os.path.splitext(path)[1].lower())
        else:
            names, sounds = [], sum(kind == "audio" for _, kind in files)
            for n, (path, kind) in enumerate(files, 1):
                ext = os.path.splitext(path)[1].lower()
                names.append((path, "audio.mp3" if kind == "audio" and sounds == 1 and (photos or videos)
                              else f"{n:02}{ext}"))
            final = safety.move_dir_into(folder, base, names)
        label = (MP3_LABEL if len(files) == 1 else f"{len(files)} MP3s") if mp3 else count_label(photos, videos)
        if not mp3 and any(kind == "audio" for _, kind in files):
            label += " · sound"
        return {"path": final, "title": post_title, "label": label, "fallback": False}
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- Spotify albums and playlists ----

def _download_spotify_list(url: str, quality: str, folder: str, ffmpeg_dir, *, title, progress, status,
                           cancelled, browser_setting: str) -> dict:
    """Every song of a Spotify album or playlist as a tagged MP3, in one new folder.
    Songs that can't be found are skipped; the label says how many were saved."""
    if quality != "mp3":
        raise DownloaderError(SPOTIFY_LIST_MP3)
    try:
        c = spotify.collection(url)
    except spotify.SpotifyError as e:
        raise DownloaderError(str(e)) from None
    tracks, album = c["tracks"], c["kind"] == "album"
    if os.environ.get("DLR_TEST_MAX_SONGS", "").isdigit():  # tests/live_links.py: only the first few
        tracks = tracks[:int(os.environ["DLR_TEST_MAX_SONGS"])]
    n = len(tracks)
    year = c["year"]
    if album and not year:
        try:
            year = spotify.track_info(tracks[0]["id"])["year"]  # album pages don't show the year
        except spotify.SpotifyError:
            pass
    work = tempfile.mkdtemp(prefix=".vd-", dir=folder)
    saved, missed = [], []
    try:
        for i, track in enumerate(tracks):
            if cancelled():
                raise JobCancelled()
            title(f"{c['name']} · {i + 1}/{n}")
            track = {**track, "year": track["year"] or (year if album else ""), "total": n if album else 0,
                     "album_artist": c["owner"] if album else ""}
            if not album:
                try:  # a playlist's songs each have their own cover and year
                    details = spotify.track_info(track["id"])
                    track.update(cover=details["cover"], year=details["year"])
                except spotify.SpotifyError:
                    pass

            def song_progress(d, i=i):
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                part = min(d.get("downloaded_bytes", 0) / total, 1.0) if total else 0.0
                progress({"status": "downloading", "downloaded_bytes": (i + part) * 1000,
                          "total_bytes": n * 1000, "speed": d.get("speed")})
            try:
                source = spotify.match(track)
                number = f"{track['number']:02} " if track.get("number") else ""
                result = _download_ytdlp(
                    source, "mp3", work, ffmpeg_dir, track=track,
                    name=safety.safe_filename(f"{number}{', '.join(track['artists'])} - {track['name']}"),
                    progress=song_progress, status=lambda s: None, cancelled=cancelled,
                    browser_setting=browser_setting)
                saved.append(result["path"])
            except (JobCancelled, yt_dlp.utils.DownloadCancelled):
                raise
            except Exception:
                missed.append(track["name"])
        if not saved:
            raise DownloaderError(f"None of the {n} songs could be found on YouTube Music, so nothing was saved.")
        status("processing")
        base = safety.safe_filename(f"{c['owner']} - {c['name']}" if album and c["owner"] else c["name"], 120, "Spotify")
        final = safety.move_dir_into(folder, base, [(p, os.path.basename(p)) for p in saved])
        label = f"{len(saved)} songs" if not missed else f"{len(saved)} of {n} songs"
        return {"path": final, "title": c["name"], "label": label, "fallback": bool(missed)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


_STALE = re.compile(r"\.vd-[a-z0-9_]{8}(\.(mp4|mp3|jpg))?")


def remove_stale_temp(folder: str) -> int:
    """Delete temp folders/files left in the download folder by an interrupted run.
    Only names this app creates (".vd-" + 8 random characters); never follows symlinks."""
    removed = 0
    try:
        entries = os.listdir(folder)
    except OSError:
        return 0
    for entry in entries:
        path = os.path.join(folder, entry)
        if not _STALE.fullmatch(entry) or os.path.islink(path):
            continue
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            safety.remove_inside(folder, path)
        removed += 1
    return removed


def _empty(folder: str):
    """Remove everything inside our private temp folder (before a retry)."""
    for entry in os.listdir(folder):
        path = os.path.join(folder, entry)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass


@dataclass
class Job:
    id: int
    url: str
    quality: str
    out_dir: str
    title: str = ""
    status: str = "queued"  # queued, downloading, processing, done, error, cancelled
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    error: str = ""
    filepath: str = ""
    label: str = ""  # quality: expected at first, then what was actually saved
    fallback: bool = False  # saved at a lower quality after a retry


class Downloader:
    """A queue that downloads jobs one at a time on a background thread.

    Listeners are called from that thread whenever a job changes.
    """

    def __init__(self, on_update=None, browser_setting=lambda: "off"):
        self._browser_setting = browser_setting  # read for each download, so changes apply at once
        self.jobs: list[Job] = []
        self._lock = threading.Lock()
        self._queue: queue.Queue[Job] = queue.Queue()
        self._ids = itertools.count(1)
        self._listeners = [on_update] if on_update else []
        self._cancelled: set[int] = set()
        threading.Thread(target=self._worker, daemon=True).start()

    def subscribe(self, fn):
        self._listeners.append(fn)

    def add(self, url: str, quality: str, out_dir: str, title: str = "", label: str = "") -> Job:
        if not isinstance(url, str) or not valid_quality(quality):
            raise ValueError("bad download request")
        url, title, label = url.strip(), str(title or "")[:300], str(label or "")[:60]
        if quality == "mp3" and not label:
            label = MP3_LABEL
        job = Job(next(self._ids), url, quality, out_dir, title=title or url, label=label)
        with self._lock:
            self.jobs.append(job)
        self._notify(job)
        self._queue.put(job)
        return job

    def cancel(self, job_id: int) -> bool:
        """Stop a queued or running download; its partial files are deleted."""
        job = self.get(job_id)
        if not job or job.status not in ("queued", "downloading", "processing"):
            return False
        with self._lock:
            self._cancelled.add(job_id)
            if job.status == "queued":
                job.status = "cancelled"
        self._notify(job)
        return True

    def get(self, job_id: int):
        with self._lock:
            return next((j for j in self.jobs if j.id == job_id), None)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [asdict(j) for j in self.jobs]

    def clear_finished(self):
        with self._lock:
            self.jobs = [j for j in self.jobs if j.status not in ("done", "error", "cancelled")]

    def busy(self) -> bool:
        with self._lock:
            return any(j.status in ("queued", "downloading", "processing") for j in self.jobs)

    def _notify(self, job: Job):
        for fn in self._listeners:
            try:
                fn(job)
            except Exception:
                pass

    def _worker(self):
        while True:
            job = self._queue.get()
            if job.status == "cancelled":
                self._cancelled.discard(job.id)
                continue
            try:
                try:
                    self._run(job)
                except (JobCancelled, yt_dlp.utils.DownloadCancelled):
                    raise
                except Exception as e:
                    if not self._retry_after_update(job, e):
                        raise
                job.status = "done"
                job.percent = 100.0
            except (JobCancelled, yt_dlp.utils.DownloadCancelled):
                job.status = "cancelled"  # download() already removed its temp folder
                job.percent = 0.0
                job.speed = job.eta = ""
            except DownloaderError as e:
                job.status = "error"
                job.error = str(e)
            except Exception as e:
                job.status = "error"
                job.error = friendly_error(e)
            self._cancelled.discard(job.id)
            self._notify(job)

    def _callbacks(self, job: Job):
        def progress(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    job.percent = min((d.get("downloaded_bytes") or 0) / total * 100, 100.0)
                job.speed = fmt_speed(d.get("speed"))
                job.eta = fmt_duration(d.get("eta")) or ""
                self._notify(job)

        def status(new_status):
            if new_status == "downloading":
                job.percent = 0.0  # a retry starts over
            job.status = new_status
            job.speed = job.eta = ""
            self._notify(job)

        def title(new_title):
            job.title = str(new_title)[:300]

        return progress, status, title

    def _run(self, job: Job):
        # Without FFmpeg, yt-dlp can silently save video-only or unplayable files.
        ffmpeg_dir = find_ffmpeg()
        if not ffmpeg_dir:
            raise DownloaderError(FFMPEG_MISSING)
        job.status = "downloading"
        self._notify(job)
        progress, status, title = self._callbacks(job)
        result = download(job.url, job.quality, job.out_dir, ffmpeg_dir, expected_label=job.label,
                          progress=progress, status=status, title=title,
                          cancelled=lambda: job.id in self._cancelled,
                          browser_setting=self._browser_setting())
        job.filepath, job.label, job.fallback = result["path"], result["label"], result["fallback"]

    def _retry_after_update(self, job: Job, error: Exception) -> bool:
        """After a failed download: update yt-dlp and gallery-dl, as sites change often and a
        new version usually fixes it. If a newer one is now installed, download once more
        with it, in a fresh copy of Dlr (this one keeps the yt-dlp it started with).
        Returns False if there was nothing new to retry with."""
        message = str(error) if isinstance(error, DownloaderError) else friendly_error(error)
        if isinstance(error, DownloaderError) and not isinstance(error, EngineError):
            return False  # Dlr's own checks: a new yt-dlp won't change them
        if message in _NO_UPDATE or is_login_message(message):
            return False
        if not update_engines():
            return False
        job.status = "downloading"
        job.percent = 0.0
        self._notify(job)
        progress, status, title = self._callbacks(job)
        result = run_job_in_child(
            {"url": job.url, "quality": job.quality, "folder": job.out_dir, "label": job.label,
             "browser": self._browser_setting()},
            progress=progress, status=status, title=title, cancelled=lambda: job.id in self._cancelled)
        job.filepath, job.label, job.fallback = result["path"], result["label"], result["fallback"]
        return True


# Failures a newer yt-dlp or gallery-dl can't fix.
_NO_UPDATE = {NETWORK_ERROR, DRM_ERROR, LOGIN_ERROR, STORIES_LOGIN, RATE_LIMITED, NO_SOUND, SPOTIFY_LIST_MP3,
              FFMPEG_MISSING, PLAYLIST_ERROR}


# ---- a download in a fresh copy of Dlr (after an update) ----

def _child_env() -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    return env


def run_job_in_child(request: dict, *, progress, status, title, cancelled) -> dict:
    """Run one download in a new Dlr process (Dlr --job), which loads the newest yt-dlp and
    gallery-dl. The request goes in as JSON on stdin; progress comes back as JSON lines.
    Raises DownloaderError or JobCancelled."""
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    proc = subprocess.Popen([*gallery.self_command(), "--job"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=_child_env(), **extra)
    proc.stdin.write(json.dumps(request).encode("utf-8"))
    proc.stdin.close()
    lines: queue.Queue = queue.Queue()

    def read():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    outcome = None
    try:
        while True:
            if cancelled():
                proc.terminate()  # the child cleans up its temp folder on the way out
                proc.wait(timeout=30)
                raise JobCancelled()
            try:
                line = lines.get(timeout=0.3)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("event") if isinstance(event, dict) else None
            if kind == "progress":
                progress(event)
            elif kind == "status" and event.get("status") in ("downloading", "processing"):
                status(event["status"])
            elif kind == "title":
                title(str(event.get("title") or ""))
            elif kind in ("done", "error", "cancelled"):
                outcome = event
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    if not outcome or outcome["event"] == "error":
        raise DownloaderError(str((outcome or {}).get("message") or "Something went wrong.")[:500])
    if outcome["event"] == "cancelled":
        raise JobCancelled()
    result = outcome.get("result") or {}
    if not isinstance(result.get("path"), str) or not os.path.exists(result["path"]):
        raise DownloaderError("The download finished but no file was saved. Try again.")
    return {"path": result["path"], "title": str(result.get("title") or "")[:300],
            "label": str(result.get("label") or "")[:60], "fallback": bool(result.get("fallback"))}


def job_child(stdin=None, stdout=None) -> int:
    """Dlr --job: one download, as asked by run_job_in_child. Stops cleanly on SIGTERM."""
    import signal

    import config
    # (A windowed app may start without sys.stdin/stdout: use the pipes directly.)
    stdin = stdin or (sys.stdin.buffer if sys.stdin else open(0, "rb", closefd=False))
    stdout = stdout or sys.stdout or open(1, "w", encoding="utf-8", closefd=False)

    def emit(**event):
        stdout.write(json.dumps(event) + "\n")
        stdout.flush()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        request = json.loads(stdin.read(64 * 1024))
        url, quality, folder = request["url"], str(request["quality"]), request["folder"]
        browser = request.get("browser") if request.get("browser") in config.BROWSERS else "off"
        if not isinstance(url, str) or not isinstance(folder, str) or not valid_quality(quality):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        emit(event="error", message="That request isn't valid.")
        return 2
    keys = ("status", "downloaded_bytes", "total_bytes", "total_bytes_estimate", "speed", "eta")
    try:
        ffmpeg_dir = find_ffmpeg()
        if not ffmpeg_dir:
            raise DownloaderError(FFMPEG_MISSING)
        result = download(url, quality, folder, ffmpeg_dir, expected_label=str(request.get("label") or "")[:60],
                          progress=lambda d: emit(event="progress", **{k: d.get(k) for k in keys}),
                          status=lambda s: emit(event="status", status=s),
                          title=lambda t: emit(event="title", title=t),
                          cancelled=stop.is_set, browser_setting=browser)
    except (JobCancelled, yt_dlp.utils.DownloadCancelled):
        emit(event="cancelled")
        return 1
    except DownloaderError as e:
        emit(event="error", message=str(e))
        return 1
    except Exception as e:
        emit(event="error", message=friendly_error(e))
        return 1
    emit(event="done", result=result)
    return 0


# ---- yt-dlp and gallery-dl versions and updates ----

def ytdlp_version() -> str:
    return yt_dlp.version.__version__


def install_method() -> str:
    """How the yt-dlp in use was installed, which decides how to update it:
    "app" (inside Dlr.app: verified download of the official release file), "brew" or "pip"."""
    if getattr(sys, "frozen", False):
        return "app"
    location = os.path.realpath(yt_dlp.__file__)
    if "/Cellar/" in location or location.startswith(("/opt/homebrew/", "/usr/local/Homebrew/")):
        return "brew"
    return "pip"


def update_ytdlp() -> tuple[bool, str]:
    """Update yt-dlp the way it was installed. Returns (changed, message).
    A new version is used from the next launch. Commands are argument lists, never a shell."""
    method = install_method()
    if method == "app":
        return updater.install_latest()
    before = updater.current_version()
    if method == "brew":
        brew = next(filter(None, (shutil.which("brew", path=d) for d in [None, *_FFMPEG_DIRS])), "")
        if not brew:
            return False, f"Couldn't find Homebrew. Keeping {before}."
        r = subprocess.run([brew, "upgrade", "yt-dlp"], capture_output=True, text=True, timeout=600)
        check = [os.path.join(os.path.dirname(brew), "yt-dlp"), "--version"]
    else:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "--no-cache-dir",
                            "--disable-pip-version-check", "yt-dlp"],
                           capture_output=True, text=True, timeout=600)
        check = [sys.executable, "-c", "import yt_dlp; print(yt_dlp.version.__version__)"]
    if r.returncode != 0:
        return False, f"Couldn't update right now. Keeping {before}."
    after = subprocess.run(check, capture_output=True, text=True, timeout=60).stdout.strip() or before
    if not updater.newer(after, before):
        return False, f"Up to date ({before})"
    updater.active["pending"] = after
    return True, f"Updated to {after}. Restart Dlr to use it."


def update_gallery_dl() -> tuple[bool, str]:
    """Update gallery-dl in the packaged app (used at once: it runs in its own process).
    Running from source, pip manages it."""
    if not getattr(sys, "frozen", False):
        return False, f"Up to date ({updater.gallery_dl_version()})"
    return updater.install_latest_gallery_dl()


def update_all() -> tuple[bool, str]:
    """The Update button: yt-dlp and gallery-dl. Returns (changed, message)."""
    ytdlp_changed, ytdlp_message = update_ytdlp()
    gdl_changed, gdl_message = update_gallery_dl()
    return ytdlp_changed or gdl_changed, f"yt-dlp: {ytdlp_message} gallery-dl: {gdl_message}"


def update_engines() -> bool:
    """After a failed download: update yt-dlp and gallery-dl (at most once an hour). True if
    a newer version than the one this process uses is installed, so a retry may help."""
    gdl_changed = False
    if updater.due("last_failure_update", 3600):
        updater.mark("last_failure_update")
        for update in (update_ytdlp, update_gallery_dl):
            try:
                changed, _ = update()
                gdl_changed = gdl_changed or (changed and update is update_gallery_dl)
            except Exception:
                pass
    return gdl_changed or updater.newer(updater.active["pending"], updater.active["version"])


def auto_update():
    """At launch: update yt-dlp and gallery-dl on their own, at most once a day."""
    if updater.due("last_auto_update", updater.CHECK_EVERY):
        updater.mark("last_auto_update")
        for update in (update_ytdlp, update_gallery_dl):
            try:
                update()
            except Exception:
                pass
    updater.check_latest()


def with_update_note(error: str) -> str:
    """After a failed lookup, update yt-dlp and gallery-dl (at most once an hour). Returns the
    error, plus a note if a new yt-dlp arrived (this window keeps the one it started with)."""
    if error in _NO_UPDATE or is_login_message(error):
        return error
    update_engines()
    if updater.newer(updater.active["pending"], updater.active["version"]):
        return f"{error} Dlr just updated yt-dlp to {updater.active['pending']}: restart Dlr and try again."
    return error
