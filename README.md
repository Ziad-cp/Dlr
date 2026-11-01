# Dlr 1.1.0

Dlr is a minimal dark-mode app for downloading videos and MP3s from YouTube, TikTok, Instagram, X,
Reddit, Facebook and [many other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).
Works on **Windows**, **Mac** and **Android**. Free, and everything it needs is included.
(iPhone: [see below](#iphone-and-ipad).)

Built with [yt-dlp](https://github.com/yt-dlp/yt-dlp) (as a Python library), FFmpeg and
[pywebview](https://pywebview.flowrl.com/). It only downloads: no history, no logs, no
tracking. See [SECURITY.md](SECURITY.md).

![Dlr on macOS](docs/screenshot.png)

## Download and install

**1. Tap or click the download for your device:**

| Your device | Download |
| --- | --- |
| **Windows 10 or 11** | [⬇ **Download for Windows**](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-Windows-Setup.exe) |
| **Mac with an Apple chip** (M1, M2, M3, M4…, most Macs from 2021 on) | [⬇ **Download for Mac (Apple chip)**](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-Mac-Apple-Silicon.dmg) |
| **Mac with an Intel chip** (older Macs) | [⬇ **Download for Mac (Intel)**](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-Mac-Intel.dmg) |
| **Android phone or tablet** (Android 10 or newer) | [⬇ **Download for Android**](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-Android.apk) |
| **iPhone or iPad** | No app, sorry: Apple doesn't allow it. [What you can do instead](#iphone-and-ipad) |

*Not sure which Mac you have?* Click the Apple menu (top-left corner of the screen) ›
**About This Mac**. If it says **Chip: Apple M…**, you have an Apple chip. If it says
**Processor: … Intel**, you have an Intel chip.

**2. Install it:**

<details open>
<summary><b>On Windows</b></summary>

1. Open your **Downloads** folder and double-click **Dlr-Windows-Setup.exe**.
2. Windows may show a blue box saying **"Windows protected your PC"**. This appears for apps
   from small developers that haven't paid for a Microsoft certificate. Click **More info**,
   then **Run anyway**.
3. Click **Install**, then **Finish**. No password is needed.
4. Dlr opens by itself. Next time, find it in the **Start menu** or on your **desktop**.

</details>

<details open>
<summary><b>On Mac</b></summary>

1. Open your **Downloads** folder and double-click the Dlr file you downloaded (it ends in `.dmg`).
2. A window opens: drag the **Dlr** icon onto the **Applications** folder next to it.
3. Open **Applications** and double-click **Dlr**.
4. **The first time only**, your Mac says it can't check Dlr ("Apple could not verify…").
   This appears for apps from developers who haven't paid for an Apple certificate. Click
   **Done**, then:
   - Open **System Settings** (Apple menu › System Settings) › **Privacy & Security**.
   - Scroll down to the message about Dlr and click **Open Anyway**, then **Open Anyway**
     again and enter your Mac password.
5. After that, Dlr opens normally, like any other app.

</details>

<details open>
<summary><b>On Android</b></summary>

<img src="docs/screenshot-android.png" alt="Dlr on Android" width="240" align="right">

1. On your phone, tap **Download for Android** above. If your browser asks, tap **Download**
   (or **Download anyway**).
2. When it's done, tap **Open** (or find **Dlr-Android.apk** in the **Files** app ›
   **Downloads** and tap it).
3. The first time, Android asks for permission to install apps from your browser. Tap
   **Settings**, turn on **Allow from this source**, then go back.
4. Tap **Install**. If **Google Play Protect** shows a warning, tap **More details** ›
   **Install anyway**. It appears for apps that don't come from the Play Store.
5. Tap **Open**. Dlr is now on your home screen or in your app list, like any other app.

If Android says **"App not installed"** or **"not compatible"**, your phone is an older 32-bit
model: use [the 32-bit version](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-Android-32-bit.apk) instead.
<br clear="right">

</details>

**3. Use it:**

- **Computer:** copy a video's link (from YouTube, TikTok, Instagram…), switch to Dlr (the link
  fills in by itself) and click **Download Video** or **MP3**. Files go to your **Downloads** folder.
- **Android:** in YouTube, TikTok, Instagram or your browser, tap **Share** › **Dlr**, then tap
  **Download Video** or **MP3**. (Or copy the link and open Dlr: it fills in by itself.) Keep
  Dlr open until it says **Saved**. Files go to **Downloads › Dlr**, and videos also show up
  in your gallery app.

**Uninstall:** on Windows, Settings › Apps › **Dlr** › Uninstall. On Mac, drag **Dlr** from
Applications to the Trash. On Android, press and hold the Dlr icon › **Uninstall**.

**Update:** download and install the newest version the same way. Dlr keeps your settings.
(Android: if it says the app **conflicts** with the one you have, uninstall the old Dlr first.)

### iPhone and iPad

There's no Dlr for iPhone or iPad. Apple only lets you install apps from the App Store, and
the App Store doesn't allow apps that download videos from YouTube and similar sites.

What you can do instead: download on a computer with Dlr, then send the file to your iPhone.
Dlr's videos are made to play on iPhone (in Photos and every video app).

- **From a Mac:** right-click the video in Finder › **Share** › **AirDrop** › your iPhone.
  It appears in **Photos**.
- **From Windows:** put the file in **iCloud Drive** (with
  [iCloud for Windows](https://apps.microsoft.com/detail/9pktq5699m62)), Google Drive or
  OneDrive. On your iPhone, open it in the **Files** app (or the Drive app), tap
  **Share** › **Save Video**, and it appears in **Photos**.

## Security highlights

I built Dlr as a cybersecurity student, so every input from the internet is treated as untrusted.
The full threat model and its limits are in [SECURITY.md](SECURITY.md). In short:

- **No open ports.** The Mac app runs no web server, not even on `127.0.0.1`.
- **SSRF protection.** Links, thumbnails and redirects can never point at this computer or the
  local network; host names are resolved and checked before connecting.
- **No command injection.** Nothing runs through a shell; FFmpeg only gets argument lists and may
  read local files only.
- **XSS protection.** A strict Content-Security-Policy, and every title or name from a site is escaped.
- **Safe file names.** No path traversal, no overwriting existing files.
- **Verified updates.** New yt-dlp versions come only from the official GitHub releases and must
  match the official SHA-256 checksums, with automatic fallback.
- **Privacy.** No logs, no download history, no tracking.

## Features

- **Paste a link.** It's looked up automatically; a link on the clipboard is filled in when you
  switch to the app.
- **Glow colour.** The field's glow takes on the site's colour.
- **The card:** thumbnail, title, duration, site and quality badges, with two buttons:
  - **Download Video**: the highest quality, as an MP4 that plays in QuickTime, Photos and on
    iPhone (H.264/HEVC + AAC, metadata removed, constant frame rate up to 60 fps).
  - **MP3**: best audio, 192 kbps.
- **Pick a quality.** Tap **Download Video** again while it runs to stop it and choose one.
- **Checked files.** Every file is checked for picture and sound, with one automatic retry.
- **Queue.** Several downloads run one after another.
- **Spotify songs:** Spotify's own audio is copy-protected (DRM) and Dlr never touches it. For a
  Spotify song link, Dlr reads the song's public info (title, artist, length, cover), finds the
  same song's public upload on YouTube, downloads that, and tags the MP3 with Spotify's title,
  artist and cover art. Live versions, covers and remixes are skipped unless the Spotify title
  says so. Only single songs, no albums or playlists.
- **Clear errors.** Plain messages for private videos, logins, copy-protected services (Netflix,
  Disney+, Apple Music…), and links to your own network.
- **⚙ Settings:** download folder, yt-dlp version and update. A dot on the icon means a new
  yt-dlp is available (checked at most once a day; it never updates on its own).

## Build it yourself (for developers)

**Mac, one command:** this installs Homebrew, Python 3.12 and FFmpeg if needed, builds Dlr
on your Mac and puts it in Applications (no security warning, since your Mac built it):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Ziad-cp/Dlr/main/install.sh)"
```

<details>
<summary><b>Manual steps, Windows, and how releases are made</b></summary>

**Run from source (Mac):**

```bash
brew install python@3.12 ffmpeg
git clone https://github.com/Ziad-cp/Dlr.git && cd Dlr
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

**Run from source (Windows):** install [Python 3.12](https://www.python.org/downloads/) and
FFmpeg (`winget install Gyan.FFmpeg`), then in the Dlr folder:

```bat
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

**Build the app:** `python build.py` makes `dist/Dlr.app` and `dist/Dlr-1.1.0.dmg` on a Mac,
or `dist\Dlr\Dlr.exe` on Windows. Run `python packaging/get_ffmpeg.py` first to include FFmpeg
in the app. On Windows, [Inno Setup](https://jrsoftware.org/isinfo.php) then makes the
installer: `iscc /DAppVersion=1.1.0 packaging\windows\dlr.iss`.

**Android:** the app is in `android/` (Java, using
[youtubedl-android](https://github.com/yausername/youtubedl-android) for yt-dlp, Python and
FFmpeg). With JDK 17, Gradle 8.11+ and the Android SDK (or Android Studio): put the newest
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp/releases/latest) file at
`android/app/src/main/res/raw/ytdlp`, then `gradle -p android assembleRelease`. Tests:
`gradle -p android testDebugUnitTest` and, with a phone or emulator connected,
`connectedDebugAndroidTest -PuniversalApk`. To sign releases with your own key (so updates
install over older versions), add the repository secrets `DLR_KEYSTORE_BASE64` (the keystore
file, base64), `DLR_KEYSTORE_PASSWORD`, `DLR_KEY_ALIAS` and `DLR_KEY_PASSWORD`.

**Releases:** GitHub builds and tests the Mac, Windows and Android apps on every push
(`.github/workflows/build.yml`). To publish a release, set `__version__` in `app.py`, then
push a matching tag. The download links above always point to the newest release:

```bash
git tag v1.1.0 && git push origin v1.1.0
```

**Command-line mode** (same code and checks, no window), from `Dlr.app/Contents/MacOS/Dlr` or
`Dlr.exe`: `--download LINK video|mp3 [FOLDER]`, `--version`, `--update-ytdlp`

</details>

## When downloads stop working

Sites change often. Open **⚙ Settings** in Dlr and click **Update**, then close and reopen Dlr.
A dot on the ⚙ icon means an update is available.

<details>
<summary>How the update works</summary>

Dlr downloads the newest yt-dlp (the part that knows how each site works) from its official
GitHub releases, checks it against the official checksums, and uses it from the next launch.
The yt-dlp built into the app stays as a fallback: if the update is damaged or won't load, Dlr
quietly goes back to it. Running from source, **Update** uses `pip install -U yt-dlp` instead.

</details>

## What it keeps

`~/Library/Application Support/Dlr/` on Mac, or `%APPDATA%\Dlr\` on Windows, holds `config.json` (your download folder) and, after an
update, the verified yt-dlp in `yt-dlp/`, plus the date of the last update check.
It keeps no history, links, titles, logs or caches. It talks only to the site you download from,
plus GitHub for yt-dlp updates (full list in [SECURITY.md](SECURITY.md)).

On Android, Dlr keeps only its download engine and the date of the last update check inside
the app, and saves your videos and MP3s in Downloads › Dlr. Nothing is backed up or shared.

## Files

| File | What it does |
| --- | --- |
| `app.py` | Window (pywebview), the functions the page may call, command-line mode |
| `ui/` | The interface: `index.html`, `style.css`, `app.js` |
| `downloader.py` | Download logic: formats, checks, retry, Apple-compatible MP4 |
| `safety.py` | Link and file rules |
| `spotify.py` | Spotify song info and the matching YouTube upload |
| `config.py` | The settings file |
| `updater.py` | Verified yt-dlp updates from GitHub for the packaged app, with fallback |
| `build.py` | Builds the .app and .dmg (macOS) or the app folder (Windows) |
| `install.sh` | One-command Mac install from source: builds Dlr and puts it in Applications |
| `packaging/` | App icons, the script that draws them, `get_ffmpeg.py` (fetches a checked FFmpeg for the app) and the Windows installer script |
| `android/` | The Android app: `MainActivity.java` (the screen), `Engine.java` (downloads, saving, yt-dlp updates), `LinkCheck.java` (the same link rules as `safety.py`), and tests |
| `.github/workflows/build.yml` | Builds, tests and publishes the Mac, Windows and Android downloads |

## Notes

- Only download videos you have the right to download.
- Private videos, videos behind a login, and copy-protected services can't be downloaded.
- Spotify links download the matching public YouTube upload, never Spotify's own audio.

## License

[MIT](LICENSE) © 2026 Ziad Gahlan. Dlr uses [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(Unlicense), [pywebview](https://github.com/r0x0r/pywebview) (BSD) and [FFmpeg](https://ffmpeg.org),
each under its own license. The downloadable apps include an FFmpeg build licensed under the
GPL v3; its notice and source details ship inside the app (`FFmpeg-NOTICE.txt` on Mac,
`_internal\ffmpeg\NOTICE.txt` on Windows). The Android app uses
[youtubedl-android](https://github.com/yausername/youtubedl-android) (GPL v3), so the Android
APK as a whole is distributed under the GPL v3; Dlr's own code stays MIT.
