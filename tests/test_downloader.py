"""Download rules: qualities, format choice, errors, logins and retries. Offline."""
import os
import socket
import tempfile
import unittest
from unittest import mock

import downloader as dl
import safety

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]


def fmt(fid, height, vcodec="avc1.640028", acodec="none", fps=30, **extra):
    width = extra.pop("width", height * 16 // 9 if height else None)
    return {"format_id": fid, "height": height, "width": width, "vcodec": vcodec, "acodec": acodec,
            "fps": fps, "ext": "mp4", "protocol": "https", **extra}


class QualityTest(unittest.TestCase):
    def test_only_real_qualities(self):
        formats = [
            fmt("sb0", 90, vcodec="none", ext="mhtml", format_note="storyboard"),
            fmt("a", None, vcodec="none", acodec="mp4a.40.2"),
            fmt("360", 360), fmt("720", 720, fps=60), fmt("1080", 1080),
            fmt("1080b", 1080, vcodec="vp9"),
        ]
        q = dl.quality_options(formats)
        self.assertEqual([x["height"] for x in q["qualities"]], [1080, 720])
        self.assertEqual(q["qualities"][1]["label"], "720p · 60fps")
        self.assertFalse(q["lowOnly"])

    def test_low_only(self):
        q = dl.quality_options([fmt("240", 240), fmt("144", 144)])
        self.assertEqual([x["height"] for x in q["qualities"]], [240])
        self.assertTrue(q["lowOnly"])

    def test_vertical_video_uses_short_side(self):
        q = dl.quality_options([fmt("v", 1920, width=1080)])
        self.assertEqual(q["qualities"][0]["height"], 1080)

    def test_watermarked_versions_are_ignored(self):
        formats = [fmt("clean", 720, acodec="aac"), fmt("wm", 1080, acodec="aac", format_note="watermarked")]
        self.assertEqual([x["height"] for x in dl.quality_options(formats)["qualities"]], [720])
        picked = list(dl._pick_video({"formats": formats}))
        self.assertEqual(picked[0]["format_id"], "clean")

    def test_h264_preferred_at_same_quality(self):
        formats = [fmt("av1", 1080, vcodec="av01"), fmt("h264", 1080, vcodec="avc1.640028"),
                   fmt("vp9", 1080, vcodec="vp9"), fmt("m4a", None, vcodec="none", acodec="mp4a.40.2", ext="m4a")]
        picked = list(dl._pick_video({"formats": formats}))[0]
        self.assertEqual(picked["format_id"], "h264+m4a")

    def test_sound_with_unknown_codec_is_merged(self):
        # X lists its HLS sound streams without a codec, next to silent HLS video.
        formats = [
            fmt("hls-audio-32000-Audio", None, vcodec="none", acodec=None),
            fmt("hls-audio-64000-Audio", None, vcodec="none", acodec=None),
            fmt("http-256", 180, vcodec=None, acodec=None),
            fmt("hls-126", 180, vcodec="avc1.42C00C", acodec="none"),
            fmt("http-832", 360, vcodec=None, acodec=None),
            fmt("hls-348", 360, vcodec="avc1.42C01E", acodec="none"),
        ]
        picked = list(dl._pick_video({"formats": formats}))[0]
        self.assertEqual(picked["format_id"], "hls-348+hls-audio-64000-Audio")

    def test_best_kept_when_h264_is_worse(self):
        formats = [fmt("h264", 720, vcodec="avc1"), fmt("vp9", 2160, vcodec="vp9"),
                   fmt("opus", None, vcodec="none", acodec="opus", ext="webm")]
        picked = list(dl._pick_video({"formats": formats}))[0]
        self.assertEqual(picked["format_id"], "vp9+opus")

    def test_mp3_is_320k(self):
        opts = dl.build_opts("mp3", "/tmp")
        self.assertEqual(opts["postprocessors"][0]["preferredquality"], "320")
        self.assertEqual(dl.MP3_LABEL, "MP3 · 320 kbps")

    def test_tiktok_impersonates_a_browser(self):
        if not dl.IMPERSONATE:
            self.skipTest("curl_cffi isn't installed")
        self.assertIn("impersonate", dl.build_opts("best", "/tmp", "https://www.tiktok.com/@a/video/1"))
        self.assertNotIn("impersonate", dl.build_opts("best", "/tmp", "https://www.youtube.com/watch?v=a"))

    def test_valid_quality(self):
        for q in ("best", "mp3", "720", "2160"):
            self.assertTrue(dl.valid_quality(q))
        for q in ("", "video", "99", "9999", "720p", "-1"):
            self.assertFalse(dl.valid_quality(q))

    def test_count_label(self):
        self.assertEqual(dl.count_label(3, 0), "3 photos")
        self.assertEqual(dl.count_label(1, 2), "1 photo · 2 videos")
        self.assertEqual(dl.count_label(0, 1), "1 video")


class ErrorTest(unittest.TestCase):
    def test_plain_english(self):
        cases = {
            "ERROR: [Reddit] x: Account authentication is required. Use --cookies-from-browser": dl.LOGIN_ERROR,
            "AbortExtraction: \"You've been blocked by network security.\"": dl.LOGIN_ERROR,
            "ERROR: [Instagram] x: There is no video in this post": dl.NO_MEDIA,
            "ERROR: [x] y: Unable to download webpage: HTTP Error 500: Domain Not Found":
                "The site had a problem sending this. Try again in a few minutes.",
            "ERROR: [x] y: Unable to download webpage: <urlopen error [Errno 8] nodename nor servname provided>":
                dl.NETWORK_ERROR,
            "ERROR: [youtube] y: HTTP Error 429: Too Many Requests": dl.RATE_LIMITED,
            "ERROR: [facebook] 1: Cannot parse data; please report this issue":
                "Dlr couldn't read this page: the site may have changed. Try again later (Dlr updates itself).",
        }
        for raw, expected in cases.items():
            self.assertEqual(dl.friendly_error(Exception(raw)), expected, raw)

    def test_no_install_commands(self):
        for _, text in dl._ERRORS:
            self.assertNotIn("brew", text)
            self.assertNotIn("winget", text)

    def test_long_unknown_errors_are_hidden(self):
        self.assertEqual(dl.friendly_error(Exception("x" * 500)), "Something went wrong. Try again in a few minutes.")

    def test_reddit_403_needs_login(self):
        e = Exception("HTTP Error 403: Forbidden")
        self.assertTrue(dl.needs_login(e, "https://www.reddit.com/r/a/comments/b/"))
        self.assertFalse(dl.needs_login(e, "https://www.youtube.com/watch?v=a"))

    def test_other_format_only_for_format_problems(self):
        self.assertTrue(dl._try_other_format(Exception("HTTP Error 403: Forbidden")))
        self.assertTrue(dl._try_other_format(Exception("ERROR: something unexpected happened")))
        self.assertFalse(dl._try_other_format(Exception("Video unavailable")))
        self.assertFalse(dl._try_other_format(Exception("getaddrinfo failed")))


class LoginRetryTest(unittest.TestCase):
    def test_logins_off_says_so(self):
        cases = {
            ("https://www.reddit.com/r/a/comments/b/", "ERROR: [Reddit] x: Account authentication is required"):
                "Reddit needs login — turn on logins in settings",
            ("https://www.instagram.com/p/BsOGulcndj-/", "AbortExtraction: HTTP redirect to login page"):
                "This Instagram post needs login — turn on logins in settings",
            ("https://example.com/v/1", "ERROR: [generic] 1: login required"):
                "This site needs login — turn on logins in settings",
        }
        for (url, raw), expected in cases.items():
            def run(extra, raw=raw):
                self.assertEqual(extra, {})  # logins off: cookies are never read
                raise Exception(raw)
            with self.assertRaises(dl.EngineError) as cm:
                dl.with_login_retry(run, "off", url=url)
            self.assertEqual(str(cm.exception), expected)
            self.assertTrue(dl.is_login_message(str(cm.exception)))  # no update-and-retry for these

    def test_login_retry_uses_browser(self):
        calls = []

        def run(extra):
            calls.append(extra)
            if not extra:
                raise Exception("login required")
            return "ok"
        self.assertEqual(dl.with_login_retry(run, "firefox", url="https://www.instagram.com/p/a/"), "ok")
        self.assertEqual(calls, [{}, {"cookiesfrombrowser": ("firefox",)}])

    def test_instagram_rate_limit_waits_and_retries_once(self):
        calls, waits = [], []

        def run(extra):
            calls.append(extra)
            if len(calls) == 1:
                raise Exception("HTTP Error 429: Too Many Requests")
            return "ok"
        result = dl.with_login_retry(run, "off", url="https://www.instagram.com/reel/a/", wait=waits.append)
        self.assertEqual(result, "ok")
        self.assertEqual(waits, [dl.INSTAGRAM_WAIT])
        self.assertEqual(len(calls), 2)

    @mock.patch("socket.getaddrinfo", return_value=PUBLIC)
    def test_stories_need_login(self, _):
        url = "https://www.instagram.com/stories/someone/123/"
        with self.assertRaises(dl.DownloaderError) as cm:
            dl._resolved(url, "off")
        self.assertEqual(str(cm.exception), "Stories need login — turn on logins in settings")


class ToolsTest(unittest.TestCase):
    def test_missing_tools_never_suggests_homebrew(self):
        with mock.patch("downloader.find_ffmpeg", return_value=None), \
                mock.patch("downloader.find_deno", return_value=None):
            missing = dl.missing_tools()
        self.assertEqual([t["name"] for t in missing], ["FFmpeg", "Deno"])
        for tool in missing:
            self.assertNotIn("brew", str(tool))
            self.assertNotIn("winget", str(tool))

    def test_packaged_app_uses_only_its_own_deno(self):
        with mock.patch.object(dl.sys, "frozen", True, create=True), \
                mock.patch.object(dl.sys, "_MEIPASS", "/nonexistent", create=True):
            self.assertIsNone(dl.find_deno())

    def test_deno_leaves_nothing_behind(self):
        # A private temporary folder (removed at exit), never ~/Library/Caches/deno.
        self.assertTrue(os.path.basename(os.environ.get("DENO_DIR", "")).startswith("dlr-deno-"))
        self.assertEqual(os.environ.get("DENO_NO_UPDATE_CHECK"), "1")


class FolderTest(unittest.TestCase):
    def test_move_dir_into_never_reuses_a_folder(self):
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, "Post [1]"))
            src = os.path.join(root, "a.jpg")
            open(src, "w").close()
            final = safety.move_dir_into(root, "Post [1]", [(src, "01.jpg")])
            self.assertEqual(os.path.basename(final), "Post [1] (2)")
            self.assertEqual(os.listdir(final), ["01.jpg"])

    def test_move_dir_into_cleans_names(self):
        with tempfile.TemporaryDirectory() as root:
            src = os.path.join(root, "a.jpg")
            open(src, "w").close()
            final = safety.move_dir_into(root, "Post", [(src, "../../evil.jpg")])
            self.assertEqual(os.listdir(final), ["evil.jpg"])


if __name__ == "__main__":
    unittest.main()
