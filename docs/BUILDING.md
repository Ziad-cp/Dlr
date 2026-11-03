# Building Dlr

Everything needed to run Dlr from source, build the apps and publish a release. This is for
developers: people who just want Dlr install it from the .dmg (Mac), the setup .exe (Windows) or
the .apk (Android), see the [README](../README.md).

## Contents

- [Run from source](#run-from-source)
- [Build the desktop apps](#build-the-desktop-apps)
- [Build the Android app](#build-the-android-app)
- [Tests](#tests)
- [Releases](#releases)
- [Command-line mode](#command-line-mode)
- [Project structure](#project-structure)

## Run from source

**Mac: Apple Silicon (M1 or newer) only.** The Mac app runs on macOS 12 Monterey or newer
(the oldest macOS the bundled FFmpeg and Deno support), and is built and run from source on an
Apple-chip Mac; `build.py`, `get_ffmpeg.py` and `get_deno.py` stop on any other Mac.

**macOS** (Python 3.12 from [python.org](https://www.python.org/downloads/) or elsewhere):

```bash
git clone https://github.com/Ziad-cp/Dlr.git && cd Dlr
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python packaging/get_ffmpeg.py && .venv/bin/python packaging/get_deno.py
.venv/bin/python app.py
```

**Windows:** install [Python 3.12](https://www.python.org/downloads/), then in the Dlr folder:

```bat
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python packaging\get_ffmpeg.py
.venv\Scripts\python packaging\get_deno.py
.venv\Scripts\python app.py
```

Running from source, Dlr uses `packaging/ffmpeg/` and `packaging/deno/` (or an FFmpeg and Deno
it finds on the computer); yt-dlp, gallery-dl and curl_cffi come from `requirements.txt`.

## Build the desktop apps

```bash
python packaging/get_ffmpeg.py   # bundle a verified FFmpeg into the app
python packaging/get_deno.py     # bundle a verified Deno (YouTube's challenges)
python build.py
```

`get_deno.py` takes the newest release from github.com/denoland/deno for this computer's chip,
checks it against the SHA-256 published with it and (on a Mac) its Apple code signature, and
stops on any mismatch. The app uses only its own Deno, never one installed on the computer.

| Platform | Output |
| --- | --- |
| macOS | `dist/Dlr.app` and `dist/Dlr-<version>.dmg` (the workflow renames it `Dlr-mac-apple-silicon.dmg`) |
| Windows | `dist\Dlr\Dlr.exe`, then the installer `Dlr-windows-setup.exe` with [Inno Setup](https://jrsoftware.org/isinfo.php): `iscc /DAppVersion=1.1.0 packaging\windows\dlr.iss` |

PyInstaller can't cross-compile: build the Mac app on an Apple-chip Mac and the Windows app on
Windows.

The Mac app's `Info.plist` sets `LSMinimumSystemVersion` to 12.0 (`MIN_MACOS` in `build.py`).
After building, `build.py` checks every program and library in the app with `vtool`. If any
needs a newer macOS, the GitHub build stops; a local build only warns, because it is just for
that Mac (Homebrew's Python, for example, is built for the newest macOS only). Build release
apps with Python from python.org, as GitHub does.

## Build the Android app

The app lives in `android/` (Java, using
[youtubedl-android](https://github.com/yausername/youtubedl-android) for yt-dlp, Python and
FFmpeg). Requirements: JDK 17, Gradle 8.11+ and the Android SDK, or Android Studio.

1. Put the newest [`yt-dlp`](https://github.com/yt-dlp/yt-dlp/releases/latest) release file at
   `android/app/src/main/res/raw/ytdlp`.
2. Build and test:

```bash
gradle -p android assembleRelease
gradle -p android testDebugUnitTest
gradle -p android connectedDebugAndroidTest -PuniversalApk   # with a phone or emulator connected
```

**Signing.** To sign releases with your own key, so updates install over older versions, add
these repository secrets: `DLR_KEYSTORE_BASE64` (the keystore file, base64-encoded),
`DLR_KEYSTORE_PASSWORD`, `DLR_KEY_ALIAS` and `DLR_KEY_PASSWORD`. Without them, each build is
signed with a temporary key.

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

GitHub Actions builds and tests every app on every push (`.github/workflows/build.yml`):
macOS (Apple Silicon only), Windows and Android, including real downloads and an
Android emulator run.

To publish a release:

1. Set `__version__` in `app.py`.
2. On GitHub, open **Releases › Draft a new release**, create the tag `v<version>` and
   publish. Alternatively, push the tag: `git tag v1.1.0 && git push origin v1.1.0`.
3. About 10 minutes later, the apps and `SHA256SUMS.txt` are attached to the release.

The file names are the same for every version, so the README's links
(`https://github.com/Ziad-cp/Dlr/releases/latest/download/<file>`) always give the newest one:
`Dlr-mac-apple-silicon.dmg`, `Dlr-windows-setup.exe`, `Dlr-android.apk`
and `Dlr-android-32-bit.apk`.

## Command-line mode

Same code and checks as the app, without a window. Run `Dlr.app/Contents/MacOS/Dlr` on macOS
or `Dlr.exe` on Windows with:

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
| `ui/` | The desktop interface: `index.html`, `style.css`, `app.js` |
| `downloader.py` | Download logic: which engine, formats, checks, retries, Apple-compatible MP4 |
| `gallery.py` | Photo posts, carousels and slideshows with gallery-dl (in its own process) |
| `links.py` | Which site a link is from, share links, tracking parameters |
| `safety.py` | Link and file rules |
| `spotify.py` | Spotify songs, albums and playlists, and the matching YouTube Music songs |
| `config.py` | The settings file |
| `updater.py` | Verified yt-dlp and gallery-dl updates for the packaged app, with fallback |
| `build.py` | Builds the macOS app and disk image, or the Windows app folder |
| `packaging/` | Icons, `get_ffmpeg.py` and `get_deno.py` (verified tools for the apps), the Windows installer script |
| `tests/` | Unit tests, and `live_links.py` for real downloads on a Mac |
| `android/` | The Android app and its tests |
| `.github/workflows/build.yml` | Builds, tests and publishes all the apps |
