# Building Dlr

Everything needed to run Dlr from source, build the apps and publish a release.
For downloading and installing Dlr, see the [README](../README.md).

## Contents

- [Run from source](#run-from-source)
- [Build the desktop apps](#build-the-desktop-apps)
- [Build the Android app](#build-the-android-app)
- [Releases](#releases)
- [Command-line mode](#command-line-mode)
- [Project structure](#project-structure)

## Run from source

**macOS, one command.** Installs Homebrew, Python 3.12 and FFmpeg if needed, builds Dlr and
puts it in Applications:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Ziad-cp/Dlr/main/install.sh)"
```

**macOS, manually:**

```bash
brew install python@3.12 ffmpeg
git clone https://github.com/Ziad-cp/Dlr.git && cd Dlr
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

**Windows:** install [Python 3.12](https://www.python.org/downloads/) and FFmpeg
(`winget install Gyan.FFmpeg`), then in the Dlr folder:

```bat
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

## Build the desktop apps

```bash
python packaging/get_ffmpeg.py   # optional: bundle a verified FFmpeg into the app
python build.py
```

| Platform | Output |
| --- | --- |
| macOS | `dist/Dlr.app` and `dist/Dlr-<version>.dmg` |
| Windows | `dist\Dlr\Dlr.exe`, then the installer with [Inno Setup](https://jrsoftware.org/isinfo.php): `iscc /DAppVersion=1.1.0 packaging\windows\dlr.iss` |

PyInstaller can't cross-compile: build the Mac app on a Mac and the Windows app on Windows.

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

## Releases

GitHub Actions builds and tests every app on every push (`.github/workflows/build.yml`):
macOS (Apple silicon and Intel), Windows and Android, including real downloads and an
Android emulator run.

To publish a release:

1. Set `__version__` in `app.py`.
2. On GitHub, open **Releases › Draft a new release**, create the tag `v<version>` and
   publish. Alternatively, push the tag: `git tag v1.1.0 && git push origin v1.1.0`.
3. About 10 minutes later, the apps and `SHA256SUMS.txt` are attached to the release. The
   download links in the README always point to the newest release.

## Command-line mode

Same code and checks as the app, without a window. Run `Dlr.app/Contents/MacOS/Dlr` on macOS
or `Dlr.exe` on Windows with:

| Option | Does |
| --- | --- |
| `--download LINK video\|mp3 [FOLDER]` | Downloads one link and prints the saved file's path |
| `--version` | Shows the Dlr, yt-dlp and FFmpeg in use |
| `--update-ytdlp` | Updates yt-dlp, like the Update button |

## Project structure

| Path | Purpose |
| --- | --- |
| `app.py` | Window (pywebview), the functions the page may call, command-line mode |
| `ui/` | The desktop interface: `index.html`, `style.css`, `app.js` |
| `downloader.py` | Download logic: formats, checks, retry, Apple-compatible MP4 |
| `safety.py` | Link and file rules |
| `spotify.py` | Spotify song info and the matching YouTube upload |
| `config.py` | The settings file |
| `updater.py` | Verified yt-dlp updates for the packaged app, with fallback |
| `build.py` | Builds the macOS app and disk image, or the Windows app folder |
| `install.sh` | One-command macOS install from source |
| `packaging/` | Icons, `get_ffmpeg.py` (verified FFmpeg for the apps), the Windows installer script |
| `android/` | The Android app and its tests |
| `.github/workflows/build.yml` | Builds, tests and publishes all the apps |
