"""Input, network and file-system safety rules.

- Links: http/https only, never starting with "-", a sane length, no control characters, no
  logins in the link, and never this computer or the local network (localhost, 192.168.x.x ...).
- Network: once install_network_guard() has run, every connection the app's Python code makes
  (yt-dlp, gallery-dl, updates, thumbnails) is checked again when it connects, so a redirect or
  a name that changes what it points to (DNS rebinding) can't reach a local address either.
- Things Dlr fetches itself (thumbnails, covers, photos, share links): every redirect hop is
  checked, and the size is capped.
- Files: safe names (no folders, no "..", no hidden files), never overwrite an
  existing file, and never write or delete outside the download folder
  (symlinks included).
- Messages: file paths and cookies are removed from any error text shown to the user.
"""
import ipaddress
import os
import re
import socket
import tempfile
import unicodedata
import urllib.request
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024  # for small things we fetch ourselves (thumbnails, covers)
MAX_REDIRECTS = 5
MAX_IMAGE_PIXELS = 40_000_000  # larger images are refused ("decompression bombs")


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


def _is_public_address(address: str) -> bool:
    try:
        return _is_public_ip(ipaddress.ip_address(str(address).split("%")[0]))
    except ValueError:
        return False


_original_getaddrinfo = None  # set by install_network_guard()


def _resolve(host: str, port=None):
    return (_original_getaddrinfo or socket.getaddrinfo)(host, port)


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
            addresses = {info[4][0] for info in _resolve(host)}
        except OSError:
            return  # can't resolve: the download itself will report a network error
        for address in addresses:
            if not _is_public_address(address):
                raise blocked


def check_url(url, resolve: bool = True) -> str:
    """Return the cleaned-up link, or raise UnsafeInput with a friendly reason."""
    if not isinstance(url, str):
        raise UnsafeInput("Paste a video link first.")
    url = url.strip()
    if not url:
        raise UnsafeInput("Paste a video link first.")
    if url.startswith("-"):  # could be read as an option by a command-line tool
        raise UnsafeInput("That isn't a web link.")
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
    check_length(response, limit)
    data = response.read(limit + 1)
    if len(data) > limit:
        raise UnsafeInput("The file is too large.")
    return data


def check_length(response, limit: int):
    """Refuse a response that says up front it's larger than limit."""
    length = (response.headers.get("Content-Length") or "").strip() if getattr(response, "headers", None) else ""
    if length.isdigit() and int(length) > limit:
        raise UnsafeInput("The file is too large.")


class CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow at most MAX_REDIRECTS redirects, each checked with check_url first, and only to
    http/https (never this computer or the local network). Only the request's own headers
    for the first site go along: no cookies, no logins."""
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)  # every hop: never this computer or the local network
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            for name in ("Cookie", "Authorization"):
                new.remove_header(name)
        return new


def open_url(url: str, headers: dict | None = None, timeout: float = 15):
    """Open a public web address with checked redirects. The caller reads it with a size cap
    (read_limited). Raises UnsafeInput for addresses that aren't allowed."""
    url = check_url(url)
    req = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(CheckedRedirects)
    response = opener.open(req, timeout=timeout)
    try:
        check_url(response.geturl())  # where it ended up, too
    except UnsafeInput:
        response.close()
        raise
    return response


# ---- every connection: never this computer or the local network ----

def install_network_guard():
    """From now on, connections from this process (Python's socket module: urllib, requests,
    yt-dlp, gallery-dl) can only go to public internet addresses. Names that resolve to a
    local address are refused when connecting, not just when a link is checked, which also
    covers redirects inside yt-dlp and gallery-dl and DNS rebinding. A proxy set up on this
    Mac (System Settings or the usual environment variables) stays reachable."""
    global _original_getaddrinfo
    if _original_getaddrinfo is not None:
        return
    original = socket.getaddrinfo
    proxies = set()
    try:
        for scheme, proxy in urllib.request.getproxies().items():
            if scheme == "no":  # NO_PROXY lists hosts to reach directly, not proxies
                continue
            host = urlsplit(proxy if "://" in proxy else f"http://{proxy}").hostname
            if host:
                proxies.add(host.lower().rstrip("."))
    except Exception:
        pass

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        results = original(host, port, *args, **kwargs)
        if host is None:
            return results  # a local listening address, not a connection
        name = (host.decode("idna", "replace") if isinstance(host, bytes) else str(host))
        if name.strip("[]").lower().rstrip(".") in proxies:
            return results
        public = [r for r in results if _is_public_address(r[4][0])]
        if not public:
            raise socket.gaierror(socket.EAI_NONAME, "Links to this computer or your local network aren't allowed.")
        return public

    _original_getaddrinfo = original
    socket.getaddrinfo = guarded_getaddrinfo


# ---- messages shown to the user ----

_HOME = os.path.expanduser("~")
_QUOTED_PATHS = re.compile(r"(['\"])(?:file://)?(?:~|/)[^'\"\n]*\1")
_FILE_URLS = re.compile(r"file://[^\s'\"<>]+", re.I)
_PATHS = re.compile(r"(?:(?<=^)|(?<=[\s'\"(\[=,]))(?:~|/)[^\s'\"<>]*[^\s'\"<>.,;:)\]]")
_AUTH = re.compile(r"(?i)\b(authorization|proxy-authorization)(\s*[:=]\s*)[^\r\n]+")
_COOKIES = re.compile(r"(?i)\b(cookies?|set-cookie|x-csrftoken|sessionid|token)(\s*[:=]\s*)[^\s,;]+(?:\s*;\s*[^\s,;]+)*;?")


def scrub(message) -> str:
    """Error text without file paths, user names or cookies, safe to show or print."""
    text = str(message or "")
    if _HOME and _HOME != "/":
        text = text.replace(_HOME, "~")
    text = _AUTH.sub(lambda m: f"{m.group(1)}{m.group(2)}[hidden]", text)
    text = _COOKIES.sub(lambda m: f"{m.group(1)}{m.group(2)}[hidden]", text)
    text = _QUOTED_PATHS.sub(lambda m: f"{m.group(1)}[file]{m.group(1)}", text)
    text = _FILE_URLS.sub("[file]", text)
    return _PATHS.sub("[file]", text)


def safe_filename(name, max_bytes: int = 150, fallback: str = "download") -> str:
    """A file name with no folders, no "..", not hidden, and valid on the Mac, iPhone and USB drives.

    Limited in bytes, not characters: names may be at most 255 bytes and an emoji takes
    4, so this leaves room for " (2)" and yt-dlp's ".f137.webm.part" endings.
    """
    name = unicodedata.normalize("NFC", str(name or ""))
    name = _CONTROL_IN_NAMES.sub("", name)
    name = re.sub(r'[\\/:*?"<>|]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.lstrip(". ").rstrip(". ")  # no hidden files, no trailing dots
    name = name.encode("utf-8")[:max_bytes].decode("utf-8", "ignore").rstrip(". ")
    if not name:
        name = fallback
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


def safe_ext(ext: str) -> str:
    """A file extension like ".mp4": a dot and up to 10 letters or digits, or ".bin"."""
    ext = str(ext or "").lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{1,10}", ext) else ".bin"


def move_into(folder: str, src: str, base: str, ext: str) -> str:
    """Move src into folder as base+ext, or "base (2)ext", "base (3)ext" ... Only the exact
    same name and extension counts as taken, and an existing file is never replaced:
    the name is first claimed by creating it exclusively, then src is moved onto that claim."""
    base, ext = safe_filename(base, 200, "download"), safe_ext(ext)
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


def move_dir_into(folder: str, base: str, files: list[tuple[str, str]]) -> str:
    """Make a new folder base (or "base (2)" ...) inside folder and move each (src, name) into
    it. An existing folder is never reused: the name is claimed by creating it exclusively."""
    base = safe_filename(base, 200, "download")
    n = 1
    while True:
        target = os.path.join(folder, base if n == 1 else f"{base} ({n})")
        try:
            os.mkdir(target, 0o755)
        except FileExistsError:
            n += 1
            continue
        break
    for src, name in files:
        name = safe_filename(name, 150, "file")
        move_into(target, src, *os.path.splitext(name))
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
