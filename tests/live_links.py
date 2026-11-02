"""Real downloads from real sites, to run on your own Mac (not on GitHub: YouTube, TikTok,
Instagram and Reddit block GitHub's datacenter computers).

    python tests/live_links.py                         # the source code in this folder
    python tests/live_links.py --app dist/Dlr.app      # a built app
    python tests/live_links.py --only tiktok --keep    # one site; keep the files
    python tests/live_links.py --logins                # use the "Logins from" setting

Each case downloads 2-3 public links through Dlr's own command line (--download), so it
runs exactly the app's code, then checks the result with ffprobe:
  - videos are MP4s with both picture and sound (Reddit's are merged from two streams),
  - photo posts are folders with the photos (and a slideshow's sound as audio.mp3),
  - MP3s are about 320 kbps and Spotify ones carry title, artist, album and cover art.

Logins are off unless --logins is given. A link that only works when logged in is reported
as NEEDS LOGIN rather than as a failure, so you can tell the two apart; run again with
--logins (and be logged in to the site in your browser) to check those.
Files go to a temporary folder that is deleted afterwards (unless --keep).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (site, case, mode, check, links). mode is what --download gets: video, mp3 or a height.
CASES = [
    ("youtube", "video", "video", "video", [
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
        "https://youtu.be/dQw4w9WgXcQ?si=share",
    ]),
    ("youtube", "picked quality", "480", "video480", [
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
    ]),
    ("youtube", "mp3", "mp3", "mp3", [
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    ]),
    ("tiktok", "video, no watermark", "video", "video", [
        "https://www.tiktok.com/@hankgreen1/video/7047596209028074758",
        "https://www.tiktok.com/@gimenezluciana/video/7669591210486467848",
    ]),
    ("tiktok", "slideshow (photos + sound)", "video", "slideshow", [
        "https://www.tiktok.com/@velocitydrawing/photo/7266832970353233185",
    ]),
    ("tiktok", "slideshow sound as MP3", "mp3", "mp3", [
        "https://www.tiktok.com/@velocitydrawing/photo/7266832970353233185",
    ]),
    ("tiktok", "share link", "video", "video", [
        "https://vt.tiktok.com/ZS4ghQ5py/",
        "https://vt.tiktok.com/ZSXjHUWbe/",
    ]),
    ("instagram", "reel", "video", "video", [
        "https://www.instagram.com/reel/Chunk8-jurw/",
        "https://www.instagram.com/reels/Cop84x6u7CP/",
    ]),
    ("instagram", "video post", "video", "video", [
        "https://www.instagram.com/p/DUNGKnBCSdC/",
        "https://www.instagram.com/p/C9GAp84SPWW/",
    ]),
    ("instagram", "photo post", "video", "photos", [
        "https://www.instagram.com/p/Cmzn4-LMjt2/",
        "https://www.instagram.com/p/CmUv48DLvxd/",
    ]),
    ("instagram", "single photo", "video", "photos", [
        "https://www.instagram.com/p/BsOGulcndj-/",
    ]),
    ("instagram", "mixed carousel (photos + videos)", "video", "mixed", [
        "https://www.instagram.com/p/DQ3zR6-DPGm/",
        "https://www.instagram.com/p/CmcjUz3tXBa/",
    ]),
    ("instagram", "share link", "video", "any", [
        "https://www.instagram.com/share/reel/_gdkGEJBn",
        "https://www.instagram.com/share/_a7bsO89b",
    ]),
    ("reddit", "video with sound", "video", "video", [
        "https://www.reddit.com/r/videos/comments/6rrwyj/that_small_heart_attack/",
        "https://www.reddit.com/r/aww/comments/90bu6w/heat_index_was_110_degrees_so_we_offered_him_a/",
    ]),
    ("reddit", "gallery", "video", "photos", [
        "https://www.reddit.com/gallery/nip71r",
        "https://www.reddit.com/user/creepyt0es/comments/nip71r/i_plan_to_make_more_stickers_and_prints_check/",
    ]),
    ("reddit", "share link", "video", "any", [
        "https://www.reddit.com/r/cats/s/mqNof1kbPG",
        "https://redd.it/6rrwyj",
    ]),
    ("x", "video", "video", "video", [
        "https://x.com/captainamerica/status/719944021058060289",
        "https://x.com/LisPower1/status/1001551623938805763",
    ]),
    ("facebook", "video", "video", "video", [
        "https://www.facebook.com/cnn/videos/10155529876156509/",
    ]),
    ("spotify", "track", "mp3", "spotify_mp3", [
        "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
    ]),
    ("spotify", "album", "mp3", "spotify_folder", [
        "https://open.spotify.com/album/2546nbn3NfAUPMJ3X0qTJ8",
    ]),
    ("spotify", "playlist", "mp3", "spotify_folder", [
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    ]),
]
# A Spotify playlist has up to 100 songs: test only its first few (DLR_TEST_MAX_SONGS).
MAX_SONGS = "3"
LOGIN_HINTS = ("needs login", "need login", "needs you to be logged in")

IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"}


def ffprobe() -> str:
    for candidate in (ROOT / "packaging" / "ffmpeg" / "ffprobe", shutil.which("ffprobe"),
                      "/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"):
        if candidate and os.path.isfile(candidate):
            return str(candidate)
    sys.exit("ffprobe not found: run python packaging/get_ffmpeg.py first.")


def probe(path: Path) -> dict:
    r = subprocess.run([ffprobe(), "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,height,width:stream_disposition=attached_pic"
                        ":format=format_name,bit_rate:format_tags", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=120)
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        return {}


def kinds(info: dict) -> set:
    return {s["codec_type"] for s in info.get("streams", []) if not s.get("disposition", {}).get("attached_pic")}


def check_video(path: Path, height: int = 0) -> str:
    if path.suffix != ".mp4":
        return f"not an MP4: {path.name}"
    info = probe(path)
    if kinds(info) != {"video", "audio"}:
        return f"expected picture and sound, got {sorted(kinds(info))}"
    if height:
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        if min(v.get("height") or 0, v.get("width") or 0) != height:
            return f"expected {height}p, got {v.get('width')}x{v.get('height')}"
    return ""


def check_mp3(path: Path, tags=False) -> str:
    info = probe(path)
    if path.suffix != ".mp3" or "audio" not in kinds(info):
        return f"not an MP3 with sound: {path.name}"
    kbps = int(info.get("format", {}).get("bit_rate") or 0) // 1000
    if kbps < 300:
        return f"expected about 320 kbps, got {kbps}"
    if tags:
        t = {k.lower(): v for k, v in (info.get("format", {}).get("tags") or {}).items()}
        missing = [k for k in ("title", "artist", "album") if not t.get(k)]
        if missing:
            return f"missing tags: {', '.join(missing)}"
        if not any(s.get("disposition", {}).get("attached_pic") for s in info.get("streams", [])):
            return "no cover art"
    return ""


def check(kind: str, path: Path) -> str:
    """"" if the saved file or folder is right, else what's wrong."""
    if not path.exists():
        return "nothing saved"
    files = sorted(path.iterdir()) if path.is_dir() else [path]
    photos = [f for f in files if f.suffix.lower() in IMAGES]
    videos = [f for f in files if f.suffix == ".mp4"]
    if kind == "video":
        return check_video(path) if path.is_file() else "expected one video, got a folder"
    if kind == "video480":
        return check_video(path, 480)
    if kind == "mp3":
        return check_mp3(path)
    if kind == "spotify_mp3":
        return check_mp3(path, tags=True)
    if kind == "spotify_folder":
        songs = [f for f in files if f.suffix == ".mp3"]
        if not path.is_dir() or not songs:
            return "expected a folder of MP3s"
        return next((f"{s.name}: {e}" for s in songs if (e := check_mp3(s, tags=True))), "")
    if kind == "photos":
        if not photos:
            return "no photos saved"
        return "" if path.is_file() or len(photos) == len(files) else "unexpected files in the folder"
    if kind == "slideshow":
        if len(photos) < 2:
            return f"expected the slideshow's photos, got {len(photos)}"
        sound = path / "audio.mp3"
        return check_mp3(sound) if sound.exists() else "the slideshow's sound (audio.mp3) is missing"
    if kind == "mixed":
        if not photos or not videos:
            return f"expected photos and videos, got {len(photos)} photos and {len(videos)} videos"
        return next((f"{v.name}: {e}" for v in videos if (e := check_video_any(v))), "")
    if kind == "any":
        if path.is_file() and path.suffix == ".mp4":
            return check_video(path)
        return "" if photos or videos else "nothing usable saved"
    raise ValueError(kind)


def check_video_any(path: Path) -> str:
    """A video in a carousel: it must have a picture (some have no sound on purpose)."""
    return "" if "video" in kinds(probe(path)) else f"no picture in {path.name}"


def command(app: str) -> list[str]:
    if app:
        return [str(Path(app) / "Contents" / "MacOS" / "Dlr")]
    python = ROOT / ".venv" / "bin" / "python"
    return [str(python if python.exists() else sys.executable), str(ROOT / "app.py")]


def run_case(cmd, url, mode, folder, logins) -> tuple[str, str]:
    """(saved path, error) for one link."""
    env = dict(os.environ, DLR_TEST_MAX_SONGS=MAX_SONGS)
    env.pop("DLR_LOGINS", None)
    if not logins:
        env["DLR_LOGINS"] = "off"  # otherwise: the app's own "Logins from" setting
    try:
        r = subprocess.run([*cmd, "--download", url, mode, str(folder)], capture_output=True, text=True,
                           timeout=900, env=env)
    except subprocess.TimeoutExpired:
        return "", "took longer than 15 minutes"
    lines = [line for line in r.stdout.splitlines() if line.strip()]
    last = lines[-1] if lines else ""
    if r.returncode != 0 or last.startswith("ERROR"):
        return "", last.removeprefix("ERROR: ") or (r.stderr.strip().splitlines() or ["failed"])[-1]
    return last, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--app", help="a built Dlr.app (default: the source code)")
    parser.add_argument("--only", help="only this site (youtube, tiktok, instagram, reddit, x, facebook, spotify)")
    parser.add_argument("--logins", action="store_true", help="use the app's Logins from setting")
    parser.add_argument("--keep", action="store_true", help="keep the downloaded files")
    args = parser.parse_args()
    if os.environ.get("CI"):
        print("SKIPPED: these sites block GitHub's computers. Run this on your own Mac.")
        return 0
    cmd = command(args.app)
    out = Path(tempfile.mkdtemp(prefix="dlr-live-"))
    results = []
    try:
        for site, case, mode, kind, urls in CASES:
            if args.only and site != args.only:
                continue
            for url in urls:
                folder = out / f"{len(results):02}"
                folder.mkdir()
                started = time.time()
                path, error = run_case(cmd, url, mode, folder, args.logins)
                if not error:
                    error = check(kind, Path(path))
                status = "PASS" if not error else (
                    "NEEDS LOGIN" if not args.logins and any(h in error for h in LOGIN_HINTS) else "FAIL")
                results.append((status, site, case, url, error))
                print(f"{status:<11} {site:<9} {case:<34} {time.time() - started:5.0f}s  {url}"
                      + (f"\n            {error}" if error else ""), flush=True)
    finally:
        if args.keep:
            print(f"\nFiles kept in {out}")
        else:
            shutil.rmtree(out, ignore_errors=True)
    counts = {s: sum(r[0] == s for r in results) for s in ("PASS", "NEEDS LOGIN", "FAIL")}
    print(f"\n{counts['PASS']} passed, {counts['NEEDS LOGIN']} need a login, {counts['FAIL']} failed")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
