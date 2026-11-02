"""The settings file: logins are off until the user turns them on. Offline."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        patches = [mock.patch.object(config, "CONFIG_PATH", self.dir / "config.json"),
                   mock.patch.object(config, "OLD_CONFIG", self.dir / "old" / "config.json")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_logins_off_by_default(self):
        self.assertEqual(config.load()["cookies_browser"], "off")

    def test_unknown_value_falls_back_to_off(self):
        config.CONFIG_PATH.write_text(json.dumps({"cookies_browser": "netscape"}))
        self.assertEqual(config.load()["cookies_browser"], "off")

    def test_a_chosen_browser_is_kept(self):
        config.CONFIG_PATH.write_text(json.dumps({"cookies_browser": "firefox"}))
        self.assertEqual(config.load()["cookies_browser"], "firefox")

    def test_save_without_a_choice_keeps_logins_off(self):
        config.save({"output_dir": str(self.dir)})
        self.assertEqual(json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))["cookies_browser"], "off")


if __name__ == "__main__":
    unittest.main()
