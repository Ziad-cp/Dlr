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
`update_ytdlp`, `update_status`. They're registered one by one, by exact name
(`window.expose`); no Python object is handed to the page. (pywebview looks up a name like
`a.b.c` with `getattr`, including names starting with `_`, so handing it an object would let
the page reach that object's private parts.)
Every argument is checked for type, length and allowed values. Errors come back as plain
messages, never Python tracebacks. The clipboard function returns only a valid link found
there, never the rest of the clipboard. None of these functions runs a command (Finder and
the clipboard are used through macOS itself) or lets the page choose where a file goes:
downloads go only into the folder picked in the system's own folder window, and the only
other files written are Dlr's settings and its verified engine updates, at fixed places in
`~/Library/Application Support/Dlr/`.

**Links.** Only `http`/`https`, never anything starting with `-` (which a command-line tool
could read as an option), at most 2,048 characters, no control or invisible characters
(including bidi tricks), no `user:password@` logins, and never this computer or the local
network (`localhost`, `127.x`, `10.x`, `192.168.x`, `169.254.x`, `*.local`, IPv6 local
ranges). Names are resolved and checked too. The same checks apply to thumbnails, cover
art and photos Dlr fetches itself: every redirect hop is checked before it's followed (at
most 5), cookies and logins are never sent along, and they're size-capped (8 MB for
thumbnails and covers, 200 MB for a photo, refused up front when the site announces more)
and limited to 40 million pixels, checked before an image is decoded.

**Every connection, not just the link.** Dlr also checks addresses when a connection is
made: any name that resolves to this computer or the local network is refused right then,
for all of Dlr's own Python code, yt-dlp and gallery-dl. So a site can't send their requests
to a local address with a redirect, and a name that points somewhere else the second time
it's looked up (DNS rebinding) doesn't help either. A proxy set up on the Mac stays usable. Share links (`vm.tiktok.com`,
`instagram.com/share/…`, `reddit.com/r/…/s/…`, `redd.it`) are followed before downloading, and
every hop of their redirects is checked the same way (at most 5 hops). Tracking parameters
(`igsh`, `utm_…`, TikTok's `_t`/`_d`…) are removed.

**No shell, ever.** Nothing is run through a shell, and no command line is built from text.
yt-dlp is used as a library (so a link is never parsed as an option); FFmpeg and ffprobe get
argument lists with absolute paths. FFmpeg may read only local files
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

- Names come from titles and other metadata, so they're cleaned: no folders, no `..`, no
  hidden files, no control or bidi characters, length limited in bytes; extensions may only
  be letters and digits.
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
are pinned to exact versions in `requirements.txt` together with the SHA-256 of every file pip
may use, and are installed with `--require-hashes` (the build tool for the one package without
a ready-made wheel is pinned the same way, in `requirements-build.txt`, so nothing unpinned is
fetched while building). They're checked with `pip-audit`.

**Errors and crashes.** Messages shown in the window or printed by the command line never
contain file paths, your user name or cookies: they're removed before anything is shown. The
released app prints nothing, and if it ever crashes it shows no traceback.

**Deno in the downloadable app.** yt-dlp needs a JavaScript runtime to solve YouTube's
challenges. The app includes Deno, fetched by `packaging/get_deno.py` from the official releases
at `github.com/denoland/deno` for Apple chips, at a pinned version. It must match the SHA-256
pinned in that script (the one published with the release), carry a valid code signature from
Deno Land Inc.'s Apple Developer ID (team `2H4KBF436B`) and be built for Apple chips; it must
run and report the pinned version, or the build stops. The app uses only its own Deno.
yt-dlp runs it without network or file access; its update check and prompts are off, and its
cache goes to a temporary folder that's deleted when Dlr quits, however it quits (including ⌘Q).

**FFmpeg in the downloadable app.** The app on the Releases page is built by GitHub Actions
(`.github/workflows/build.yml`) and includes FFmpeg, fetched by `packaging/get_ffmpeg.py`. The
FFmpeg project itself publishes only source code, and the macOS build ffmpeg.org links to
(evermeet.cx) is for Intel Macs only, so Dlr uses Martin Riedl's notarized static builds for
Apple chips, at a pinned FFmpeg release (the newest at the time, with every fix listed on
ffmpeg.org/security.html). Each file must match the SHA-256 pinned in that script (the one his
site publishes), carry a valid code signature from his Apple Developer ID (team `KU3N25YGLU`),
be built for Apple chips, run, report the pinned version and include the encoders Dlr uses, or
the build stops. The app uses its own FFmpeg before any installed one.

**Releases.** Every release lists the .dmg's SHA-256 in its notes and in
`Dlr-mac-apple-silicon.dmg.sha256`, and the README gives the current one. The workflow pins
every GitHub Action to a full commit SHA, runs with read-only permissions (only the release job
may write, to publish), doesn't keep the token on disk after checking out, and uses no secrets
besides GitHub's own short-lived token.

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
  to the sites they belong to. For photo posts, gallery-dl reads only that site's cookies (for
  example only `.instagram.com`). Photos, thumbnails and covers Dlr fetches itself never get
  cookies, and redirects never carry them along. macOS asks first: Keychain access for Chrome-based browsers, Full
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
     (Running from source, Dlr never updates anything itself: the versions in
     `requirements.txt` are used.)
  4. PyPI, for gallery-dl updates, at the same times: `pypi.org/pypi/gallery-dl/json`, then the
     release file from `files.pythonhosted.org` if there's a new one.

  Nothing else: no analytics, telemetry, crash reports or update checks. The window itself makes
  no connections. Deno (run by yt-dlp for YouTube) has no network access.

## yt-dlp updates in the packaged app

The app has its own yt-dlp sealed inside. Updates replace it safely:

1. **Source:** only the official releases at `github.com/yt-dlp/yt-dlp`, over HTTPS. Redirects
   are followed only to GitHub's download servers (`*.githubusercontent.com`). Anything else
   stops the update.
2. **Signature:** the release's checksum list (`SHA2-256SUMS`) must carry a valid OpenPGP
   signature (`SHA2-256SUMS.sig`) from yt-dlp's release key. That key is pinned inside Dlr
   (`pgp.py`, fingerprint `AC0C BBE6 848D 6A87 3464 AF4E 57CF 6593 3B5A 7581`, as published in
   yt-dlp's repository) and checked by Dlr's own code, without needing gpg. Anything else (no
   signature, a damaged one, another key) stops the update before the file is downloaded.
3. **Checksum:** the file (`yt-dlp`, yt-dlp's platform-independent Python zip) must match the
   signed `SHA2-256SUMS`, and the version written inside it must match the release.
   On any mismatch the download is thrown away and the current version stays. (Tested with a
   1-byte change, with a changed or missing signature, with another key, and with a fake
   carrying a matching checksum but the wrong version.)
4. **Storage:** it's saved atomically to `~/Library/Application Support/Dlr/yt-dlp/` together
   with the signed checksum list, its signature and a small manifest.
5. **Use:** at the next launch, only if it's newer than the built-in yt-dlp, the signature is
   still valid, the file still matches the signed checksum, and it loads cleanly (plugins off).
   Otherwise the built-in version is used and the bad update is deleted. (Tested with a damaged
   file, a missing signature and one that fails to load.)
6. **When:** on its own at most once a day at launch, and after a failed download (at most once
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

## Known limits

- **Connections Python doesn't make:** the connection check covers everything Dlr, yt-dlp and
  gallery-dl do through Python. Two kinds of request don't go through it: TikTok's, which yt-dlp
  makes with curl_cffi (to look like a browser), and streams yt-dlp hands to FFmpeg to download
  itself (rare; live streams, for example). A TikTok page or such a stream could still point
  those at a local address.
- **Impersonation:** for TikTok, yt-dlp's `--impersonate` (curl_cffi) makes its requests look
  like a normal browser's, because TikTok refuses plain ones.
- **`'unsafe-eval'` in the CSP:** see the trade-off above.
- **yt-dlp updates trust yt-dlp's release key:** a release signed with that key is accepted. If
  yt-dlp ever changes its key, updates stop (the built-in version keeps working) until a new Dlr
  pins the new key.
- **gallery-dl updates trust PyPI:** gallery-dl publishes no signatures, so its update is
  checked against the SHA-256 PyPI lists for it (over HTTPS), not a signature. It doesn't protect
  against PyPI or the gallery-dl project itself being compromised.
- **Updated code lives in your account:** the update is code the app runs, stored in your
  Library folder. The yt-dlp update's signature is re-checked at every launch, so a changed file
  isn't used; the gallery-dl update's checksum is re-checked, which catches damage but not a
  deliberate change of both files by someone who can already write there.
- **Ad-hoc signature:** the Mac app is signed "ad hoc", not notarized by Apple, so macOS asks
  you to confirm the first launch (System Settings › Privacy & Security › Open Anyway).
- **Bundled FFmpeg and Deno trust their builders:** the checks prove the downloads are exactly
  the pinned files, signed by Martin Riedl's and Deno Land's Apple Developer IDs, not that the
  builders are trustworthy.
- **Clipboard:** read when the window comes to the front (only a link copied since Dlr opened
  is used).

## Keeping it safe

Update yt-dlp when sites change (see README), and re-check dependencies now and then:

```bash
pip install pip-audit
```

```bash
pip-audit --require-hashes --disable-pip -r requirements.txt -r requirements-build.txt
```

For FFmpeg, compare the version pinned in `packaging/get_ffmpeg.py` with the fixes listed on
[ffmpeg.org/security.html](https://ffmpeg.org/security.html), and move to a newer release when
one fixes something.
