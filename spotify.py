"""Spotify links (songs, albums, playlists): read their public info and find each song on
YouTube Music.

Spotify's own audio is DRM-protected, so like the "Spotify downloader" websites this
downloads the matching YouTube Music upload instead, then tags the MP3 with the title,
artist, album and cover art from Spotify.

The info comes from Spotify's public embed pages (open.spotify.com/embed/...), the ones
websites use to show a player. They need no account and no API key, so Spotify's Web API
rules (which since 2026 need a Premium account and an app review) don't apply.
"""
import json
import re
import threading
import unicodedata
import urllib.parse
import urllib.request

import yt_dlp

import safety

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# Words that mean a different version of the song, unless Spotify's title has them too.
_OTHER_VERSIONS = ["live", "cover", "remix", "sped up", "slowed", "reverb", "karaoke", "instrumental",
                   "nightcore", "8d", "piano", "pianoforte", "acoustic", "1 hour", "loop", "edit", "mashup"]

KINDS = ("track", "album", "playlist")
MAX_TRACKS = 300


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


def parse(url: str) -> tuple[str, str]:
    """("track" | "album" | "playlist", Spotify ID) of a link. Share links are followed."""
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
        raise SpotifyError("That doesn't look like a Spotify song, album or playlist link.")
    if m.group(1) not in KINDS:
        raise SpotifyError("Paste a link to a Spotify song, album or playlist. Artists and "
                           "podcasts aren't supported.")
    return m.group(1), m.group(2)


def is_collection(url: str) -> bool:
    """An album or playlist link (without opening share links)."""
    return bool(re.search(r"/(album|playlist)/[A-Za-z0-9]{22}", url))


def _embed(kind: str, sid: str) -> dict:
    try:
        _, html = _get(f"https://open.spotify.com/embed/{kind}/{sid}")
        data = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        return parse_embed(data.group(1))
    except (OSError, AttributeError, KeyError, ValueError, TypeError):
        raise SpotifyError(f"Couldn't read this {'song' if kind == 'track' else kind} from Spotify. "
                           "Check the link and try again.") from None


def parse_embed(next_data: str) -> dict:
    """The "entity" from an embed page's __NEXT_DATA__ JSON."""
    return json.loads(next_data)["props"]["pageProps"]["state"]["data"]["entity"]


def _cover(entity: dict) -> str:
    images = (entity.get("visualIdentity") or {}).get("image") or []
    if not images:
        images = [{"url": s.get("url"), "maxWidth": s.get("width")}
                  for s in (entity.get("coverArt") or {}).get("sources") or []]
    images = [i for i in images if i.get("url")]
    return max(images, key=lambda i: i.get("maxWidth") or 0)["url"] if images else ""


def _year(entity: dict) -> str:
    release = entity.get("releaseDate") or {}
    return str(release.get("isoString", ""))[:4] if isinstance(release, dict) else ""


def _artists(text: str) -> list[str]:
    return [a.strip() for a in re.split(r", |, ", text or "") if a.strip()]


def track_from_entity(entity: dict, tid: str) -> dict:
    return {
        "id": tid,
        "url": f"https://open.spotify.com/track/{tid}",
        "name": entity.get("name") or entity.get("title") or "",
        "artists": [a["name"] for a in entity.get("artists") or [] if a.get("name")],
        "duration": (entity.get("duration") or 0) / 1000,
        "cover": _cover(entity),
        "year": _year(entity),
        "album": "",
        "number": 0,
    }


def collection_from_entity(kind: str, entity: dict, sid: str) -> dict:
    """An album or playlist: its name, owner/artist, cover and songs, in order."""
    cover, year = _cover(entity), _year(entity)
    tracks = []
    for n, item in enumerate(entity.get("trackList") or [], 1):
        m = re.fullmatch(r"spotify:track:([A-Za-z0-9]{22})", str(item.get("uri") or ""))
        if not m or item.get("isPlayable") is False:
            continue
        tracks.append({
            "id": m.group(1),
            "url": f"https://open.spotify.com/track/{m.group(1)}",
            "name": item.get("title") or "",
            "artists": _artists(item.get("subtitle")),
            "duration": (item.get("duration") or 0) / 1000,
            # An album's songs share its cover, name and year; a playlist's are looked up one by one.
            "cover": cover if kind == "album" else "",
            "year": year if kind == "album" else "",
            "album": (entity.get("name") or entity.get("title") or "") if kind == "album" else "",
            "number": n,
        })
    return {
        "kind": kind,
        "id": sid,
        "name": entity.get("name") or entity.get("title") or "",
        "owner": entity.get("subtitle") or "",
        "cover": cover,
        "year": year,
        "tracks": tracks[:MAX_TRACKS],
    }


def track_info(url_or_id: str) -> dict:
    """Public info for a Spotify song: name, artists, duration, cover, year."""
    tid = url_or_id if re.fullmatch(r"[A-Za-z0-9]{22}", url_or_id) else _track_id(url_or_id)
    return track_from_entity(_embed("track", tid), tid)


def _track_id(url: str) -> str:
    kind, sid = parse(url)
    if kind != "track":
        raise SpotifyError("Paste a link to a single Spotify song.")
    return sid


def collection(url: str) -> dict:
    """An album's or playlist's info and songs."""
    kind, sid = parse(url)
    if kind == "track":
        raise SpotifyError("That's a single song, not an album or playlist.")
    with _lock:
        if (kind, sid) in _lists:
            return _lists[(kind, sid)]
    result = collection_from_entity(kind, _embed(kind, sid), sid)
    if not result["tracks"]:
        raise SpotifyError(f"This {kind} has no songs that can be played.")
    with _lock:
        _lists[(kind, sid)] = result
    return result


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _score(track: dict, entry: dict) -> float:
    title = _norm(entry.get("track") or entry.get("title"))
    artists = entry.get("artists") or [entry.get("artist") or ""]
    channel = _norm(" ".join([*map(str, artists), str(entry.get("channel") or entry.get("uploader") or "")]))
    name, artist = _norm(track["name"]), _norm(track["artists"][0] if track["artists"] else "")
    score = 0.0
    if track["duration"] and entry.get("duration"):
        diff = abs(entry["duration"] - track["duration"])
        if diff > 15:
            return float("-inf")  # too different to be the same recording
        score -= diff
    if name and name not in title and title not in name:
        score -= 10
    if artist and (artist in channel or channel.endswith(" topic")):
        score += 8
    elif artist and artist in title:
        score += 2
    if entry.get("track") or "official audio" in title or channel.endswith(" topic"):
        score += 5
    elif "audio" in title:
        score += 4
    elif "official" in title:
        score += 1  # music videos can have intros or skits the song doesn't
    for word in _OTHER_VERSIONS:
        if re.search(rf"\b{word}\b", title) and not re.search(rf"\b{word}\b", name):
            score -= 15
    return score


_GOOD_ENOUGH = -5.0


def _search(url: str, limit: int) -> list[dict]:
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True,
            "cachedir": False, "playlistend": limit}
    with yt_dlp.YoutubeDL(opts) as ydl:
        results = ydl.extract_info(url, download=False)
    return [e for e in results.get("entries") or [] if e and e.get("url")][:limit]


def _details(url: str) -> dict:
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "cachedir": False,
                           "noplaylist": True}) as ydl:
        return ydl.extract_info(url, download=False, process=False)


def find_on_youtube(track: dict, music: bool = True) -> str:
    """URL of the YouTube Music song (or else YouTube upload) that best matches the Spotify song.
    music=False skips YouTube Music (a second choice, when its song wouldn't download)."""
    query = f"{', '.join(track['artists'][:2])} - {track['name']}"
    try:
        if not music:
            raise LookupError
        # YouTube Music's "Songs" are the official recordings. Their search results don't say
        # how long each one is, so the first few are opened and checked.
        for entry in _search(f"https://music.youtube.com/search?q={urllib.parse.quote(query)}#songs", 3):
            try:
                details = _details(entry["url"])
            except Exception:
                continue
            if _score(track, details) >= _GOOD_ENOUGH:
                # Same song, same ID: downloading through youtube.com is more reliable than
                # music.youtube.com (whose streams can stall), and keeps the album details.
                return f"https://www.youtube.com/watch?v={details['id']}"
    except Exception:
        pass  # YouTube Music can't be searched right now: fall back to YouTube
    try:
        entries = _search(f"ytsearch10:{query} audio", 10)
    except Exception:
        raise SpotifyError("Couldn't search YouTube for this song. Check your internet connection.") from None
    ranked = sorted(entries, key=lambda e: _score(track, e), reverse=True)
    if not ranked or _score(track, ranked[0]) == float("-inf"):
        raise SpotifyError(f"Couldn't find “{track['name']}” on YouTube Music, so it can't be downloaded.")
    return ranked[0]["url"]


_cache: dict[str, tuple[dict, str]] = {}
_lists: dict[tuple[str, str], dict] = {}
_lock = threading.Lock()


def resolve(url: str) -> tuple[dict, str]:
    """(Spotify song info, matching YouTube URL). Cached, so fetch and download agree."""
    tid = _track_id(url)
    with _lock:
        if tid in _cache:
            return _cache[tid]
    track = track_info(tid)
    result = (track, find_on_youtube(track))
    with _lock:
        _cache[tid] = result
    return result


def match(track: dict) -> str:
    """The YouTube URL for one song of an album or playlist (cached like resolve)."""
    with _lock:
        if track["id"] in _cache:
            return _cache[track["id"]][1]
    url = find_on_youtube(track)
    with _lock:
        _cache[track["id"]] = (track, url)
    return url
