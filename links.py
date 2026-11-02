"""Link rules: which site a link is from, share links, and tracking junk.

Share links (vm.tiktok.com/..., instagram.com/share/..., reddit.com/r/.../s/..., redd.it/...)
only redirect to the real post, so they're followed first. Every hop of the redirect is
checked with safety.check_url, so a share link can never lead Dlr to this computer or the
local network. If a link can't be followed, the original is used (yt-dlp knows most of them).
"""
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import safety

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
MAX_HOPS = 5

SITES = {
    "youtube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "tiktok": ("tiktok.com",),
    "instagram": ("instagram.com",),
    "reddit": ("reddit.com", "redd.it"),
    "facebook": ("facebook.com", "fb.watch", "fb.com"),
    "x": ("x.com", "twitter.com"),
    "spotify": ("spotify.com", "spotify.link"),
}

# Query parameters that only track who shared a link.
_TRACKING = re.compile(r"^(utm_\w+|igsh|igshid|_t|_r|share_id|share_app_id|share_item_id|share_link_id"
                       r"|sender_device|sender_web_id|is_from_webapp|is_copy_url|web_id|fbclid|gclid"
                       r"|rdt|si|context|ref_source|ref_url|mibextid|s|t|_d|u_code|timestamp|preview_pb|enter_from"
                       r"|sec_user_id|social_share_type|tt_from|checksum|enable_checksum|user_id|share_source)$", re.I)
def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def site(url: str) -> str:
    """"tiktok", "instagram", "reddit" ... or "" for any other site."""
    host = host_of(url)
    return next((name for name, hosts in SITES.items()
                 if any(host == h or host.endswith("." + h) for h in hosts)), "")


def clean(url: str) -> str:
    """The link without tracking parameters (YouTube's "t", the start time, is kept)."""
    parts = urlsplit(url)
    keep = {"t"} if site(url) == "youtube" else set()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k in keep or not _TRACKING.match(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def is_share_link(url: str) -> bool:
    host, path = host_of(url), urlsplit(url).path
    return bool(
        host in ("vm.tiktok.com", "vt.tiktok.com")
        or (host == "tiktok.com" and re.match(r"/t/\w+", path))
        or (host.endswith("instagram.com") and path.startswith("/share/"))
        or (site(url) == "reddit" and re.match(r"/r/[^/]+/s/\w+", path))
        or (host == "redd.it" and re.fullmatch(r"/\w+/?", path))
        or host == "spotify.link"
    )


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_HOPS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safety.check_url(newurl)  # every hop: never this computer or the local network
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _follow(url: str) -> str:
    opener = urllib.request.build_opener(_CheckedRedirects)
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en"})
    try:
        with opener.open(req, timeout=15) as r:
            return r.geturl()
    except urllib.error.HTTPError as e:
        return e.geturl() or url  # the post itself may refuse us; where it is is enough


def _from_login_page(url: str) -> str:
    """A login page that a share link landed on names the post it was going to."""
    parts = urlsplit(url)
    if "login" not in parts.path:
        return url
    for key, value in parse_qsl(parts.query):
        if key in ("next", "dest", "redirect_url") and value:
            target = value if "://" in value else f"{parts.scheme}://{parts.netloc}{value}"
            if site(target) == site(url):
                return target
    return url


def resolve(url: str) -> str:
    """Follow a share link to the post it points to, and drop tracking parameters.
    Raises safety.UnsafeInput if a hop leads somewhere not allowed."""
    url = safety.check_url(url)
    if is_share_link(url):
        try:
            final = _from_login_page(_follow(url))
            final = safety.check_url(final)
            if site(final) and urlsplit(final).path not in ("", "/"):
                url = final
        except safety.UnsafeInput:
            raise
        except (OSError, ValueError):
            pass  # can't follow it now: let yt-dlp try the original
    return clean(url)


def is_story(url: str) -> bool:
    """Instagram stories and highlights, which are only visible when logged in."""
    return site(url) == "instagram" and urlsplit(url).path.startswith(("/stories/", "/s/"))


def is_photo_link(url: str) -> bool:
    """Links that are photos for sure, so they go straight to gallery-dl."""
    host, path = host_of(url), urlsplit(url).path
    return bool(
        (site(url) == "tiktok" and re.search(r"/photo/\d+", path))
        or (site(url) == "reddit" and path.startswith("/gallery/"))
        or host in ("i.redd.it", "preview.redd.it")
    )


GALLERY_SITES = ("tiktok", "instagram", "reddit", "x", "facebook")
