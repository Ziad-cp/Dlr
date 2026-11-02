"""The app's only saved data: the download folder and which browser's login to use, in
config.json in the user's app-data folder.

Nothing else is ever stored: no history, no links, no titles, no cookies. Anything else found in the
file (e.g. from older versions) is erased the next time the app starts.
"""
import json
import os
import sys
from pathlib import Path

APP_NAME = "Dlr"
OLD_NAME = "VideoDownloader"  # before the app was renamed


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


CONFIG_PATH = config_dir() / "config.json"
OLD_CONFIG = config_dir().parent / OLD_NAME / "config.json"


# Browsers yt-dlp can read logins from; "auto" is the default browser, "off" never reads any.
BROWSERS = ("auto", "safari", "chrome", "firefox", "brave", "edge", "opera", "vivaldi", "chromium", "off")
# Logins are off until the user turns them on in Settings.
DEFAULT_BROWSER = "off"


def _default_folder() -> str:
    return str(Path.home() / "Downloads")


def _move_old_settings():
    """Carry the download folder over from the app's old name, then remove the old file."""
    if CONFIG_PATH.exists() or not OLD_CONFIG.is_file() or OLD_CONFIG.is_symlink():
        return
    try:
        folder = json.loads(OLD_CONFIG.read_text(encoding="utf-8")).get("output_dir")
    except (OSError, ValueError, AttributeError):
        folder = None
    if isinstance(folder, str):
        save({"output_dir": folder})
    if not CONFIG_PATH.is_file():
        return  # couldn't write the new file: keep the old one
    try:
        OLD_CONFIG.unlink()
        OLD_CONFIG.parent.rmdir()  # only if now empty
    except OSError:
        pass


def load() -> dict:
    _move_old_settings()
    stored = {}
    try:
        stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    folder = stored.get("output_dir") if isinstance(stored, dict) else None
    if not isinstance(folder, str) or not os.path.isabs(folder) or not os.path.isdir(folder):
        folder = _default_folder()
    browser = stored.get("cookies_browser") if isinstance(stored, dict) else None
    cfg = {"output_dir": folder, "cookies_browser": browser if browser in BROWSERS else DEFAULT_BROWSER}
    if stored and stored != cfg:
        save(cfg)  # rewrite without anything an older version kept (history, tokens ...)
    return cfg


def save(cfg: dict) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"output_dir": cfg["output_dir"], "cookies_browser": cfg.get("cookies_browser", DEFAULT_BROWSER)}
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
