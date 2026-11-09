"""Download Deno for the downloadable app. yt-dlp runs it to solve YouTube's challenges.

    python packaging/get_deno.py

Puts deno and a NOTICE.txt into packaging/deno/. build.py copies that folder into the app.
Every download is checked before it's used, and the build stops on any mismatch:

- A pinned release (VERSION below) from the official releases at github.com/denoland/deno, for
  Apple chips (aarch64-apple-darwin), over HTTPS, with redirects allowed only to GitHub's
  download servers.
- Must match the SHA-256 pinned below (the one published next to it, <file>.sha256sum).
- Must carry a valid code signature from Deno Land Inc.'s Apple Developer ID (team 2H4KBF436B),
  be built for arm64, run, and report the pinned version.

To move to a newer Deno: change VERSION and SHA256 (from the release's
deno-aarch64-apple-darwin.zip.sha256sum), then run this script.
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
from urllib.parse import urlsplit

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "deno"
VERSION = "2.9.8"
NAME = "deno-aarch64-apple-darwin.zip"
SHA256 = "9f0bf660393da2eaff044cdc7444cb08c73f235849b61d224d825a194ce7c98e"
URL = f"https://github.com/denoland/deno/releases/download/v{VERSION}/{NAME}"
TEAM_ID = "2H4KBF436B"  # Developer ID Application: Deno Land Inc.
MAX_ZIP = 300 * 1024 * 1024


def _allowed(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == "github.com" or host.endswith(".githubusercontent.com"))


class _GitHubOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            sys.exit(f"Refusing a redirect away from GitHub: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, limit: int = MAX_ZIP) -> bytes:
    if not _allowed(url):
        sys.exit(f"Refusing an address outside GitHub: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Dlr-build"})
    with urllib.request.build_opener(_GitHubOnly).open(req, timeout=300) as r:
        if not _allowed(r.geturl()):
            sys.exit(f"Redirected away from GitHub: {r.geturl()}")
        data = r.read(limit + 1)
    if len(data) > limit:
        sys.exit(f"{url} is larger than expected.")
    return data


def download() -> str:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        sys.exit("Dlr is a Mac app for Apple chips (M1 or newer): run this on an Apple-chip Mac.")
    data = fetch(URL)
    actual = hashlib.sha256(data).hexdigest()
    if actual != SHA256:
        sys.exit(f"Checksum mismatch for {NAME}: got {actual}, expected {SHA256}.")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members = [n for n in z.namelist() if n.rsplit("/", 1)[-1] == "deno"]
        if len(members) != 1:
            sys.exit(f"{NAME} should contain exactly one deno.")
        (OUT / "deno").write_bytes(z.read(members[0]))
    tool = OUT / "deno"
    tool.chmod(0o755)
    subprocess.run(["xattr", "-c", str(tool)], check=False)
    # Signed by Deno's own Developer ID (Apple-issued), not just anyone.
    requirement = f'=anchor apple generic and certificate leaf[subject.OU] = "{TEAM_ID}"'
    subprocess.run(["codesign", "--verify", "--strict", "-R", requirement, str(tool)], check=True)
    archs = subprocess.run(["lipo", "-archs", str(tool)], capture_output=True, text=True).stdout
    if archs.split() != ["arm64"]:
        sys.exit(f"deno is built for {archs.strip()}, not arm64 (Apple chips).")
    return f"{NAME} from https://github.com/denoland/deno/releases/tag/v{VERSION}, SHA-256 {actual}"


def check() -> str:
    exe = OUT / "deno"
    env = dict(os.environ, DENO_NO_UPDATE_CHECK="1")
    first = subprocess.run([str(exe), "--version"], capture_output=True, text=True, check=True,
                           env=env).stdout.splitlines()[0]
    if not first.startswith(f"deno {VERSION} "):
        sys.exit(f"Expected Deno {VERSION}, got: {first}")
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
