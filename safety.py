"""Input and file-system safety rules, shared by the Mac app and the iPhone script.

- Links: http/https only, a sane length, no control characters, no logins in the
  link, and never this computer or the local network (localhost, 192.168.x.x ...).
- Files: safe names (no folders, no "..", no hidden files), never overwrite an
  existing file, and never write or delete outside the download folder
  (symlinks included).
"""
import ipaddress
import os
import re
import socket
import tempfile
import unicodedata
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024  # for small things we fetch ourselves (thumbnails, covers)


class UnsafeInput(ValueError):
    """Rejected input; the message is safe to show to the user."""


# Control characters, plus invisible ones that can disguise text (zero-width, bidi overrides).
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
# The same for file names, except the zero-width joiner (U+200D) that combined emoji need.
_CONTROL_IN_NAMES = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b\u200c\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".home.arpa", ".corp", ".intranet")


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_host(host: str, resolve: bool = True) -> None:
    """Raise UnsafeInput unless host is a public internet address."""
    host = (host or "").strip("[]").lower().rstrip(".")
    if not host:
        raise UnsafeInput("That link has no website in it.")
    blocked = UnsafeInput("Links to this computer or your local network aren't allowed.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None  # a name, not an IP address
    if ip is not None:
        if not _is_public_ip(ip):
            raise blocked
        return
    if host == "localhost" or "." not in host or host.endswith(_LOCAL_SUFFIXES):
        raise blocked
    if resolve:
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
        except OSError:
            return  # can't resolve: the download itself will report a network error
        for address in addresses:
            if not _is_public_ip(ipaddress.ip_address(address.split("%")[0])):
                raise blocked


def check_url(url, resolve: bool = True) -> str:
    """Return the cleaned-up link, or raise UnsafeInput with a friendly reason."""
    if not isinstance(url, str):
        raise UnsafeInput("Paste a video link first.")
    url = url.strip()
    if not url:
        raise UnsafeInput("Paste a video link first.")
    if len(url) > MAX_URL_LENGTH:
        raise UnsafeInput("That link is too long.")
    if _CONTROL.search(url) or any(c.isspace() for c in url):
        raise UnsafeInput("That link contains hidden or invalid characters.")
    if not re.match(r"[a-z][a-z0-9+.-]*://", url, re.I):
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise UnsafeInput("Only web links (http or https) can be downloaded.")
    if parts.username or parts.password:
        raise UnsafeInput("Links with a username or password in them aren't allowed.")
    try:
        parts.port  # raises on a malformed port
    except ValueError:
        raise UnsafeInput("That link isn't valid.") from None
    check_host(parts.hostname, resolve)
    return url


def read_limited(response, limit: int = MAX_DOWNLOAD_BYTES) -> bytes:
    """Read an HTTP response, refusing anything larger than limit."""
    data = response.read(limit + 1)
    if len(data) > limit:
        raise UnsafeInput("The file is too large.")
    return data


_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe_filename(name, max_bytes: int = 150, fallback: str = "download") -> str:
    """A file name with no folders, no "..", not hidden, and valid on Mac, Windows and iOS.

    Limited in bytes, not characters: names may be at most 255 bytes and an emoji takes
    4, so this leaves room for " (2)" and yt-dlp's ".f137.webm.part" endings.
    """
    name = unicodedata.normalize("NFC", str(name or ""))
    name = _CONTROL_IN_NAMES.sub("", name)
    name = re.sub(r'[\\/:*?"<>|]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.lstrip(". ").rstrip(". ")  # no hidden files, no trailing dots (Windows)
    name = name.encode("utf-8")[:max_bytes].decode("utf-8", "ignore").rstrip(". ")
    if not name or name.split(".")[0].lower() in _RESERVED:
        name = fallback + (f" {name}" if name else "")
    return name


def real_folder(folder: str) -> str:
    """The download folder with symlinks resolved; it must exist."""
    real = os.path.realpath(os.path.expanduser(folder))
    if not os.path.isdir(real):
        raise UnsafeInput("The download folder doesn't exist.")
    return real


def is_inside(folder: str, path: str) -> bool:
    """True if path is a direct, non-symlink entry inside folder."""
    folder = os.path.realpath(folder)
    parent = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    return parent == folder and not os.path.islink(path)


def move_into(folder: str, src: str, base: str, ext: str) -> str:
    """Move src into folder as base+ext, or "base (2)ext", "base (3)ext" ... Only the exact
    same name and extension counts as taken, and an existing file is never replaced:
    the name is first claimed by creating it exclusively, then src is moved onto that claim."""
    n = 1
    while True:
        name = f"{base}{ext}" if n == 1 else f"{base} ({n}){ext}"
        target = os.path.join(folder, name)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
        except FileExistsError:
            n += 1
            continue
        os.close(fd)
        os.replace(src, target)  # replaces only the empty claim we just made
        return target


def temp_file(folder: str, suffix: str) -> str:
    """Create a new, empty, randomly named hidden temp file in folder (never an existing one)."""
    fd, path = tempfile.mkstemp(dir=folder, prefix=".vd-", suffix=suffix)
    os.close(fd)
    return path


def remove_inside(folder: str, path: str) -> None:
    """Delete path only if it's a regular file directly inside folder."""
    try:
        if path and is_inside(folder, path) and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
