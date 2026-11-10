<div align="center">

<img src="packaging/icon.png" alt="" width="96">

# Dlr

**A video and MP3 downloader for Apple Silicon Macs, built on yt-dlp.**

[![Latest release](https://img.shields.io/github/v/release/Ziad-cp/Dlr?style=flat-square&color=6d5dfc)](https://github.com/Ziad-cp/Dlr/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-555?style=flat-square)](LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/Ziad-cp/Dlr/build.yml?branch=main&style=flat-square&label=build)](https://github.com/Ziad-cp/Dlr/actions/workflows/build.yml)
[![macOS Apple Silicon](https://img.shields.io/badge/macOS%2012%2B-Apple%20Silicon-555?style=flat-square&logo=apple)](#download--install)

</div>

## Demo

<p align="center"><img src="docs/demo.gif" alt="Downloading Dlr from GitHub, installing it, and saving a video with it" width="860"></p>

<p align="center"><a href="docs/demo.mp4">Watch full demo (MP4)</a></p>

## What it is

Dlr is a small Mac app: paste a link, get an MP4 that plays everywhere, or a 320 kbps MP3. It wraps
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and [gallery-dl](https://github.com/mikf/gallery-dl) in a
native window, ships everything they need, and treats every link, page and file from the internet as
untrusted.

## Features

- **Paste and go.** Copy a link and switch to Dlr: it fills it in and looks it up.
- **Video or MP3.** H.264 MP4 when the site has it at full quality, otherwise the best version converted;
  every file is checked for picture and sound.
- **Real qualities only.** Pick from the resolutions the video actually has.
- **Photo posts.** Slideshows, carousels and galleries are saved as one folder per post.
- **Spotify.** Songs, albums and playlists, matched on YouTube Music and saved as tagged MP3s.
- **Self-updating engines.** yt-dlp and gallery-dl update themselves from their official releases,
  verified before use.
- **Private.** No account, no history, no logs, no telemetry. Browser logins are off unless you turn
  them on.

## Supported sites

| Site | What works | Login needed |
| --- | --- | --- |
| YouTube | Videos (choose a quality), MP3 | Only for private, age-restricted or "not a bot" videos |
| TikTok | Videos without watermark, photo slideshows with sound, share links | No |
| Instagram | Reels, video posts, share links | For photo posts, carousels and stories |
| Reddit | Videos with sound, galleries, share links | Yes: Reddit refuses most logged-out downloads |
| X | Videos | No |
| Facebook | Public videos | No |
| Pinterest | Video and image pins | No |
| Spotify | Songs, albums, playlists (first 100 songs) as MP3 | No |
| 1,000+ others | Anything [yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) | Depends on the site |

Logins are read from the browser you choose in **Settings › Logins from**, only when a site asks for one.

## Download & install

Requires a Mac with Apple Silicon (M1 or newer) and macOS 12 Monterey or newer.

1. Download **[Dlr-mac-apple-silicon.dmg](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-mac-apple-silicon.dmg)**.
2. Open it and drag **Dlr** into **Applications**.
3. Open Dlr. It isn't notarized by Apple, so the first time macOS says it can't check it: click
   **Done**, open **System Settings › Privacy & Security**, click **Open Anyway** next to "Dlr was
   blocked", and confirm. After that it opens normally.

yt-dlp, gallery-dl, FFmpeg and Deno are included. Nothing else to install.

## Verify your download

SHA-256 of Dlr 1.2.1 (also in the release notes and in
[Dlr-mac-apple-silicon.dmg.sha256](https://github.com/Ziad-cp/Dlr/releases/latest/download/Dlr-mac-apple-silicon.dmg.sha256)):

```
d20482eed54dc73482d6cb4e54d99d429e6a111585f8b0fb4792321647f3af77
```

```bash
shasum -a 256 ~/Downloads/Dlr-mac-apple-silicon.dmg
```

## Usage

1. Copy a link to a video, post, song or playlist.
2. Switch to Dlr. The link is filled in and a preview card appears.
3. Click **Download Video** (click it again while it runs to stop and pick another quality) or **MP3**.
4. Click **Show in Finder** when it's done.

Files are saved to your **Downloads** folder; change it in **Settings › Save downloads to**. Existing
files are never overwritten.

## Security

- **Signed engine updates.** yt-dlp updates must carry a valid signature from yt-dlp's release key,
  pinned in the app and checked strictly; gallery-dl updates must match PyPI's SHA-256.
- **Pinned tools.** FFmpeg 9.0.2 and Deno 2.9.8 are pinned to exact files, SHA-256s and their makers'
  Apple Developer IDs. FFmpeg is Martin Riedl's notarized third-party build, not an ffmpeg.org binary.
  Python packages are pinned with hashes.
- **Local-network block.** Links, redirects and every connection made from Python can't reach your Mac
  or local network, including DNS rebinding.
- **Restricted page bridge.** The window can call 11 checked functions by exact name; none runs a
  command or chooses where files go. Text from sites is never inserted as HTML.
- **Files and errors.** Names from titles can't escape the download folder; errors never show file
  paths or cookies.

Known limits: TikTok requests (made with curl_cffi) and streams yt-dlp hands to FFmpeg don't go
through the local-network check; the app is signed ad hoc, not notarized. Details, the full list of
network connections and all limits: [SECURITY.md](SECURITY.md).

## Building from source

Python 3.12 on an Apple Silicon Mac; see [docs/BUILDING.md](docs/BUILDING.md).

## Legal

Only download content you have the right to download, and respect each site's terms of service.
Copy-protected (DRM) services such as Netflix, or Spotify's own audio, aren't supported.

## License

Dlr's source code is under the [MIT License](LICENSE). The released app bundles GPL-licensed
components (FFmpeg and gallery-dl), so the app as distributed is covered by the GPL v3; their
license notices ship inside the app.
