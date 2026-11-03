"""Every launch starts empty, and nothing about past downloads is kept on disk. Offline."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import config

ROOT = Path(__file__).resolve().parent.parent
LAST = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
NEW = "https://www.tiktok.com/@a/video/1"


class LaunchClipboardTest(unittest.TestCase):
    def clipboard(self, text):
        self.text = text
        patcher = mock.patch("app.read_clipboard", side_effect=lambda: self.text)
        patcher.start()
        self.addCleanup(patcher.stop)
        return app.LaunchClipboard()

    def test_link_from_before_launch_is_not_filled_in(self):
        clip = self.clipboard(f"look at this {LAST}")
        self.assertEqual(clip.new_link(), "")  # the page's check at launch
        self.assertEqual(clip.new_link(), "")  # and each time the window comes to the front

    def test_link_copied_after_launch_is_filled_in(self):
        clip = self.clipboard(LAST)
        self.text = NEW
        self.assertEqual(clip.new_link(), NEW)

    def test_same_link_copied_again_later_counts(self):
        clip = self.clipboard(LAST)
        self.text = "some notes"
        self.assertEqual(clip.new_link(), "")
        self.text = LAST
        self.assertEqual(clip.new_link(), LAST)

    def test_empty_clipboard_at_launch(self):
        clip = self.clipboard("")
        self.assertEqual(clip.new_link(), "")
        self.text = NEW
        self.assertEqual(clip.new_link(), NEW)

    def test_only_safe_links(self):
        for text in ("no link here", "http://127.0.0.1/x", "file:///etc/passwd"):
            self.assertEqual(app.clipboard_link(text), "", text)


class NothingRememberedTest(unittest.TestCase):
    def test_config_holds_only_settings(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.object(config, "CONFIG_PATH", Path(home) / "config.json"):
            config.save({"output_dir": home, "cookies_browser": "off",
                         "last_url": LAST, "history": [LAST], "title": "x", "thumbnail": "y"})
            saved = json.loads((Path(home) / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(set(saved), {"output_dir", "cookies_browser"})

    def test_page_never_stores_anything(self):
        for name in ("app.js", "index.html"):
            text = (ROOT / "ui" / name).read_text(encoding="utf-8")
            for api in ("localStorage", "sessionStorage", "indexedDB", "document.cookie", "caches."):
                self.assertNotIn(api, text, f"{name} uses {api}")

    def test_link_field_starts_empty(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        field = re.search(r"<input[^>]*\bid=\"url\"[^>]*>", html).group(0)
        self.assertNotIn("value=", field)
        self.assertIn('autocomplete="off"', field)

    def test_web_view_keeps_no_data(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertRegex(source, r"webview\.start\([^)]*private_mode=True")


if __name__ == "__main__":
    unittest.main()
