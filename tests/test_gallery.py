"""gallery-dl child process: command line, private settings, and reading its listing. Offline."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import gallery

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.work, ignore_errors=True))

    def test_link_comes_last_after_double_dash(self):
        url = "https://www.tiktok.com/@a/photo/1"
        args = gallery.command(url, self.work, "/ff", "safari", ["--dump-json"])
        self.assertEqual(args[-2:], ["--", url])
        self.assertIn("--gallery-dl", args)
        self.assertIn("--config-ignore", args)  # never the user's own gallery-dl settings
        self.assertEqual(args[args.index("--cookies-from-browser") + 1], "safari")
        self.assertTrue(all(isinstance(a, str) for a in args))

    def test_a_link_that_looks_like_an_option_stays_a_link(self):
        args = gallery.command("--exec=evil", self.work, None)
        self.assertEqual(args[-2:], ["--", "--exec=evil"])

    def test_private_settings(self):
        args = gallery.command("https://x.com/a/status/1", self.work, "/ff")
        config = json.loads(Path(args[args.index("--config-json") + 1]).read_text())
        self.assertEqual(config["cache"]["file"], ":memory:")  # no cache on disk
        self.assertEqual(config["extractor"]["base-directory"], self.work)
        self.assertIsNone(config["extractor"]["archive"])
        self.assertIsNone(config["extractor"]["postprocessors"])
        self.assertIsNone(config["output"]["logfile"])
        self.assertTrue(config["extractor"]["tiktok"]["audio"])
        self.assertEqual(config["extractor"]["ytdl"]["raw-options"]["ffmpeg_location"], "/ff")


class ListingTest(unittest.TestCase):
    def test_tiktok_slideshow(self):
        out = (FIXTURES / "gallery_tiktok_slideshow.json").read_bytes()
        done = subprocess.CompletedProcess([], 0, stdout=out, stderr=b"")
        with tempfile.TemporaryDirectory() as work, mock.patch("subprocess.run", return_value=done):
            info = gallery.listing("https://www.tiktok.com/@a/photo/1", work, None)
        self.assertEqual((info["photos"], info["videos"], info["audio"]), (2, 0, True))
        self.assertEqual(info["title"], "now i understand")
        self.assertEqual(info["uploader"], "velocitydrawing")
        self.assertEqual(info["id"], "7266832970353233185")
        self.assertTrue(info["thumbnail"].endswith("photo1.jpeg"))

    def test_error_from_gallery_dl(self):
        out = json.dumps([[-1, {"error": "AbortExtraction", "message": "HTTP redirect to login page"}]]).encode()
        done = subprocess.CompletedProcess([], 4, stdout=out, stderr=b"")
        with tempfile.TemporaryDirectory() as work, mock.patch("subprocess.run", return_value=done):
            with self.assertRaisesRegex(gallery.GalleryError, "login page"):
                gallery.listing("https://www.instagram.com/p/abc/", work, None)

    def test_kind_of(self):
        self.assertEqual(gallery.kind_of("https://a/b.jpg", {"extension": "jpg"}), "photo")
        self.assertEqual(gallery.kind_of("https://a/b", {"extension": "mp4"}), "video")
        self.assertEqual(gallery.kind_of("ytdl:https://v.redd.it/x", {"extension": ""}), "video")
        self.assertEqual(gallery.kind_of("https://a/b", {"extension": "mp3", "type": "audio"}), "audio")


class ChildCommandTest(unittest.TestCase):
    def test_runs_this_app(self):
        cmd = gallery.self_command()
        self.assertTrue(os.path.basename(cmd[-1]) in ("app.py", os.path.basename(cmd[0])))


if __name__ == "__main__":
    unittest.main()
