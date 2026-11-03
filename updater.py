"""yt-dlp and gallery-dl updates for the packaged app (Dlr.app has both sealed inside).

- Downloads only from the official GitHub releases (github.com/yt-dlp/yt-dlp), over HTTPS,
  following redirects only to GitHub's own download servers.
- Checks the file against the release's official SHA2-256SUMS and the version written inside
  it. On any mismatch the download is thrown away and the current version stays.
- Keeps the update in ~/Library/Application Support/Dlr/yt-dlp/. At launch, activate() uses it
  only if it's newer than the built-in yt-dlp, still matches its recorded checksum, and loads
  cleanly; otherwise the built-in version is used (and a broken update is removed).
- Dlr installs a new release on its own: at most once a day at launch, and again (at most once
  an hour) when a download fails, since a failure often means the site changed. It's used from
  the next launch. The Update button does the same at any time.

gallery-dl (used for photo posts) is updated the same way, from its official releases on PyPI
(pypi.org lists the SHA-256 of every release file), into ~/Library/Application Support/Dlr/
gallery-dl/. It always runs in a separate process (see gallery.py), which calls
activate_gallery_dl() first, so a new version is used at once.

activate() must run before anything imports yt_dlp.
"""
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

RELEASES = "https://github.com/yt-dlp/yt-dlp/releases"
ASSET = "yt-dlp"  # the platform-independent Python zip app
MAX_ASSET = 60 * 1024 * 1024
CHECK_EVERY = 24 * 3600
_TAG = re.compile(r"\d{4}\.\d{2}\.\d{2}(\.\d+)?")


def app_dir() -> Path:
    base = Path.home() / "Library" / "Application Support"
    return base / "Dlr"


UPDATE_DIR = app_dir() / "yt-dlp"
ZIP, MANIFEST, STATE = UPDATE_DIR / "yt-dlp.zip", UPDATE_DIR / "manifest.json", UPDATE_DIR / "state.json"

# What is in use; filled in by activate(). "pending": a newer version installed since launch.
active = {"source": "built-in", "version": "", "note": "", "pending": ""}


class UpdateError(Exception):
    """A plain-language reason the update didn't happen."""


def vtuple(version: str) -> tuple:
    return tuple(int(x) for x in version.split(".")) if version and _TAG.fullmatch(version) else ()


def newer(a: str, b: str) -> bool:
    return vtuple(a) > vtuple(b)


def builtin_version() -> str:
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _forget_loaded_ytdlp():
    for name in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
        del sys.modules[name]


def activate() -> dict:
    """Use the downloaded yt-dlp if it's newer and healthy, else the built-in one."""
    active.update(source="built-in", version=builtin_version(), note="")
    if not getattr(sys, "frozen", False):
        return active  # running from source: pip manages yt-dlp
    try:
        if UPDATE_DIR.is_symlink() or ZIP.is_symlink():
            raise ValueError("unexpected link")
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        version = manifest["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return active  # no update installed
    if not newer(version, active["version"]):
        return active
    if _sha256(ZIP) != manifest.get("sha256"):
        _discard("The saved yt-dlp update was damaged, so the built-in version is used.")
        return active
    sys.path.insert(0, str(ZIP))
    try:
        import yt_dlp
        import yt_dlp.globals
        import yt_dlp.version
        yt_dlp.globals.plugin_dirs.value = []  # never load plugins
        if yt_dlp.version.__version__ != version:
            raise ImportError("version mismatch")
        yt_dlp.YoutubeDL({"quiet": True, "logger": None, "cachedir": False}).close()
        active.update(source="updated", version=version)
    except Exception:
        sys.path.remove(str(ZIP))
        _forget_loaded_ytdlp()
        _discard(f"yt-dlp {version} didn't load, so the built-in version is used.")
    return active


def _discard(note: str):
    active["note"] = note
    for path in (ZIP, MANIFEST):
        try:
            path.unlink()
        except OSError:
            pass


# ---- network: GitHub (yt-dlp) or PyPI (gallery-dl) only ----

def _allowed(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == "github.com" or host.endswith(".githubusercontent.com"))


def _allowed_pypi(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").lower() in ("pypi.org", "files.pythonhosted.org")


class _Restricted(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed, site: str):
        self.allowed, self.site = allowed, site

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.allowed(newurl):
            raise UpdateError(f"The download was sent somewhere other than {self.site}, so it was stopped.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, limit: int, method: str = "GET", allowed=_allowed, site: str = "GitHub"):
    if not allowed(url):
        raise UpdateError(f"Only {site} is allowed for updates.")
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "Dlr-updater"})
    try:
        with urllib.request.build_opener(_Restricted(allowed, site)).open(req, timeout=30) as r:
            if not allowed(r.geturl()):
                raise UpdateError(f"The download was sent somewhere other than {site}, so it was stopped.")
            data = r.read(limit + 1) if method == "GET" else b""
            if len(data) > limit:
                raise UpdateError("The download was larger than expected, so it was stopped.")
            return r.geturl(), data
    except OSError:  # includes URLError
        raise UpdateError(f"Couldn't reach {site}. Check your internet connection.") from None


def latest_version() -> str:
    final, _ = _get(f"{RELEASES}/latest", 0, method="HEAD")
    tag = final.rstrip("/").rsplit("/", 1)[-1]
    if not _TAG.fullmatch(tag):
        raise UpdateError("Couldn't read the latest version from GitHub.")
    return tag


def _read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def due(key: str, every: float) -> bool:
    """True if the action recorded under key last ran more than `every` seconds ago."""
    return time.time() - _read_state().get(key, 0) >= every


def mark(key: str):
    """Record that the action under key ran now (only a time is kept, nothing else)."""
    try:
        _write_atomic(STATE, json.dumps({**_read_state(), key: time.time()}).encode())
    except OSError:
        pass


def _write_atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def check_latest(force: bool = False) -> str:
    """Latest release, looked up at most once a day (cached in state.json). "" if unknown."""
    state = _read_state()
    if not force and time.time() - state.get("last_check", 0) < CHECK_EVERY:
        return state.get("latest", "")
    try:
        latest = latest_version()
    except UpdateError:
        return state.get("latest", "")
    _write_atomic(STATE, json.dumps({**state, "last_check": time.time(), "latest": latest}).encode())
    return latest


def update_available() -> str:
    latest = _read_state().get("latest", "")
    return latest if newer(latest, current_version()) else ""


def current_version() -> str:
    """The newest yt-dlp on this computer: in use, or installed and waiting for a restart."""
    in_use = active["version"] or builtin_version()
    return active["pending"] if newer(active["pending"], in_use) else in_use


def verify(data: bytes, sums: str, tag: str) -> str:
    """Check a downloaded yt-dlp against the release's SHA2-256SUMS and its own version.
    Returns the SHA-256; raises UpdateError on any mismatch."""
    expected = None
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == ASSET:
            expected = parts[0].lower()
    if not expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise UpdateError("The official checksum list didn't include yt-dlp, so nothing was installed.")
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise UpdateError("The download didn't match the official checksum, so it was rejected.")
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            text = z.read("yt_dlp/version.py").decode("utf-8")
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
        raise UpdateError("The download isn't a valid yt-dlp file, so it was rejected.") from None
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not m or m.group(1) != tag:
        raise UpdateError("The downloaded yt-dlp has the wrong version inside, so it was rejected.")
    return digest


def install_latest() -> tuple[bool, str]:
    """Download, verify and save the newest yt-dlp. Returns (changed, message)."""
    current = current_version()
    try:
        tag = latest_version()
        _write_atomic(STATE, json.dumps({**_read_state(), "last_check": time.time(), "latest": tag}).encode())
        if not newer(tag, current):
            return False, f"Up to date ({current})"
        _, sums = _get(f"{RELEASES}/download/{tag}/SHA2-256SUMS", 64 * 1024)
        _, data = _get(f"{RELEASES}/download/{tag}/{ASSET}", MAX_ASSET)
        digest = verify(data, sums.decode("utf-8", "replace"), tag)
        if UPDATE_DIR.is_symlink():
            raise UpdateError("The update folder is a link to somewhere else, so nothing was installed.")
        _write_atomic(ZIP, data)
        _write_atomic(MANIFEST, json.dumps({"version": tag, "sha256": digest, "asset": ASSET,
                                            "source": f"{RELEASES}/tag/{tag}"}).encode())
        active["pending"] = tag
        return True, f"Updated to {tag}. Restart Dlr to use it."
    except UpdateError as e:
        return False, f"{e} Keeping {current}."


# ---- gallery-dl (photo posts) ----

GDL_INDEX = "https://pypi.org/pypi/gallery-dl/json"
GDL_DIR = app_dir() / "gallery-dl"
GDL_WHEEL, GDL_MANIFEST = GDL_DIR / "gallery-dl.whl", GDL_DIR / "manifest.json"
MAX_GDL = 20 * 1024 * 1024
_GDL_VERSION = re.compile(r"\d+(\.\d+){1,3}")

# What the gallery-dl child process uses; filled in by activate_gallery_dl().
gdl_active = {"source": "built-in", "version": "", "note": ""}


def gdl_vtuple(version: str) -> tuple:
    return tuple(int(x) for x in version.split(".")) if version and _GDL_VERSION.fullmatch(version) else ()


def gdl_builtin_version() -> str:
    try:
        return importlib.metadata.version("gallery-dl")
    except importlib.metadata.PackageNotFoundError:
        return ""


def _gdl_manifest() -> dict:
    """The saved gallery-dl update, if it's there, newer than the built-in one and undamaged."""
    try:
        if GDL_DIR.is_symlink() or GDL_WHEEL.is_symlink():
            return {}
        manifest = json.loads(GDL_MANIFEST.read_text(encoding="utf-8"))
        version = manifest["version"]
        if gdl_vtuple(version) <= gdl_vtuple(gdl_builtin_version()):
            return {}
        if _sha256(GDL_WHEEL) != manifest.get("sha256"):
            for path in (GDL_WHEEL, GDL_MANIFEST):
                path.unlink(missing_ok=True)
            return {}
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def gallery_dl_version() -> str:
    """The gallery-dl the next photo download will use."""
    return _gdl_manifest().get("version") or gdl_builtin_version()


def activate_gallery_dl() -> dict:
    """Use the downloaded gallery-dl if it's newer and healthy, else the built-in one.
    Must run before gallery_dl is imported (only in the gallery-dl child process)."""
    gdl_active.update(source="built-in", version=gdl_builtin_version(), note="")
    if not getattr(sys, "frozen", False):
        return gdl_active  # running from source: pip manages gallery-dl
    manifest = _gdl_manifest()
    if not manifest:
        return gdl_active
    sys.path.insert(0, str(GDL_WHEEL))
    try:
        import gallery_dl.version
        if gallery_dl.version.__version__ != manifest["version"]:
            raise ImportError("version mismatch")
        gdl_active.update(source="updated", version=manifest["version"])
    except Exception:
        sys.path.remove(str(GDL_WHEEL))
        for name in [m for m in sys.modules if m == "gallery_dl" or m.startswith("gallery_dl.")]:
            del sys.modules[name]
        for path in (GDL_WHEEL, GDL_MANIFEST):
            path.unlink(missing_ok=True)
        gdl_active["note"] = f"gallery-dl {manifest['version']} didn't load, so the built-in version is used."
    return gdl_active


def gdl_latest() -> tuple[str, str, str]:
    """(version, wheel URL, SHA-256) of the newest gallery-dl release, from PyPI."""
    _, data = _get(GDL_INDEX, 8 * 1024 * 1024, allowed=_allowed_pypi, site="PyPI")
    try:
        index = json.loads(data)
        version = index["info"]["version"]
        wheel = next(u for u in index["urls"] if u.get("packagetype") == "bdist_wheel"
                     and u.get("filename") == f"gallery_dl-{version}-py3-none-any.whl")
        digest = wheel["digests"]["sha256"].lower()
    except (ValueError, KeyError, TypeError, StopIteration):
        raise UpdateError("Couldn't read the latest gallery-dl release from PyPI.") from None
    if not _GDL_VERSION.fullmatch(version) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise UpdateError("Couldn't read the latest gallery-dl release from PyPI.")
    if not _allowed_pypi(wheel.get("url", "")):
        raise UpdateError("The gallery-dl download isn't on PyPI, so it was stopped.")
    return version, wheel["url"], digest


def verify_gallery_dl(data: bytes, expected: str, version: str) -> str:
    """Check a downloaded gallery-dl wheel against PyPI's SHA-256 and its own version."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise UpdateError("The download didn't match the official checksum, so it was rejected.")
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            text = z.read("gallery_dl/version.py").decode("utf-8")
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
        raise UpdateError("The download isn't a valid gallery-dl file, so it was rejected.") from None
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not m or m.group(1) != version:
        raise UpdateError("The downloaded gallery-dl has the wrong version inside, so it was rejected.")
    return digest


def install_latest_gallery_dl() -> tuple[bool, str]:
    """Download, verify and save the newest gallery-dl. Returns (changed, message)."""
    current = gallery_dl_version()
    try:
        version, url, expected = gdl_latest()
        if gdl_vtuple(version) <= gdl_vtuple(current):
            return False, f"Up to date ({current})"
        _, data = _get(url, MAX_GDL, allowed=_allowed_pypi, site="PyPI")
        digest = verify_gallery_dl(data, expected, version)
        if GDL_DIR.is_symlink():
            raise UpdateError("The update folder is a link to somewhere else, so nothing was installed.")
        _write_atomic(GDL_WHEEL, data)
        _write_atomic(GDL_MANIFEST, json.dumps({"version": version, "sha256": digest,
                                                "source": url}).encode())
        return True, f"Updated to {version}."
    except UpdateError as e:
        return False, f"{e} Keeping {current}."
