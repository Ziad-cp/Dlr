"""Build the app for personal use.

    python build.py

macOS   -> dist/Dlr.app  and  dist/Dlr-<version>.dmg
           (drag-to-Applications window; the app is signed "ad hoc" for this Mac)
Windows -> dist/Dlr.exe  (single file)

PyInstaller can't cross-compile: build the .exe on Windows and the .app on a Mac.
The iPhone script is built separately: python iphone/build.py
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
        args += ["--onefile"]
    PyInstaller.__main__.run(args)


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
    shutil.rmtree(ROOT / "build", ignore_errors=True)
