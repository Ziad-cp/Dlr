"""Download Deno for the downloadable app. yt-dlp runs it to solve YouTube's challenges.

    python packaging/get_deno.py

Puts deno (deno.exe on Windows) and a NOTICE.txt into packaging/deno/. build.py copies that
folder into the app. Every download is checked before it's used:

- Only from the official releases at github.com/denoland/deno, newest release, for this
  computer's chip (Mac: Apple chip or Intel; Windows: x64).
- Must match the SHA-256 published next to it in the same release (<file>.sha256sum).
- macOS: must also carry a valid Apple-issued code signature and be built for this chip.
- Must run, and be Deno 2 or newer (what yt-dlp needs).
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
OUT = HERE / "deno"
LATEST = "https://api.github.com/repos/denoland/deno/releases/latest"
TARGETS = {
    ("darwin", "arm64"): "aarch64-apple-darwin",
    ("darwin", "x86_64"): "x86_64-apple-darwin",
    ("win32", "AMD64"): "x86_64-pc-windows-msvc",
}


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


def expected_sha256(text: str, name: str) -> str:
    """The SHA-256 for name in a .sha256sum file. Deno's are either "<hash>  <name>" lines
    or PowerShell's Get-FileHash table (Algorithm / Hash / Path)."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*").rsplit("/", 1)[-1].rsplit("\\", 1)[-1] == name:
            if re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                return parts[0].lower()
    hashes = re.findall(r"\b[0-9a-fA-F]{64}\b", text)
    if len(hashes) == 1 and name in text:
        return hashes[0].lower()
    sys.exit(f"No checksum listed for {name}.")


def download() -> str:
    target = TARGETS.get((sys.platform, platform.machine()))
    if not target:
        sys.exit(f"No Deno build for {sys.platform} {platform.machine()}.")
    release = json.loads(fetch(LATEST))
    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    name = f"deno-{target}.zip"
    if name not in assets or f"{name}.sha256sum" not in assets:
        sys.exit(f"{name} or its checksum is missing from Deno {release['tag_name']}.")
    expected = expected_sha256(fetch(assets[f"{name}.sha256sum"]).decode("utf-8", "replace"), name)
    data = fetch(assets[name])
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        sys.exit(f"Checksum mismatch for {name}: got {actual}, expected {expected}.")
    exe = "deno.exe" if sys.platform == "win32" else "deno"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        member = next((n for n in z.namelist() if n.rsplit("/", 1)[-1] == exe), None)
        if not member:
            sys.exit(f"{name} doesn't contain {exe}.")
        (OUT / exe).write_bytes(z.read(member))
    if sys.platform == "darwin":
        tool = OUT / exe
        tool.chmod(0o755)
        subprocess.run(["xattr", "-c", str(tool)], check=False)
        # Must be signed by a developer Apple knows (it's notarized), not just anyone.
        subprocess.run(["codesign", "--verify", "--strict", "-R", "=anchor apple generic", str(tool)],
                       check=True)
        archs = subprocess.run(["lipo", "-archs", str(tool)], capture_output=True, text=True).stdout
        if platform.machine() not in archs.split():
            sys.exit(f"deno is built for {archs.strip()}, not {platform.machine()}.")
    return (f"{name} from https://github.com/denoland/deno/releases/tag/{release['tag_name']}, "
            f"SHA-256 {actual}")


def check() -> str:
    exe = OUT / ("deno.exe" if sys.platform == "win32" else "deno")
    env = dict(os.environ, DENO_NO_UPDATE_CHECK="1")
    first = subprocess.run([str(exe), "--version"], capture_output=True, text=True, check=True,
                           env=env).stdout.splitlines()[0]
    m = re.match(r"deno (\d+)\.", first)
    if not m or int(m.group(1)) < 2:
        sys.exit(f"yt-dlp needs Deno 2 or newer, got: {first}")
    print(first)
    return first


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    source = download()
    first_line = check()
    (OUT / "NOTICE.txt").write_text(
        "Dlr includes Deno (https://deno.com), which yt-dlp runs, without network or file\n"
        "access, to solve YouTube's challenges. Deno is free software under the MIT License:\n"
        "https://github.com/denoland/deno/blob/main/LICENSE.md\n"
        "Deno's source code: https://github.com/denoland/deno\n\n"
        f"{first_line}\n{source}\n", encoding="utf-8")
    print(f"Deno is ready in {OUT}")


if __name__ == "__main__":
    main()
