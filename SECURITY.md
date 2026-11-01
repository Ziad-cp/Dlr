# Security

Dlr is a personal tool: paste a link, get a video or MP3. This page says what it
protects against, how, and where the limits are.

## Threat model

The app treats everything that comes from the internet as untrusted:

- **Links** you paste or share, which someone else may have crafted.
- **What sites send back**: titles, uploader names, thumbnail addresses, redirects.
- **Downloaded files**, which may not be what they claim to be.
- **Other devices on your network**, and other programs on your computer.

Out of scope: someone who already controls your user account, the sites themselves seeing what
you download from them, and copy-protected (DRM) services, which the app refuses.

## What's protected, and how

**No network listening.** The Mac app opens no network port at all, not even on `127.0.0.1`.
The window loads its page straight from disk. (Checked with `lsof` while idle and downloading.)

**The window's bridge to Python.** The page can call only the functions it needs: `info`,
`fetch`, `add`, `cancel`, `jobs`, `reveal`, `clipboard`, `choose_folder`, `update_ytdlp`,
`update_status`.
Every argument is checked for type, length and allowed values. Errors come back as plain
messages, never Python tracebacks. The clipboard function returns only a valid link found
there, never the rest of the clipboard.

**Links.** Only `http`/`https`, at most 2,048 characters, no control or invisible characters
(including bidi tricks), no `user:password@` logins, and never this computer or the local
network (`localhost`, `127.x`, `10.x`, `192.168.x`, `169.254.x`, `*.local`, IPv6 local
ranges). Names are resolved and checked too. The same checks apply to thumbnails and cover
art, including after redirects, with size caps.

**No shell, ever.** Nothing is run through a shell. yt-dlp is used as a library; FFmpeg and
ffprobe get argument lists with absolute paths. FFmpeg may read only local files
(`-protocol_whitelist file`) and only real audio/video containers, so a "video" that's really
a playlist can't make it open other files or web addresses.

**Files.** Downloads are written only inside the chosen folder:

- Names are cleaned: no folders, no `..`, no hidden files, no reserved Windows names, length
  limited in bytes.
- An existing file is **never overwritten**. A name is claimed with an exclusive create, then
  the finished file replaces only that claim; same name and extension gets " (2)".
- Work happens in a private temporary folder that's deleted after every download, error or cancel.
- Symlinks are never followed or deleted.

**The page.** All text from the internet is inserted with `textContent` or escaped. A strict
Content-Security-Policy allows only the app's own script and styles, images only as inline
data, and no connections, fonts, frames or forms. Files dropped on the window can't replace
the page.
Trade-off: `'unsafe-eval'` is allowed because pywebview's bridge uses `eval`. This is low risk
because the page loads only local files, blocks inline and remote scripts, and escapes all
internet text.

**Code that runs.** yt-dlp plugins (Python code it would otherwise load from folders in your
home) are disabled. Dependencies come only from PyPI and Homebrew, are pinned to exact versions
in `requirements.txt`, and are checked with `pip-audit` (no known vulnerabilities as of 1.0.0).

**FFmpeg in the downloadable apps.** The apps on the Releases page are built by GitHub Actions
(`.github/workflows/build.yml`) and include FFmpeg, fetched by `packaging/get_ffmpeg.py` from
builds that ffmpeg.org links to. The Windows build (BtbN/FFmpeg-Builds on GitHub) must match the
SHA-256 published in that release; the Mac build (Martin Riedl) must carry a valid Apple-issued
code signature and be built for the right chip. Both must run and include the encoders Dlr
uses, or the build stops. The app uses its own FFmpeg before any installed one. Each release
also lists the SHA-256 of every download in `SHA256SUMS.txt`.

## Privacy

- **Saved:** only `config.json`, holding the download folder
  (`~/Library/Application Support/Dlr/` on Mac). No history, links or titles.
- **No logs, no debug output, no caches:** yt-dlp's cache is off, and pip uses no cache.
  WebKit's own (empty) data folders are removed when the app quits and when it starts.
- **Never read:** browser cookies, Keychain, contacts or photos. No cookie or login options exist.
- **Read when you switch to the window:** the clipboard, and only to find a link to fill in.
  Nothing from it is kept.
- **Network connections (complete list):**
  1. The site you download from: its pages, video/audio servers and thumbnails (for example
     `youtube.com`, `*.googlevideo.com`, `i.ytimg.com`; `tiktok.com`, `*.tiktokcdn-eu.com`).
     For Spotify links: `open.spotify.com` for the song's public info, `*.spotifycdn.com`
     for the cover, then YouTube to find and download the song.
  2. DNS lookups for the link's host, from the local-network check.
  3. GitHub, for yt-dlp updates: at most once a day at launch, one request to
     `github.com/yt-dlp/yt-dlp/releases/latest` to see if there's a new version; and when you
     press **Update**, the release files from `github.com` / `*.githubusercontent.com`.
     (Running from source, **Update** uses `pypi.org` and `files.pythonhosted.org` instead.)

  Nothing else: no analytics, telemetry, crash reports or update checks. The window itself makes
  no connections. If Deno is installed, yt-dlp may run it (sandboxed: no network, no files) to
  solve YouTube's signature puzzles; its update check is switched off.

## yt-dlp updates in the packaged app

The app has its own yt-dlp sealed inside. **Update** in Settings replaces it safely:

1. **Source:** only the official releases at `github.com/yt-dlp/yt-dlp`, over HTTPS. Redirects
   are followed only to GitHub's download servers (`*.githubusercontent.com`). Anything else
   stops the update.
2. **Checksum:** the file (`yt-dlp`, yt-dlp's platform-independent Python zip) must match the
   release's official `SHA2-256SUMS`, and the version written inside it must match the release.
   On any mismatch the download is thrown away and the current version stays. (Tested with a
   1-byte change and with a fake carrying a matching checksum but the wrong version.)
3. **Storage:** it's saved atomically to `~/Library/Application Support/Dlr/yt-dlp/` with a small
   manifest (version and SHA-256).
4. **Use:** at the next launch, only if it's newer than the built-in yt-dlp, still matches its
   recorded checksum, and loads cleanly (plugins off). Otherwise the built-in version is used and
   the bad update is deleted. (Tested with a damaged file and with one that fails to load.)
5. **Checks:** at most once a day at launch, the app asks GitHub for the latest version and shows
   a dot on the Settings icon. It never installs anything without your click.

## Known limits

- **Redirects inside yt-dlp:** a public site could still redirect yt-dlp's own requests to a
  local address (or use DNS rebinding). The checks cover the link you paste, thumbnails and
  covers, not yt-dlp's internal redirects.
- **`'unsafe-eval'` in the CSP:** see the trade-off above.
- **Updates trust GitHub:** the checksum comes from the same official release page as the file,
  so it proves the download is intact and is what yt-dlp published there. It doesn't protect
  against GitHub or the yt-dlp project itself being compromised; the release's GPG signature
  isn't checked.
- **Updated code lives in your account:** the update is code the app runs, stored in your
  Library folder. Anyone who can already write there could change it; its checksum is
  re-checked at every launch, which catches damage but not a deliberate change of both files.
- **Ad-hoc signature:** the Mac app is signed "ad hoc", not notarized by Apple, so macOS asks
  you to confirm the first launch (System Settings › Privacy & Security › Open Anyway). The
  Windows installer isn't code-signed either, so SmartScreen shows a warning first.
- **Bundled FFmpeg trusts its builders:** the checks prove the FFmpeg download is intact and
  (on Mac) signed by an Apple-registered developer, not that the builder is trustworthy.
- **Clipboard:** read when the window comes to the front (only a link is used).
- **Windows:** built and tested automatically on GitHub's Windows computers, but less used than
  the Mac app. Settings live in `%APPDATA%\Dlr\`.

## Keeping it safe

Update yt-dlp when sites change (see README), and re-check dependencies now and then:

```bash
pip install pip-audit
```

```bash
pip-audit -r requirements.txt
```
