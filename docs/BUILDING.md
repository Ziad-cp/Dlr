# Building Dlr

Everything needed to run Dlr from source, build the app and publish a release. This is for
developers: people who just want Dlr install it from the .dmg, see the [README](../README.md).

**Mac: Apple Silicon (M1 or newer) only.** The app runs on macOS 12 Monterey or newer (the
oldest macOS the bundled FFmpeg and Deno support), and is built and run from source on an
Apple-chip Mac; `build.py`, `get_ffmpeg.py` and `get_deno.py` stop on any other computer.

## Contents

- [Run from source](#run-from-source)
- [Build the app](#build-the-app)
- [Tests](#tests)
- [Releases](#releases)
- [Command-line mode](#command-line-mode)
- [Project structure](#project-structure)

## Run from source

With Python 3.12 from [python.org](https://www.python.org/downloads/) or elsewhere:

```bash
git clone https://github.com/Ziad-cp/Dlr.git && cd Dlr
python3.12 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-build.txt
.venv/bin/pip install --require-hashes --no-build-isolation -r requirements.txt
.venv/bin/python packaging/get_ffmpeg.py && .venv/bin/python packaging/get_deno.py
.venv/bin/python app.py
```

Running from source, Dlr uses `packaging/ffmpeg/` and `packaging/deno/` (or an FFmpeg and Deno
it finds on the Mac); yt-dlp, gallery-dl and curl_cffi come from `requirements.txt`, where every
package is pinned with the SHA-256 of its files. Running from source, Dlr never updates yt-dlp
or gallery-dl by itself: change the version and hashes in `requirements.txt` instead.

## Build the app

```bash
python packaging/get_ffmpeg.py   # bundle a verified FFmpeg into the app
python packaging/get_deno.py     # bundle a verified Deno (YouTube's challenges)
python build.py
```

Both scripts download a pinned version from a fixed address and stop on any mismatch:
`get_ffmpeg.py` takes FFmpeg 9.0.2 from Martin Riedl's notarized builds for Apple chips (a
third-party build: the FFmpeg project publishes no official macOS binaries, and this is not an
ffmpeg.org binary), and `get_deno.py` takes Deno 2.9.8 from github.com/denoland/deno. Each file must match the
SHA-256 pinned in the script and carry its maker's Apple Developer ID signature. To move to a
newer version, change the version and the SHA-256 (the one published next to the file) in the
script. The app uses only its own FFmpeg and Deno, never ones installed on the Mac.

The output is `dist/Dlr.app` and `dist/Dlr-<version>.dmg` (the workflow renames it
`Dlr-mac-apple-silicon.dmg`).

The app's `Info.plist` sets `LSMinimumSystemVersion` to 12.0 (`MIN_MACOS` in `build.py`).
After building, `build.py` checks every program and library in the app with `vtool`. If any
needs a newer macOS, the GitHub build stops; a local build only warns, because it is just for
that Mac (Homebrew's Python, for example, is built for the newest macOS only). Build release
apps with Python from python.org, as GitHub does.

## Tests

**Unit tests** (offline, also run on GitHub for every push):

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

**Real downloads** from YouTube, TikTok, Instagram, Reddit, X, Facebook and Spotify. These sites
block GitHub's computers, so on GitHub these tests are marked **skipped**; run them on your own
Mac before each release:

```bash
.venv/bin/python tests/live_links.py --app dist/Dlr.app
```

Each case uses 2–3 public links and checks the result with ffprobe (picture and sound, photos,
320 kbps MP3s, Spotify tags and cover). Logins are off unless you add `--logins`; links that
need a login are reported as NEEDS LOGIN rather than as failures. `--only tiktok` runs one
site and `--keep` keeps the files. Without `--app` it tests the source code.

## Releases

GitHub Actions builds and tests the app on every push (`.github/workflows/build.yml`), on an
Apple-chip Mac, including real downloads.

To publish a release:

1. Set `__version__` in `app.py`.
2. On GitHub, open **Releases › Draft a new release**, create the tag `v<version>` and
   publish. Alternatively, push the tag: `git tag v1.1.0 && git push origin v1.1.0`.
3. About 10 minutes later, `Dlr-mac-apple-silicon.dmg` and its checksum
   `Dlr-mac-apple-silicon.dmg.sha256` are attached to the release, and the SHA-256 is in the
   release notes.
4. Put that SHA-256 in the README's **Check the download** section.

The file name is the same for every version, so the README's link
(`https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-mac-apple-silicon.dmg`) always
gives the newest one.

## Command-line mode

Same code and checks as the app, without a window. Run `Dlr.app/Contents/MacOS/Dlr` with:

| Option | Does |
| --- | --- |
| `--download LINK video\|mp3\|720 [FOLDER]` | Downloads one link and prints the saved file's (or, for a photo post or Spotify album, folder's) path. `DLR_LOGINS=off` turns logins off for that run |
| `--version` | Shows the Dlr, yt-dlp, gallery-dl, FFmpeg and Deno in use |
| `--update-ytdlp` | Updates yt-dlp and gallery-dl, like the Update button |

Dlr also starts itself with `--gallery-dl` (to run gallery-dl in its own process) and `--job`
(to retry a download with a just-updated yt-dlp); these are internal.

## Project structure

| Path | Purpose |
| --- | --- |
| `app.py` | Window (pywebview), the functions the page may call, command-line mode |
| `ui/` | The interface: `index.html`, `style.css`, `app.js` |
| `downloader.py` | Download logic: which engine, formats, checks, retries, Apple-compatible MP4 |
| `gallery.py` | Photo posts, carousels and slideshows with gallery-dl (in its own process) |
| `links.py` | Which site a link is from, share links, tracking parameters |
| `safety.py` | Link, network, file and error-message rules |
| `pgp.py` | Checks yt-dlp's release signature against its pinned key |
| `spotify.py` | Spotify songs, albums and playlists, and the matching YouTube Music songs |
| `config.py` | The settings file |
| `updater.py` | Verified yt-dlp and gallery-dl updates for the packaged app, with fallback |
| `requirements.txt`, `requirements-build.txt` | Python packages, pinned with hashes |
| `build.py` | Builds the app and its disk image |
| `packaging/` | Icons, and `get_ffmpeg.py` and `get_deno.py` (verified tools for the app) |
| `tests/` | Unit tests, and `live_links.py` for real downloads on a Mac |
| `.github/workflows/build.yml` | Builds, tests and publishes the app |
