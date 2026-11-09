"""Download FFmpeg for the downloadable app, so people don't have to install it themselves.

    python packaging/get_ffmpeg.py

Puts ffmpeg and ffprobe and a NOTICE.txt into packaging/ffmpeg/. build.py copies that folder
into the app. FFmpeg's own project publishes only source code, and the macOS build ffmpeg.org
links to (evermeet.cx) is for Intel Macs only, so Dlr uses Martin Riedl's notarized static
builds for Apple chips (https://ffmpeg.martin-riedl.de). Every download is checked before it's
used, and the build stops on any mismatch:

- A pinned release (VERSION below), from its exact address on ffmpeg.martin-riedl.de, over
  HTTPS, with redirects allowed only within that site.
- Must match the SHA-256 pinned below (the one the site publishes next to each file).
- Must carry a valid code signature from Martin Riedl's Apple Developer ID (team KU3N25YGLU),
  be built for arm64, run, report the pinned version, and include the H.264 (libx264) and MP3
  (libmp3lame) encoders Dlr uses.

To move to a newer FFmpeg: change BUILD, VERSION and the two SHA-256s (from the .sha256 files
next to the zips), then run this script.
"""
import hashlib
import io
import pathlib
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from urllib.parse import urlsplit

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "ffmpeg"
HOST = "ffmpeg.martin-riedl.de"
VERSION = "9.0.2"
BUILD = f"1789931890_{VERSION}"
FILES = {  # tool: SHA-256 of its zip
    "ffmpeg": "c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924",
    "ffprobe": "fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6",
}
URL = f"https://{HOST}/download/macos/arm64/{BUILD}/{{tool}}.zip"
TEAM_ID = "KU3N25YGLU"  # Developer ID Application: Martin Riedl
REQUIRED = ("--enable-libx264", "--enable-libmp3lame")
MAX_ZIP = 200 * 1024 * 1024


class _SameSite(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            sys.exit(f"Refusing a redirect away from {HOST}: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _allowed(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == HOST


def fetch(url: str, limit: int = MAX_ZIP) -> bytes:
    if not _allowed(url):
        sys.exit(f"Refusing an address outside https://{HOST}: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Dlr-build"})
    with urllib.request.build_opener(_SameSite).open(req, timeout=300) as r:
        if not _allowed(r.geturl()):
            sys.exit(f"Redirected away from {HOST}: {r.geturl()}")
        data = r.read(limit + 1)
    if len(data) > limit:
        sys.exit(f"{url} is larger than expected.")
    return data


def verify_signature(tool: pathlib.Path):
    """Signed by Martin Riedl's Developer ID (Apple-issued), not just anyone."""
    requirement = f'=anchor apple generic and certificate leaf[subject.OU] = "{TEAM_ID}"'
    subprocess.run(["codesign", "--verify", "--strict", "-R", requirement, str(tool)], check=True)


def macos() -> str:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        sys.exit("Dlr is a Mac app for Apple chips (M1 or newer): run this on an Apple-chip Mac.")
    lines = []
    for tool, expected in FILES.items():
        url = URL.format(tool=tool)
        data = fetch(url)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            sys.exit(f"Checksum mismatch for {tool}.zip: got {actual}, expected {expected}.")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = [n for n in z.namelist() if n.rsplit("/", 1)[-1] == tool]
            if len(members) != 1:
                sys.exit(f"{tool}.zip should contain exactly one {tool}.")
            target = OUT / tool
            target.write_bytes(z.read(members[0]))
        target.chmod(0o755)
        subprocess.run(["xattr", "-c", str(target)], check=False)
        verify_signature(target)
        archs = subprocess.run(["lipo", "-archs", str(target)], capture_output=True, text=True).stdout
        if archs.split() != ["arm64"]:
            sys.exit(f"{tool} is built for {archs.strip()}, not arm64 (Apple chips).")
        lines.append(f"{tool}: {url}, SHA-256 {actual}")
    return "macOS static build by Martin Riedl, https://ffmpeg.martin-riedl.de\n" + "\n".join(lines)


def check():
    version = subprocess.run([str(OUT / "ffmpeg"), "-hide_banner", "-version"],
                             capture_output=True, text=True, check=True).stdout
    probe = subprocess.run([str(OUT / "ffprobe"), "-hide_banner", "-version"],
                           capture_output=True, text=True, check=True).stdout
    for name, text in (("ffmpeg", version), ("ffprobe", probe)):
        if not text.startswith(f"{name} version {VERSION}-"):
            sys.exit(f"{name} doesn't report version {VERSION}: {text.splitlines()[0] if text else ''}")
    missing = [flag for flag in REQUIRED if flag not in version]
    if missing:
        sys.exit(f"This FFmpeg build lacks {', '.join(missing)}.")
    print(version.splitlines()[0])
    return version.splitlines()[0]


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    source = macos()
    first_line = check()
    (OUT / "NOTICE.txt").write_text(
        "Dlr includes FFmpeg (https://ffmpeg.org), which it uses to combine picture and sound\n"
        "and to make MP3s. FFmpeg is free software, licensed under the GNU General Public\n"
        "License version 3 or later (https://www.gnu.org/licenses/gpl-3.0.html) for this build.\n"
        "FFmpeg's source code: https://ffmpeg.org/download.html\n\n"
        f"{first_line}\n{source}\n", encoding="utf-8")
    print(f"FFmpeg is ready in {OUT}")


if __name__ == "__main__":
    main()
