"""Build the app for personal use.

    python build.py

macOS   -> dist/Dlr.app  and  dist/Dlr-<version>.dmg
           (drag-to-Applications window; the app is signed "ad hoc" for this Mac)
Windows -> dist/Dlr/Dlr.exe  (an app folder; packaging/windows/dlr.iss turns it into an installer)

If packaging/ffmpeg/ exists (python packaging/get_ffmpeg.py), FFmpeg is copied into the app,
so it works without installing FFmpeg. Otherwise the app uses an installed FFmpeg.

PyInstaller can't cross-compile: build the .exe on Windows and the .app on a Mac.
The GitHub workflow in .github/workflows/build.yml does both.
"""
import os
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys

import PyInstaller.__main__

ROOT = pathlib.Path(__file__).resolve().parent
NAME = "Dlr"
BUNDLE_ID = "com.local.dlr"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "app.py").read_text()).group(1)
ICON = ROOT / "packaging" / "icon.icns"
FFMPEG = ROOT / "packaging" / "ffmpeg"


def build_app():
    args = [
        str(ROOT / "app.py"),
        "--name", NAME,
        "--windowed",
        "--noconfirm",
        "--clean",
        "--add-data", f"{ROOT / 'ui'}{os.pathsep}ui",
        "--copy-metadata", "yt-dlp",  # so the app knows its built-in yt-dlp version
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


def add_ffmpeg(internal: pathlib.Path):
    """Copy packaging/ffmpeg/ into the app, next to the app's own files (sys._MEIPASS)."""
    if not FFMPEG.is_dir():
        print("packaging/ffmpeg/ not found: the app will use an installed FFmpeg.")
        return
    target = internal / "ffmpeg"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(FFMPEG, target)
    print(f"Included FFmpeg in {target.relative_to(ROOT)}")


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
    })
    info_path.write_bytes(plistlib.dumps(info))
    add_ffmpeg(app / "Contents" / "Frameworks")
    bundled = app / "Contents" / "Frameworks" / "ffmpeg"
    if bundled.is_dir():
        # Only code may live in Frameworks (or signing fails), so the licence notice moves.
        notice = bundled / "NOTICE.txt"
        if notice.exists():
            shutil.move(notice, app / "Contents" / "Resources" / "FFmpeg-NOTICE.txt")
        for tool in bundled.iterdir():
            subprocess.run(["codesign", "--force", "--sign", "-", str(tool)], check=True)
    # Info.plist changed, so sign the bundle again (ad hoc: fine for your own Mac).
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    return app


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
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    build_app()
    if sys.platform == "darwin":
        shutil.rmtree(ROOT / "dist" / NAME, ignore_errors=True)  # loose copy; the .app has it all
        built = finish_mac_app()
        image = make_dmg(built)
        print(f"\nBuilt {built.relative_to(ROOT)} (version {VERSION})\nBuilt {image.relative_to(ROOT)}")
    elif sys.platform == "win32":
        add_ffmpeg(ROOT / "dist" / NAME / "_internal")
        print(f"\nBuilt dist/{NAME}/{NAME}.exe (version {VERSION})")
    shutil.rmtree(ROOT / "build", ignore_errors=True)
