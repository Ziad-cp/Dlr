"""Spotify links: read the song's public info and find the same song on YouTube.

Spotify's own audio is DRM-protected, so like the "Spotify downloader" websites
this downloads the matching YouTube upload instead, then tags it with the
title, artist and cover art from Spotify.
"""
import json
import re
import threading
import unicodedata
import urllib.request

import yt_dlp

import safety

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# Words that mean a different version of the song, unless Spotify's title has them too.
_OTHER_VERSIONS = ["live", "cover", "remix", "sped up", "slowed", "reverb", "karaoke", "instrumental",
                   "nightcore", "8d", "piano", "pianoforte", "acoustic", "1 hour", "loop", "edit", "mashup"]


class SpotifyError(Exception):
    """A message that is safe to show to the user."""


def is_spotify(url: str) -> bool:
    return bool(re.match(r"(?:https?://)?(?:[\w-]+\.)*(?:spotify\.com|spotify\.link)(?:[/?#]|$)",
                         url.strip(), re.I))


def _get(url: str) -> tuple[str, str]:
    """Fetch a Spotify page; returns (final URL after redirects, body)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=15) as r:
        final = r.geturl()
        if not is_spotify(final) or not final.lower().startswith("https://"):
            raise SpotifyError("That Spotify link points somewhere else.")
        return final, safety.read_limited(r).decode("utf-8", "replace")


def _track_id(url: str) -> str:
    url = url.strip()
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    if "spotify.link" in url.lower():  # share links redirect to open.spotify.com
        try:
            url, _ = _get(url)
        except OSError:
            raise SpotifyError("Couldn't open this Spotify link. Check your internet connection.") from None
    m = re.search(r"/(track|album|playlist|artist|episode|show)/([A-Za-z0-9]{22})", url)
    if not m:
        raise SpotifyError("That doesn't look like a Spotify song link.")
    if m.group(1) != "track":
        raise SpotifyError("Paste a link to a single Spotify song. Albums, playlists, artists "
                           "and podcasts aren't supported.")
    return m.group(2)


def track_info(url: str) -> dict:
    """Public info for a Spotify song: name, artists, duration, cover, year."""
    tid = _track_id(url)
    try:
        _, html = _get(f"https://open.spotify.com/embed/track/{tid}")
        data = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        entity = json.loads(data.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (OSError, AttributeError, KeyError, ValueError):
        raise SpotifyError("Couldn't read this song from Spotify. Check the link and try again.") from None
    images = (entity.get("visualIdentity") or {}).get("image") or []
    cover = max(images, key=lambda i: i.get("maxWidth") or 0)["url"] if images else ""
    release = entity.get("releaseDate") or {}
    year = str(release.get("isoString", ""))[:4] if isinstance(release, dict) else ""
    return {
        "id": tid,
        "url": f"https://open.spotify.com/track/{tid}",
        "name": entity.get("name") or entity.get("title") or "",
        "artists": [a["name"] for a in entity.get("artists") or [] if a.get("name")],
        "duration": (entity.get("duration") or 0) / 1000,
        "cover": cover,
        "year": year,
    }


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _score(track: dict, entry: dict) -> float:
    title, channel = _norm(entry.get("title")), _norm(entry.get("channel") or entry.get("uploader"))
    name, artist = _norm(track["name"]), _norm(track["artists"][0] if track["artists"] else "")
    score = 0.0
    if track["duration"] and entry.get("duration"):
        diff = abs(entry["duration"] - track["duration"])
        if diff > 15:
            return float("-inf")  # too different to be the same recording
        score -= diff
    if name and name not in title:
        score -= 10
    if artist and (artist in channel or channel.endswith(" topic")):
        score += 8
    elif artist and artist in title:
        score += 2
    if "official audio" in title or channel.endswith(" topic"):
        score += 5
    elif "audio" in title:
        score += 4
    elif "official" in title:
        score += 1  # music videos can have intros or skits the song doesn't
    for word in _OTHER_VERSIONS:
        if re.search(rf"\b{word}\b", title) and not re.search(rf"\b{word}\b", name):
            score -= 15
    return score


def find_on_youtube(track: dict) -> str:
    """URL of the YouTube upload that best matches the Spotify song."""
    query = f"{', '.join(track['artists'][:2])} - {track['name']}"
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            results = ydl.extract_info(f"ytsearch10:{query} audio", download=False)
    except Exception:
        raise SpotifyError("Couldn't search YouTube for this song. Check your internet connection.") from None
    entries = [e for e in results.get("entries") or [] if e and e.get("url")]
    ranked = sorted(entries, key=lambda e: _score(track, e), reverse=True)
    if not ranked or _score(track, ranked[0]) == float("-inf"):
        raise SpotifyError(f"Couldn't find “{track['name']}” on YouTube, so it can't be downloaded.")
    return ranked[0]["url"]


_cache: dict[str, tuple[dict, str]] = {}
_lock = threading.Lock()


def resolve(url: str) -> tuple[dict, str]:
    """(Spotify song info, matching YouTube URL). Cached, so fetch and download agree."""
    tid = _track_id(url)
    with _lock:
        if tid in _cache:
            return _cache[tid]
    track = track_info(url)
    result = (track, find_on_youtube(track))
    with _lock:
        _cache[tid] = result
    return result
