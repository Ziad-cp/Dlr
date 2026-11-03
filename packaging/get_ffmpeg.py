"""Download FFmpeg for the downloadable app, so people don't have to install it themselves.

    python packaging/get_ffmpeg.py

Puts ffmpeg and ffprobe (plus their DLLs on Windows) and a NOTICE.txt into packaging/ffmpeg/.
build.py copies that folder into the app. Every download is checked before it's used:

Windows  BtbN/FFmpeg-Builds on GitHub (the builds linked from ffmpeg.org), newest release
         branch, "gpl-shared" variant. Must match the SHA-256 in that release's checksums.sha256.
macOS    Martin Riedl's static builds (also linked from ffmpeg.org), for Apple chips (arm64).
         Must carry a valid Apple-issued code signature, and be built for arm64.

Both must run, and include the H.264 (libx264) and MP3 (libmp3lame) encoders Dlr uses.
"""
import hashlib
import io
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "ffmpeg"
BTBN = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest"
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


def windows() -> str:
    release = json.loads(fetch(BTBN))
    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    builds = {}
    for name in assets:
        m = re.fullmatch(r"ffmpeg-n([\d.]+)-latest-win64-gpl-shared-[\d.]+\.zip", name)
        if m:
            builds[tuple(int(x) for x in m.group(1).split("."))] = name
    if not builds:
        sys.exit("No Windows FFmpeg build found in BtbN/FFmpeg-Builds.")
    name = builds[max(builds)]
    sums = fetch(assets["checksums.sha256"]).decode()
    expected = next((line.split()[0].lower() for line in sums.splitlines()
                     if line.split()[-1:] == [name]), None)
    if not expected:
        sys.exit(f"No checksum listed for {name}.")
    data = fetch(assets[name])
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        sys.exit(f"Checksum mismatch for {name}: got {actual}, expected {expected}.")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            parts = member.split("/")
            if len(parts) == 3 and parts[1] == "bin" and (
                    parts[2] in ("ffmpeg.exe", "ffprobe.exe") or parts[2].lower().endswith(".dll")):
                (OUT / parts[2]).write_bytes(z.read(member))
    return (f"Windows build {name} from https://github.com/BtbN/FFmpeg-Builds "
            f"(release 'latest'), SHA-256 {actual}")


def macos() -> str:
    if platform.machine() != "arm64":
        sys.exit("The Mac app is for Apple chips (M1 or newer) only: build it on an Apple-chip Mac.")
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
    exe = ".exe" if sys.platform == "win32" else ""
    version = subprocess.run([str(OUT / f"ffmpeg{exe}"), "-hide_banner", "-version"],
                             capture_output=True, text=True, check=True).stdout
    subprocess.run([str(OUT / f"ffprobe{exe}"), "-hide_banner", "-version"],
                   capture_output=True, check=True)
    missing = [flag for flag in REQUIRED if flag not in version]
    if missing:
        sys.exit(f"This FFmpeg build lacks {', '.join(missing)}.")
    print(version.splitlines()[0])
    return version.splitlines()[0]


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    if sys.platform == "win32":
        source = windows()
    elif sys.platform == "darwin":
        source = macos()
    else:
        sys.exit("Only Windows and macOS builds include FFmpeg.")
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
