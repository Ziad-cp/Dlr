# Dlr 1.1.0

Dlr is a minimal dark-mode app for downloading videos and MP3s from YouTube, TikTok, Instagram, X,
Reddit, Facebook and [many other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).
Runs on **macOS** (and Windows from source).

Built with [yt-dlp](https://github.com/yt-dlp/yt-dlp) (as a Python library), FFmpeg and
[pywebview](https://pywebview.flowrl.com/). It only downloads: no history, no logs, no
tracking. See [SECURITY.md](SECURITY.md).

![Dlr on macOS](docs/screenshot.png)

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
  - **MP3**: best audio, at the best MP3 quality (variable bitrate, `--audio-quality 0`).
  - H.264 + AAC is preferred when it's as sharp as the best version; otherwise the best
    version is converted after downloading. If no preferred version exists, Dlr falls back to
    the site's single best file.
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
- **Setup check.** If FFmpeg or Deno (needed for YouTube) is missing, Dlr says so at launch with
  the exact command to install it (`brew install ffmpeg`, `brew install deno`).
- **Logins when needed.** If a site says you must be logged in, isn't sure you're not a bot,
  or limits downloads, Dlr retries once using your browser's login (Settings › **Logins from**:
  your default browser, another one, or **Never**). Cookies are read for that download only and
  never copied or saved.
- **⚙ Settings:** download folder, login browser, yt-dlp version and update. A dot on the icon
  means a new yt-dlp is waiting for a restart.

## Install on Mac

1. Install FFmpeg (needed to combine picture and sound): `brew install ffmpeg`
2. Build `Dlr-1.1.0.dmg` (see *Run or build from source* below), open it and drag **Dlr** onto
   **Applications**.
3. Open it from Applications. On a Mac other than the one that built it: right-click › **Open**
   the first time (the app is signed for personal use, not notarized by Apple).

### Run or build from source

```bash
brew install python@3.12 ffmpeg
```

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python app.py
```

Build the app and the DMG (`dist/Dlr.app`, `dist/Dlr-1.1.0.dmg`):

```bash
.venv/bin/python build.py
```

Command-line mode (same code and checks, no window), from `Dlr.app/Contents/MacOS/Dlr`:
`--download LINK video|mp3 [FOLDER]`, `--version`, `--update-ytdlp`

## Updating yt-dlp

Sites change, and yt-dlp keeps up with new releases. Dlr updates it on its own at most once a
day at launch, and again when a download fails (at most once an hour); the new version is used
after a restart. ⚙ Settings › **Update** does the same at any time. The method matches how
yt-dlp was installed:

- **Running from source:** `pip install -U yt-dlp` (or `brew upgrade yt-dlp` if it came from
  Homebrew).
- **The packaged app:** it downloads the newest yt-dlp from
  the official GitHub releases, checks it against the official checksums, and uses it from
  the next launch. The yt-dlp built into the app stays as a fallback: if the update is damaged
  or won't load, Dlr quietly goes back to it. Rebuilding (`pip install -U yt-dlp`, then
  `python build.py`) also updates the built-in copy.

## What it keeps

`~/Library/Application Support/Dlr/` holds `config.json` (your download folder and login
browser) and, after an update, the verified yt-dlp in `yt-dlp/`, plus the times of the last
update checks.
It keeps no history, links, titles, logs or caches. It talks only to the site you download from,
plus GitHub for yt-dlp updates (full list in [SECURITY.md](SECURITY.md)).

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
| `build.py` | Builds the .app and .dmg (macOS) or .exe (Windows) |
| `packaging/` | App icon and the script that draws it |

## Notes

- Only download videos you have the right to download.
- Private videos, videos behind a login, and copy-protected services can't be downloaded.
- Spotify links download the matching public YouTube upload, never Spotify's own audio.

## License

[MIT](LICENSE) © 2026 Ziad Gahlan. Dlr uses [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(Unlicense), [pywebview](https://github.com/r0x0r/pywebview) (BSD) and FFmpeg, each under its
own license.
