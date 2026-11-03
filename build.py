"""Build the app for personal use.

    python build.py

macOS   -> dist/Dlr.app  and  dist/Dlr-<version>.dmg
           (drag-to-Applications window; the app is signed "ad hoc" for this Mac).
           Apple chips (M1 or newer) only, macOS 12 Monterey or newer: build it on an
           Apple-chip Mac.
Windows -> dist/Dlr/Dlr.exe  (an app folder; packaging/windows/dlr.iss turns it into an installer)

If packaging/ffmpeg/ and packaging/deno/ exist (python packaging/get_ffmpeg.py and
python packaging/get_deno.py), FFmpeg and Deno are copied into the app, so it needs nothing else.

PyInstaller can't cross-compile: build the .exe on Windows and the .app on a Mac.
The GitHub workflow in .github/workflows/build.yml does both.
"""
import os
import pathlib
import platform
import plistlib
import re
import shutil
import subprocess
import sys

import PyInstaller.__main__

ROOT = pathlib.Path(__file__).resolve().parent
NAME = "Dlr"
BUNDLE_ID = "com.local.dlr"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "app.py").read_text(encoding="utf-8")).group(1)
ICON = ROOT / "packaging" / "icon.icns"
TOOLS = {"ffmpeg": "FFmpeg", "deno": "Deno"}  # folder in packaging/ -> name
# The oldest macOS the Mac app runs on: what the bundled FFmpeg and Deno need (both are built
# for macOS 12). Python, pywebview and the other parts need macOS 11.
MIN_MACOS = "12.0"


def build_app():
    args = [
        str(ROOT / "app.py"),
        "--name", NAME,
        "--windowed",
        "--noconfirm",
        "--clean",
        "--add-data", f"{ROOT / 'ui'}{os.pathsep}ui",
        "--copy-metadata", "yt-dlp",  # so the app knows its built-in yt-dlp version
        "--copy-metadata", "gallery-dl",
        # Loaded by name at run time, so PyInstaller can't see them by itself.
        "--collect-submodules", "gallery_dl",
        "--collect-submodules", "yt_dlp_ejs",
        "--collect-data", "yt_dlp_ejs",  # YouTube's challenge solver scripts, run by Deno
        "--collect-all", "curl_cffi",  # for --impersonate (TikTok)
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", BUNDLE_ID, "--icon", str(ICON)]
    elif sys.platform == "win32":
        # An app folder rather than one big .exe: it starts faster, and antivirus programs
        # are much less likely to flag it by mistake.
        args += ["--icon", str(ROOT / "packaging" / "icon.ico")]
    PyInstaller.__main__.run(args)


def add_tools(internal: pathlib.Path):
    """Copy packaging/ffmpeg/ and packaging/deno/ into the app, next to the app's own files
    (sys._MEIPASS)."""
    for folder, name in TOOLS.items():
        source = ROOT / "packaging" / folder
        if not source.is_dir():
            print(f"packaging/{folder}/ not found: the app won't include {name}.")
            continue
        target = internal / folder
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
        print(f"Included {name} in {target.relative_to(ROOT)}")


def finish_mac_app() -> pathlib.Path:
    app = ROOT / "dist" / f"{NAME}.app"
    info_path = app / "Contents" / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info.update({
        "CFBundleName": NAME,
        "CFBundleDisplayName": NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHumanReadableCopyright": "Personal use.",
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSArchitecturePriority": ["arm64"],
    })
    info_path.write_bytes(plistlib.dumps(info))
    add_tools(app / "Contents" / "Frameworks")
    for folder, name in TOOLS.items():
        bundled = app / "Contents" / "Frameworks" / folder
        if not bundled.is_dir():
            continue
        # Only code may live in Frameworks (or signing fails), so the licence notice moves.
        notice = bundled / "NOTICE.txt"
        if notice.exists():
            shutil.move(notice, app / "Contents" / "Resources" / f"{name}-NOTICE.txt")
        for tool in bundled.iterdir():
            subprocess.run(["codesign", "--force", "--sign", "-", str(tool)], check=True)
    # Info.plist changed, so sign the bundle again (ad hoc: fine for your own Mac).
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    check_min_macos(app)
    return app


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in text.split("."))


def check_min_macos(app: pathlib.Path):
    """Every program and library in the app must run on MIN_MACOS. On GitHub (the builds
    people download) a newer one stops the build. A local build is only for this Mac, so
    there it's a warning (Homebrew's Python, for example, is built for the newest macOS)."""
    too_new = {}
    for f in app.rglob("*"):
        if not f.is_file() or f.is_symlink():
            continue
        with open(f, "rb") as fh:
            if fh.read(4) not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):  # Mach-O
                continue
        out = subprocess.run(["vtool", "-show-build", str(f)], capture_output=True, text=True).stdout
        for minos in re.findall(r"minos (\d+(?:\.\d+)*)", out):
            if _version(minos) > _version(MIN_MACOS):
                too_new[str(f.relative_to(app))] = minos
    if not too_new:
        print(f"Every part of the app runs on macOS {MIN_MACOS} or newer.")
        return
    listing = "\n".join(f"  {name}: macOS {minos}" for name, minos in sorted(too_new.items())[:10])
    message = (f"{len(too_new)} files in the app need a macOS newer than {MIN_MACOS}:\n{listing}")
    if os.environ.get("GITHUB_ACTIONS"):
        sys.exit(message)
    print(f"Warning (fine for this Mac only): {message}")


def make_dmg(app: pathlib.Path) -> pathlib.Path:
    import dmgbuild

    dmg = ROOT / "dist" / f"Dlr-{VERSION}.dmg"
    dmg.unlink(missing_ok=True)
    dmgbuild.build_dmg(str(dmg), NAME, settings={
        "format": "UDZO",
        "files": [str(app)],
        "symlinks": {"Applications": "/Applications"},
        "icon": str(ICON),
        "icon_locations": {app.name: (150, 170), "Applications": (450, 170)},
        "window_rect": ((200, 200), (600, 380)),
        "icon_size": 112,
        "text_size": 13,
        "show_status_bar": False,
        "show_tab_view": False,
        "show_toolbar": False,
        "show_pathbar": False,
        "show_sidebar": False,
        "background": "#16161c",
    })
    return dmg


if __name__ == "__main__":
    if sys.platform == "darwin" and platform.machine() != "arm64":
        sys.exit("The Mac app is for Apple chips (M1 or newer) only: build it on an Apple-chip Mac.")
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    build_app()
    if sys.platform == "darwin":
        shutil.rmtree(ROOT / "dist" / NAME, ignore_errors=True)  # loose copy; the .app has it all
        built = finish_mac_app()
        image = make_dmg(built)
        print(f"\nBuilt {built.relative_to(ROOT)} (version {VERSION})\nBuilt {image.relative_to(ROOT)}")
    elif sys.platform == "win32":
        add_tools(ROOT / "dist" / NAME / "_internal")
        print(f"\nBuilt dist/{NAME}/{NAME}.exe (version {VERSION})")
    shutil.rmtree(ROOT / "build", ignore_errors=True)
