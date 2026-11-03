<div align="center">

<img src="packaging/icon.png" alt="Dlr" width="120">

# Dlr

**Download videos and audio from YouTube, TikTok, Instagram and 1,000+ other sites.**

[![Latest release](https://img.shields.io/github/v/release/Ziad-cp/Dlr?style=flat-square&color=6d5dfc)](https://github.com/Ziad-cp/Dlr/releases/latest)
[![Build](https://img.shields.io/github/actions/workflow/status/Ziad-cp/Dlr/build.yml?branch=main&style=flat-square&label=build)](https://github.com/Ziad-cp/Dlr/actions/workflows/build.yml)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Android-555?style=flat-square)](#download)
[![License: MIT](https://img.shields.io/badge/license-MIT-555?style=flat-square)](LICENSE)

<img src="docs/screenshot.png" alt="Dlr on macOS" width="720">

</div>

## Download

| Platform | Download | Requires |
| --- | --- | --- |
| **macOS** (Apple Silicon) | [Dlr-mac-apple-silicon.dmg](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-mac-apple-silicon.dmg) | M1 or newer, macOS 12 Monterey or newer |
| **Windows** | [Dlr-windows-setup.exe](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-windows-setup.exe) | Windows 10 or 11 |
| **Android** | [Dlr-android.apk](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-android.apk) | Android 10 or newer |

**Mac: Apple Silicon (M1 or newer) only**, on macOS 12 Monterey or newer (the oldest macOS
the bundled FFmpeg and Deno run on). To check your Mac: Apple menu › **About This Mac** should
say "Chip: Apple M…".

These links always give the newest version. Older 32-bit Android phones:
[Dlr-android-32-bit.apk](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-android-32-bit.apk).
All versions are on the [releases page](https://github.com/Ziad-cp/Dlr/releases).

Everything is included: no extra software to install. On the Mac, the .dmg is the only way
to install Dlr.

### First launch on a Mac

Dlr isn't signed with a paid Apple certificate, so macOS asks you to confirm it once:

1. Open the .dmg and drag **Dlr** into **Applications**.
2. Open Dlr. macOS says it can't check it for malicious software: click **Done**.
3. Open **System Settings › Privacy & Security**, scroll down to **Security**, and click
   **Open Anyway** next to "Dlr was blocked".
4. Enter your Mac password, then click **Open**. From now on Dlr opens normally.

**Windows:** on "Windows protected your PC", click **More info › Run anyway**.
**Android:** allow installing from your browser when asked. If Play Protect warns you,
choose **More details › Install anyway**.

## Features

- **Paste and go.** Copy a link and switch to Dlr: it fills in and looks up the video by itself.
- **Video or MP3.** An MP4 that plays everywhere (including iPhone): H.264 when the site has it
  at that quality, otherwise the best version converted to MP4. Or an MP3 at 320 kbps.
- **Choose a quality.** Only the qualities that video really has.
- **Photo posts too.** TikTok slideshows (all photos, plus the sound as an MP3), Instagram
  photo posts and carousels (every photo and video), Reddit galleries: same Download button,
  saved into one folder per post.
- **Share links.** `vm.tiktok.com`, `instagram.com/share/…`, `reddit.com/r/…/s/…` and `redd.it`
  links are followed to the post first.
- **Spotify songs, albums and playlists.** Each song is matched on YouTube Music and saved as a
  320 kbps MP3 with its title, artist, album and cover art. No Spotify account or key needed.
  (Spotify's public pages list a playlist's first 100 songs.)
- **Queue.** Add several links; they download one after another.
- **Checked files.** Every video is checked for picture and sound. If one version fails,
  another is tried. After a failed download Dlr updates its engines, and if a newer one
  arrived, tries once more with it.
- **Logins only if you want them.** Off by default. If you turn on **Logins from** in Settings
  and a site asks you to log in, Dlr retries once with that browser's login. Cookies are never
  saved.
- **Private.** No account, no history, no logs, no tracking.

### What works where

| | Mac | Windows | Android |
| --- | :-: | :-: | :-: |
| Videos from YouTube, TikTok, Instagram, Reddit, X, Facebook and 1,000+ sites | ✓ | ✓ | ✓ |
| MP3 | ✓ 320 kbps | ✓ 320 kbps | ✓ 192 kbps |
| Pick a quality | ✓ | ✓ | – |
| Photo posts, carousels, slideshows | ✓ | ✓ | – |
| Spotify songs, albums, playlists | ✓ | ✓ | – |
| Logins from your browser | ✓ | ✓ | – |
| Share menu (**Share › Dlr**) | – | – | ✓ |

The Mac and Windows apps share the same code. Downloads from each site are tested on a Mac
(`tests/live_links.py`); the Windows app is built and tested automatically on GitHub.

### Sites that need a login

Some content is only shown to logged-in visitors. Logins are off by default, so Dlr says
"… needs login — turn on logins in settings". To download it, choose a browser under
**Logins from** in Settings and be logged in to the site in that browser:

- **Reddit** now refuses most downloads from people who aren't logged in.
- **Instagram** stories and highlights, and some older single-photo posts.
- Private, age-restricted or "confirm you're not a bot" videos on any site.

## iPhone and iPad

There's no iOS version. Apple only allows apps from the App Store, which doesn't permit video
downloaders, and the other routes (sideloading, alternative stores) expire, cost money or are
limited to some countries. Download on your computer instead: Dlr's MP4s play natively on
iPhone. Send them over AirDrop, or save them to iCloud Drive and use **Save Video** in Files.

## Keeping it working

Sites change often, so Dlr keeps its download engines up to date: on Mac and Windows it updates
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and [gallery-dl](https://github.com/mikf/gallery-dl)
on its own at most once a day, and again after a failed download (at most once an hour; if a
newer version arrived, it tries that download once more). A dot on the Settings icon means a new yt-dlp is waiting for a restart.
**Settings › Update** (or **Update** on Android) does it at any time. Updates come only from
the official releases (yt-dlp from GitHub, gallery-dl from PyPI) and are verified against
their published checksums before use.

## Security and privacy

Dlr treats everything from the internet as untrusted:

- No open network ports; the app runs no web server.
- Links can never reach your computer or local network (SSRF protection).
- Nothing runs through a shell; downloaded files can't overwrite your files.
- Updates and the bundled FFmpeg and Deno are verified against official checksums or signatures.

It stores only your download folder and **Logins from** settings. Details, limits and the full list of network
connections: [SECURITY.md](SECURITY.md).

## Building from source

See [docs/BUILDING.md](docs/BUILDING.md) for running from source, building each app, the test
setup and publishing releases.

## License

[MIT](LICENSE) © 2026 Ziad Gahlan. Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[gallery-dl](https://github.com/mikf/gallery-dl), [FFmpeg](https://ffmpeg.org),
[Deno](https://deno.com) and [pywebview](https://pywebview.flowrl.com/). The released apps
bundle GPL-licensed components (FFmpeg and gallery-dl, and
[youtubedl-android](https://github.com/yausername/youtubedl-android) on Android), so those
binaries are distributed under the GPL v3. License notices ship inside each app.

Only download content you have the right to download. Copy-protected (DRM) services such as
Netflix or Spotify's own audio aren't supported.
