"""Download FFmpeg for the downloadable app, so people don't have to install it themselves.

    python packaging/get_ffmpeg.py

Puts ffmpeg and ffprobe and a NOTICE.txt into packaging/ffmpeg/. build.py copies that folder
into the app. Every download is checked before it's used: Martin Riedl's static builds (linked
from ffmpeg.org), for Apple chips. They must carry a valid Apple-issued code signature, be built
for arm64, run, and include the H.264 (libx264) and MP3 (libmp3lame) encoders Dlr uses.
"""
import hashlib
import io
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "ffmpeg"
RIEDL = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/{tool}.zip"
REQUIRED = ("--enable-libx264", "--enable-libmp3lame")


def fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        sys.exit(f"Refusing a non-HTTPS address: {url}")
    headers = {"User-Agent": "Dlr-build"}
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300) as r:
        if not r.geturl().startswith("https://"):
            sys.exit(f"Redirected to a non-HTTPS address: {r.geturl()}")
        return r.read()


def macos() -> str:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        sys.exit("Dlr is a Mac app for Apple chips (M1 or newer): run this on an Apple-chip Mac.")
    lines = []
    for tool in ("ffmpeg", "ffprobe"):
        url = RIEDL.format(tool=tool)
        data = fetch(url)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next(n for n in z.namelist() if n.rsplit("/", 1)[-1] == tool)
            target = OUT / tool
            target.write_bytes(z.read(member))
        target.chmod(0o755)
        subprocess.run(["xattr", "-c", str(target)], check=False)
        # Must be signed by a developer Apple knows (it's notarized), not just anyone.
        subprocess.run(["codesign", "--verify", "--strict", "-R", "=anchor apple generic", str(target)],
                       check=True)
        archs = subprocess.run(["lipo", "-archs", str(target)], capture_output=True, text=True).stdout
        if archs.split() != ["arm64"]:
            sys.exit(f"{tool} is built for {archs.strip()}, not arm64 (Apple chips).")
        lines.append(f"{tool}: {url}, SHA-256 {hashlib.sha256(data).hexdigest()}")
    return "macOS static build by Martin Riedl, https://ffmpeg.martin-riedl.de\n" + "\n".join(lines)


def check():
    version = subprocess.run([str(OUT / "ffmpeg"), "-hide_banner", "-version"],
                             capture_output=True, text=True, check=True).stdout
    subprocess.run([str(OUT / "ffprobe"), "-hide_banner", "-version"],
                   capture_output=True, check=True)
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
