"""yt-dlp logic: fetching video info, the download queue, and friendly errors."""
import base64
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
import urllib.request
from dataclasses import asdict, dataclass

import yt_dlp
import yt_dlp.globals

import safety
import spotify

# Never load yt-dlp plugins: they are Python code picked up from folders in the user's
# home (and next to the app) and would run inside this app. Same as --no-plugin-dirs.
yt_dlp.globals.plugin_dirs.value = []
# If Deno is installed, yt-dlp runs it (sandboxed) for YouTube; stop it phoning home for updates.
os.environ["DENO_NO_UPDATE_CHECK"] = "1"

QUALITIES = {
    "best": "Best video",
    "1080": "1080p",
    "720": "720p",
    "mp3": "Audio only (MP3)",
}


class DownloaderError(Exception):
    """An error with a message that is safe to show to the user."""


class JobCancelled(yt_dlp.utils.DownloadCancelled):
    """The user stopped the download (yt-dlp lets this pass straight through)."""

    msg = "The download was cancelled."


# Apps launched from Finder don't get Homebrew's PATH, so check the usual places too.
_FFMPEG_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]

NEEDS_FFMPEG = ("This site only sends picture and sound separately, and combining them needs "
                "FFmpeg. In a-Shell, run: pkg install ffmpeg")
FFMPEG_MISSING = ("FFmpeg isn't installed, so nothing was downloaded. Install it "
                  "(Mac: brew install ffmpeg, Windows: winget install Gyan.FFmpeg) and try again.")


def find_ffmpeg():
    """Folder that holds both ffmpeg and ffprobe, or None."""
    for d in [None, *_FFMPEG_DIRS]:
        ffmpeg = shutil.which("ffmpeg", path=d)
        if ffmpeg and shutil.which("ffprobe", path=os.path.dirname(ffmpeg)):
            return os.path.dirname(ffmpeg)
    return None


def find_deno():
    """Path to Deno, or None. yt-dlp needs it to solve YouTube's puzzles (full quality, fewer errors)."""
    for d in [None, *_FFMPEG_DIRS, os.path.expanduser("~/.deno/bin")]:
        deno = shutil.which("deno", path=d)
        if deno:
            return deno
    return None


def _install_command(package: str) -> str:
    if sys.platform == "win32":
        return {"ffmpeg": "winget install Gyan.FFmpeg", "deno": "winget install DenoLand.Deno"}[package]
    return f"brew install {package}"


def missing_tools() -> list[dict]:
    """Tools Dlr needs that aren't installed, each with the command that installs it.
    (yt-dlp itself is inside the app, or checked by app.py when running from source.)"""
    missing = []
    if not find_ffmpeg():
        missing.append({"name": "FFmpeg", "why": "needed to combine picture and sound",
                        "command": _install_command("ffmpeg")})
    if not find_deno():
        missing.append({"name": "Deno", "why": "needed for YouTube: full quality and fewer errors",
                        "command": _install_command("deno")})
    if missing and sys.platform == "darwin" and not any(
            shutil.which("brew", path=d) for d in [None, *_FFMPEG_DIRS]):
        for tool in missing:
            tool["why"] += "; install Homebrew first from brew.sh"
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
        capture_output=True, text=True, timeout=120)
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
        capture_output=True, text=True, timeout=600)
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
        r = subprocess.run(base + video_args + tail + [tmp], capture_output=True, text=True)
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
    "picture": "Failed: no picture. Two different versions of this video were tried and neither "
               "had a picture, so nothing was saved.",
    "sound": "Failed: no sound. Two different versions of this video were tried and neither "
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


# (pattern in yt-dlp's message, what to tell the user). First match wins.
NETWORK_ERROR = "Network error. Check your internet connection and try again."
DRM_ERROR = "This video is copy-protected, so it can't be downloaded."

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
     "YouTube wants to confirm you're not a bot. Log in to YouTube in your browser, then try again."),
    (r"age[- ]restricted|confirm your age|inappropriate for some users",
     "This video is age-restricted. Log in to the site in your browser, then try again."),
    (r"too many requests|http error 429|rate[- ]limit",
     "This site is limiting downloads right now. Wait a few minutes and try again."),
    (r"login required|log in|sign in|logged[- ]in|requires authentication|account authentication|use --cookies",
     "This site needs you to be logged in. Log in to it in your browser, then try again."),
    (r"available in your country|geo[- ]?restrict|from your location",
     "This video isn't available in your country."),
    (r"unsupported url|no video could be found|is not a valid url",
     "This site or link isn't supported. Make sure it's a direct link to a single video."),
    (r"requested format is not available",
     "No version of this video can be saved this way. Try the other button, or another link."),
    (r"video unavailable|is unavailable|not available|has been removed|does not exist|http error 404|this post is unavailable",
     "This video is unavailable. It may have been deleted."),
    (r"javascript runtime|js runtime|\bdeno\b|n challenge|signature solving",
     "YouTube needs Deno to download this. Install it in Terminal with: brew install deno"),
    (r"http error 403|forbidden",
     "The site refused the download. Try again in a few minutes."),
    (r"unable to download webpage|getaddrinfo|timed out|connection|network is unreachable|nodename nor servname",
     NETWORK_ERROR),
    (r"ffmpeg|ffprobe",
     "FFmpeg is missing or failed. Install it in Terminal with: brew install ffmpeg"),
]

# Errors a logged-in browser can fix: retried once with the browser's login.
_NEEDS_LOGIN = re.compile(r"not a bot|log ?in|sign in|logged[- ]in|requires authentication|account authentication"
                          r"|use --cookies|too many requests|http error 429|rate[- ]limit|private|age[- ]restricted"
                          r"|confirm your age", re.I)


def needs_login(exc: Exception) -> bool:
    return bool(_NEEDS_LOGIN.search(str(exc)))


def friendly_error(exc: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    msg = re.sub(r"^ERROR:\s*", "", msg).strip()
    msg = re.sub(r"^\[[\w:]+\] [^:]*: ", "", msg)  # drop "[youtube] abc123: "
    low = msg.lower()
    for pattern, text in _ERRORS:
        if re.search(pattern, low):
            return text
    return msg or "Something went wrong."


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _base_opts() -> dict:
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
        # Apps opened from Finder don't get Homebrew's PATH, so tell yt-dlp where Deno is.
        opts["js_runtimes"] = {"deno": {"path": deno}}
    return opts


def build_opts(quality: str, out_dir: str) -> dict:
    opts = _base_opts()
    opts["outtmpl"] = os.path.join(out_dir, "%(title).150B [%(id)s].%(ext)s")
    if quality == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "0",  # best variable bitrate, like --audio-quality 0
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
    formats = ctx["formats"]  # already sorted, worst to best
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


def retry_format(tried: list[str]) -> str:
    """Format for the second attempt: the H.264 + AAC version, avoiding what was tried."""
    avoid = "".join(f"[format_id!={f}]" for f in tried)
    h264, aac = "[vcodec~='^(avc|h264)']", "[acodec~='^(mp4a|aac)']"
    return "/".join([
        f"bv*{h264}{avoid}+ba{aac}", f"b{h264}{aac}{avoid}",  # a different H.264 + AAC version
        f"bv*{avoid}+ba[acodec!=mp3]", f"b{avoid}",            # any different version
        f"bv*{h264}+ba{aac}", f"b{h264}{aac}", "bv*+ba/b",      # same as before, downloaded again
    ])


MP3_LABEL = "MP3 · best quality"


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
    """yt-dlp couldn't get the video (the message is already plain English)."""


def with_login_retry(run, browser_setting: str, on_retry=lambda: None):
    """Call run(opts_extra); if the site wants a login, call it once more with the
    browser's login. yt-dlp reads the cookies straight from the browser each time and
    keeps them in memory only: Dlr never copies or saves them."""
    try:
        return run({})
    except yt_dlp.utils.DownloadCancelled:
        raise
    except Exception as e:
        browser = login_browser(browser_setting)
        if not needs_login(e) or not browser:
            raise
        first = e
    on_retry()
    try:
        return run({"cookiesfrombrowser": (browser,)})
    except yt_dlp.utils.DownloadCancelled:
        raise
    except Exception as e:
        if needs_login(e) and friendly_error(e) == friendly_error(first):
            name = BROWSER_NAMES[browser]
            raise EngineError(f"{friendly_error(e)} (Dlr tried your {name} login: make sure you're "
                              f"logged in to this site in {name}.)") from None
        raise


def fetch_info(url: str, browser_setting: str = "off") -> dict:
    """Look up a video without downloading. Raises DownloaderError."""
    try:
        url = safety.check_url(url)
    except safety.UnsafeInput as e:
        raise DownloaderError(str(e)) from None
    protected = drm_site(url)
    if protected:
        raise DownloaderError(f"{protected} is copy-protected, so it can't be downloaded.")
    if spotify.is_spotify(url):
        return _fetch_spotify(url, browser_setting)

    def lookup(extra):
        # Same format rules as the download, so we know what quality it will get.
        with yt_dlp.YoutubeDL({**build_opts("best", "."), **extra}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = with_login_retry(lookup, browser_setting)
    except DownloaderError:
        raise
    except Exception as e:
        raise EngineError(friendly_error(e)) from None
    if info.get("_type") == "playlist" or info.get("entries") is not None:
        raise DownloaderError("That's a playlist or profile. Paste a link to a single video.")
    chosen = next((f for f in info.get("requested_formats") or [] if f.get("vcodec") != "none"), info)
    # yt-dlp copies an MP3 source as is, so its bitrate is what gets saved.
    audio = [f for f in info.get("formats") or [] if f.get("vcodec") == "none" and f.get("acodec") not in ("none", None)]
    mp3_label = MP3_LABEL
    if audio and audio[-1].get("acodec") == "mp3":
        kbps = audio[-1].get("abr") or audio[-1].get("tbr")
        mp3_label = f"MP3 · {round(kbps)} kbps" if kbps else "MP3"

    # Resolution as the shorter side, so a 720x1280 TikTok counts as 720p.
    heights = sorted({
        min(f["height"], f.get("width") or f["height"]) for f in info.get("formats") or []
        if f.get("height") and f.get("vcodec") != "none"
    }, reverse=True)
    if heights:
        options = ["best"] + [q for q in ("1080", "720") if heights[0] >= int(q)] + ["mp3"]
    else:
        options = list(QUALITIES)
    return {
        "url": url,
        "title": info.get("title") or url,
        "thumbnail": info.get("thumbnail") or "",
        "thumbData": thumbnail_data_url(info.get("thumbnail")),
        "duration": fmt_duration(info.get("duration")),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "site": info.get("extractor_key") or "",
        "heights": heights,
        "options": options,
        "label": video_label(chosen.get("width"), chosen.get("height"), chosen.get("fps")),
        **quality_options(info.get("formats") or []),
        "mp3Label": mp3_label,
    }


def quality_options(formats: list) -> dict:
    """The video qualities on offer, highest first, one per resolution, none below 480p.

    If nothing reaches 480p, only the best available one is listed and "lowOnly" is set.
    """
    best_fps: dict[int, float] = {}
    for f in formats:
        if f.get("vcodec") == "none" or not f.get("height"):
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
    """Spotify song: show Spotify's info, with the matching YouTube upload's qualities."""
    try:
        track, youtube_url = spotify.resolve(url)
    except spotify.SpotifyError as e:
        raise DownloaderError(str(e)) from None
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
    """Give an MP3 Spotify's title, artist, year and cover art."""
    folder = os.path.dirname(os.path.abspath(path))
    cover = ""
    try:
        data = fetch_image(track["cover"])
        cover = safety.temp_file(folder, ".jpg")
        with open(cover, "wb") as f:
            f.write(data)
    except (OSError, ValueError):
        pass
    tmp = safety.temp_file(folder, ".mp3")
    args = [_tool(ffmpeg_dir, "ffmpeg"), "-v", "error", "-y", *LOCAL_ONLY, "-i", os.path.abspath(path)]
    if cover:
        args += [*LOCAL_ONLY, "-i", cover, "-map", "0:a", "-map", "1:v", "-c:v", "copy", "-disposition:v", "attached_pic",
                 "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    else:
        args += ["-map", "0:a"]
    args += ["-c:a", "copy", "-map_metadata", "-1", "-id3v2_version", "3",
             "-metadata", f"title={track['name']}", "-metadata", f"artist={', '.join(track['artists'])}"]
    if track.get("year"):
        args += ["-metadata", f"date={track['year']}"]
    r = subprocess.run(args + ["-f", "mp3", tmp], capture_output=True, text=True)
    if r.returncode == 0 and os.path.getsize(tmp):
        os.replace(tmp, path)
    safety.remove_inside(folder, tmp)
    safety.remove_inside(folder, cover)


def download(url: str, quality: str, folder: str, ffmpeg_dir, *, expected_label: str = "",
             prefer_ready_file: bool = False, progress=None, status=None, title=None,
             cancelled=lambda: False, browser_setting: str = "off") -> dict:
    """Download one link into folder.

    ffmpeg_dir: folder holding ffmpeg/ffprobe, "" to call them by name, or None if
    there is no FFmpeg (fallback: only ready-made MP4 files, nothing to merge).
    browser_setting: whose login to retry with if the site wants one (see with_login_retry).
    Work happens in a private temp folder inside `folder`, removed afterwards whatever
    happens; the result is moved out under a name that never replaces an existing file.
    Returns {"path", "title", "label", "fallback"}. Raises DownloaderError or JobCancelled.
    """
    progress, status, title = progress or (lambda d: None), status or (lambda s: None), title or (lambda t: None)
    try:
        url = safety.check_url(url)
        folder = safety.real_folder(folder)
    except safety.UnsafeInput as e:
        raise DownloaderError(str(e)) from None
    protected = drm_site(url)
    if protected:
        raise DownloaderError(f"{protected} is copy-protected, so it can't be downloaded.")
    mp3 = quality == "mp3"
    source, track = url, None
    if spotify.is_spotify(url):
        try:
            track, source = spotify.resolve(url)
        except spotify.SpotifyError as e:
            raise DownloaderError(str(e)) from None
        title(track["name"])

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
        for attempt in (1, 2):
            _empty(work)
            opts = build_opts(quality, work)
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
            if attempt == 2:
                avoid = "".join(f"[format_id!={f}]" for f in tried)
                if ffmpeg_dir is None:
                    opts["format"] = (f"ba[ext=m4a]{avoid}/ba[acodec^=mp4a]{avoid}" if mp3
                                      else f"b[ext=mp4][vcodec!^=hev1]{avoid}/b[ext=mp4][vcodec!^=hev1]")
                else:
                    opts["format"] = f"ba{avoid}/b{avoid}/ba/b" if mp3 else retry_format(tried)
                if plain_best and not mp3:
                    opts["format"] = "b"
            if attempt == 2:
                status("downloading")

            def fetch(extra, opts=opts):
                login.update(extra)
                _empty(work)
                with yt_dlp.YoutubeDL({**opts, **login}) as ydl:
                    return ydl.extract_info(source, download=True)

            try:
                info = with_login_retry(fetch, "off" if login else browser_setting,
                                        on_retry=lambda: status("downloading"))
            except yt_dlp.utils.DownloadError as e:
                no_format = "requested format is not available" in str(e).lower()
                if ffmpeg_dir is None and no_format:
                    raise DownloaderError(NEEDS_FFMPEG) from None
                if no_format and attempt == 1 and ffmpeg_dir is not None:
                    plain_best = True
                    continue
                raise
            check_cancel()
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
                if attempt == 2:
                    raise DownloaderError(FAILED_TEXT[e.missing]) from None

        if track and mp3 and ffmpeg_dir is not None:
            tag_audio(ffmpeg_dir, path, track)
        check_cancel()
        label = file_label(ffmpeg_dir, path, mp3) if ffmpeg_dir is not None else expected_label
        fallback = attempt == 2 and not mp3 and _side(label) < _side(expected_label)
        if fallback:
            label = f"{label} (fallback)"

        # Named after the Spotify song or the video's title, never replacing an existing file.
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
                self._run(job)
                job.status = "done"
                job.percent = 100.0
            except (JobCancelled, yt_dlp.utils.DownloadCancelled):
                job.status = "cancelled"  # download() already removed its temp folder
                job.percent = 0.0
                job.speed = job.eta = ""
            except EngineError as e:
                job.status = "error"
                job.error = with_update_note(str(e))
            except DownloaderError as e:
                job.status = "error"
                job.error = str(e)
            except Exception as e:
                job.status = "error"
                job.error = with_update_note(friendly_error(e))
            self._cancelled.discard(job.id)
            self._notify(job)

    def _run(self, job: Job):
        # Without FFmpeg, yt-dlp can silently save video-only or unplayable files.
        ffmpeg_dir = find_ffmpeg()
        if not ffmpeg_dir:
            raise DownloaderError(FFMPEG_MISSING)
        job.status = "downloading"
        self._notify(job)

        def progress(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    job.percent = min(d.get("downloaded_bytes", 0) / total * 100, 100.0)
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
            job.title = new_title[:300]

        result = download(job.url, job.quality, job.out_dir, ffmpeg_dir, expected_label=job.label,
                          progress=progress, status=status, title=title,
                          cancelled=lambda: job.id in self._cancelled,
                          browser_setting=self._browser_setting())
        job.filepath, job.label, job.fallback = result["path"], result["label"], result["fallback"]


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
    import updater
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


def auto_update():
    """At launch: update yt-dlp on its own, at most once a day."""
    import updater
    if updater.due("last_auto_update", updater.CHECK_EVERY):
        updater.mark("last_auto_update")
        try:
            update_ytdlp()
        except Exception:
            pass
    updater.check_latest()


def with_update_note(error: str) -> str:
    """After a failed download, update yt-dlp (at most once an hour), as sites change often
    and a new yt-dlp usually fixes it. Returns the error, plus a note if an update arrived."""
    import updater
    if error in (NETWORK_ERROR, DRM_ERROR) or not updater.due("last_failure_update", 3600):
        return error
    updater.mark("last_failure_update")
    try:
        changed, _ = update_ytdlp()
    except Exception:
        changed = False
    if changed:
        return f"{error} Dlr just updated yt-dlp to {updater.active['pending']}: restart Dlr and try again."
    return error
