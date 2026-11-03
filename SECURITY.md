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
`fetch`, `add`, `cancel`, `jobs`, `reveal`, `clipboard`, `choose_folder`, `set_browser`,
`update_ytdlp`, `update_status`.
Every argument is checked for type, length and allowed values. Errors come back as plain
messages, never Python tracebacks. The clipboard function returns only a valid link found
there, never the rest of the clipboard.

**Links.** Only `http`/`https`, at most 2,048 characters, no control or invisible characters
(including bidi tricks), no `user:password@` logins, and never this computer or the local
network (`localhost`, `127.x`, `10.x`, `192.168.x`, `169.254.x`, `*.local`, IPv6 local
ranges). Names are resolved and checked too. The same checks apply to thumbnails, cover
art and photos, including after redirects, with size caps. Share links (`vm.tiktok.com`,
`instagram.com/share/…`, `reddit.com/r/…/s/…`, `redd.it`) are followed before downloading, and
every hop of their redirects is checked the same way (at most 5 hops). Tracking parameters
(`igsh`, `utm_…`, TikTok's `_t`/`_d`…) are removed.

**No shell, ever.** Nothing is run through a shell. yt-dlp is used as a library; FFmpeg and
ffprobe get argument lists with absolute paths. FFmpeg may read only local files
(`-protocol_whitelist file`) and only real audio/video containers, so a "video" that's really
a playlist can't make it open other files or web addresses.

gallery-dl (photo posts) runs in a separate process: Dlr starts its own binary with
`--gallery-dl` and an argument list, with `--` right before the link so a link can never be
read as an option. It gets `--config-ignore` (no gallery-dl settings from your home folder) and
a private settings file inside the download's temporary folder: no cache on disk (an in-memory
database), no download archive, no post-processors, no log or "unsupported" files. Its output
is read in memory only. The same goes for `--job`, which Dlr uses to retry a failed download
with a just-updated yt-dlp: the request goes in as JSON on stdin, never on a command line.

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
home) are disabled, also inside the gallery-dl process. Python dependencies come only from PyPI,
are pinned to exact versions in `requirements.txt`, and are checked with `pip-audit`.

**Deno in the downloadable apps.** yt-dlp needs a JavaScript runtime to solve YouTube's
challenges. The apps include Deno, fetched by `packaging/get_deno.py` from the official releases
at `github.com/denoland/deno` for each chip. It must match the SHA-256 published with that
release, and on a Mac also carry a valid Apple-issued code signature and be built for the right
chip; it must run and be Deno 2 or newer, or the build stops. The app uses only its own Deno.
yt-dlp runs it without network or file access; its update check and prompts are off, and its
cache goes to a temporary folder that's deleted when Dlr quits, however it quits (including ⌘Q).

**FFmpeg in the downloadable apps.** The apps on the Releases page are built by GitHub Actions
(`.github/workflows/build.yml`) and include FFmpeg, fetched by `packaging/get_ffmpeg.py` from
builds that ffmpeg.org links to. The Windows build (BtbN/FFmpeg-Builds on GitHub) must match the
SHA-256 published in that release; the Mac build (Martin Riedl) must carry a valid Apple-issued
code signature and be built for the right chip. Both must run and include the encoders Dlr
uses, or the build stops. The app uses its own FFmpeg before any installed one. Each release
also lists the SHA-256 of every download in `SHA256SUMS.txt`.

## Privacy

- **Saved:** only `config.json`, holding the download folder and the **Logins from** setting
  (`~/Library/Application Support/Dlr/` on Mac). No history, links, titles or cookies.
- **No logs, no debug output, no caches:** yt-dlp's cache is off, and pip uses no cache.
  WebKit's own (empty) data folders are removed when the app quits, however it quits (closing
  the window, ⌘Q, Dock › Quit, logging out), and again when it starts.
- **Browser logins, only when a site asks for one:** if a site answers "log in", "not a bot",
  "private" or "too many requests", the download is retried once with yt-dlp's
  `cookiesfrombrowser`, using the browser chosen in Settings › **Logins from**. This is
  **off by default** (**Never**): until you choose a browser, Dlr never reads any cookies and
  tells you when something needs a login. yt-dlp reads the cookies straight from the browser
  into memory for that one download; Dlr never copies, saves or logs them, and they're sent only
  to the sites they belong to. macOS asks first: Keychain access for Chrome-based browsers, Full
  Disk Access for Safari.
- **Never read:** contacts or photos.
- **Read when you switch to the window:** the clipboard, and only to find a link to fill in.
  A link that was already there when Dlr opened is never filled in, so every launch starts
  with an empty link field. Nothing from it is kept.
- **Network connections (complete list):**
  1. The site you download from: its pages, video/audio servers and thumbnails (for example
     `youtube.com`, `*.googlevideo.com`, `i.ytimg.com`; `tiktok.com`, `*.tiktokcdn-eu.com`).
     For Spotify links: `open.spotify.com` for the public info of the song, album or playlist
     (its embed pages: no account or key), `*.spotifycdn.com` for covers, then YouTube Music
     and YouTube to find and download each song.
  2. DNS lookups for the link's host, from the local-network check, and for share links, each
     address they redirect to.
  3. GitHub, for yt-dlp updates: at most once a day at launch, after a failed download (at most
     once an hour), and when you press **Update**: `github.com/yt-dlp/yt-dlp/releases/latest`,
     then the release files from `github.com` / `*.githubusercontent.com` if there's a new one.
     (Running from source, updates use `pypi.org` and `files.pythonhosted.org`, or Homebrew's
     servers if yt-dlp came from `brew`.)
  4. PyPI, for gallery-dl updates, at the same times: `pypi.org/pypi/gallery-dl/json`, then the
     release file from `files.pythonhosted.org` if there's a new one.

  Nothing else: no analytics, telemetry, crash reports or update checks. The window itself makes
  no connections. Deno (run by yt-dlp for YouTube) has no network access.

## yt-dlp updates in the packaged app

The app has its own yt-dlp sealed inside. Updates replace it safely:

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
5. **When:** on its own at most once a day at launch, and after a failed download (at most once
   an hour), since a failure often means the site changed; or when you press **Update**. A dot on
   the Settings icon shows a new version waiting for a restart.

## gallery-dl updates in the packaged app

gallery-dl is updated the same way as yt-dlp, from its official releases on PyPI (its GitHub
releases have no files attached):

1. **Source:** `pypi.org` and `files.pythonhosted.org` only, over HTTPS, with redirects allowed
   only between them.
2. **Checksum:** the release's `.whl` file must match the SHA-256 PyPI lists for it, and the
   version written inside it must match the release, or it's thrown away.
3. **Storage:** saved atomically to `~/Library/Application Support/Dlr/gallery-dl/` with a
   manifest.
4. **Use:** gallery-dl always runs in its own process, which uses the update only if it's newer
   than the built-in gallery-dl, still matches its checksum and loads cleanly. So a new version
   is used at once, with no restart.

## Android app

The Android app (`android/`) follows the same rules as the desktop app:

- **Links:** `LinkCheck.java` applies the same checks as `safety.py` (web links only, length,
  hidden characters, no logins in the link, never this phone or the local network, names
  resolved and checked), with unit tests for each case.
- **One permission:** internet. Saving to Downloads › Dlr uses Android's MediaStore, which needs
  no storage permission. No contacts, camera, location or other data.
- **No shell:** yt-dlp runs as a program with an argument list (youtubedl-android's
  `ProcessBuilder`), never through a shell. Plugins and config files are off
  (`--no-plugin-dirs`, `--ignore-config`) and yt-dlp's cache is off.
- **Files:** downloads happen in a private folder in the app's cache, which is deleted after
  every download, error or stop (and at the next start if the app was closed). Only the
  finished file is copied to Downloads; Android never overwrites, it adds " (1)" to a name.
- **yt-dlp updates:** at most once a day, or with **Update**. Only from
  `github.com/yt-dlp/yt-dlp/releases/latest` over HTTPS, following redirects only to GitHub's
  download servers, and only if the file matches the release's official `SHA2-256SUMS` and
  is a real yt-dlp release (its version is read from inside it). Each APK also comes with the
  newest yt-dlp, checked the same way when it's built.
- **Privacy:** no history, logs or analytics; app data is excluded from backups and device
  transfers.
- **Network connections:** the site you download from, DNS for the link check, and GitHub for
  yt-dlp updates.

Limits: the APK is signed with the project's key only if the signing secrets are set up
(see README); otherwise each build has its own key. Downloads are an Android process that keeps
running while Dlr is open; if you leave the app, Android may stop a long download.

## Known limits

- **Redirects inside yt-dlp and gallery-dl:** a public site could still redirect their own
  requests to a local address (or use DNS rebinding). The checks cover the link you paste, share
  links, thumbnails, covers and photos Dlr fetches itself, not the engines' internal redirects.
- **Impersonation:** for TikTok, yt-dlp's `--impersonate` (curl_cffi) makes its requests look
  like a normal browser's, because TikTok refuses plain ones.
- **`'unsafe-eval'` in the CSP:** see the trade-off above.
- **Updates trust GitHub and PyPI:** the checksum comes from the same official release page as the file,
  so it proves the download is intact and is what yt-dlp published there. It doesn't protect
  against GitHub or the yt-dlp project itself being compromised; the release's GPG signature
  isn't checked.
- **Updated code lives in your account:** the update is code the app runs, stored in your
  Library folder. Anyone who can already write there could change it; its checksum is
  re-checked at every launch, which catches damage but not a deliberate change of both files.
- **Ad-hoc signature:** the Mac app is signed "ad hoc", not notarized by Apple, so macOS asks
  you to confirm the first launch (System Settings › Privacy & Security › Open Anyway). The
  Windows installer isn't code-signed either, so SmartScreen shows a warning first.
- **Bundled FFmpeg and Deno trust their builders:** the checks prove the downloads are intact
  and (on Mac) signed by an Apple-registered developer, not that the builder is trustworthy.
- **Clipboard:** read when the window comes to the front (only a link copied since Dlr opened
  is used).
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
