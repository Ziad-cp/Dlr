"""Security rules: the page's bridge, links, network, files, images, logins and messages. Offline."""
import io
import os
import socket
import tempfile
import unittest
import urllib.request
import warnings
from pathlib import Path
from unittest import mock

import webview

import app
import downloader as dl
import gallery
import safety

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]
LOCAL = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]


class BridgeTest(unittest.TestCase):
    """The page can call only the listed functions, by exact name."""

    def setUp(self):
        self.api = app.Api.__new__(app.Api)  # no threads, network or clipboard
        self.window = app.create_window(self.api)
        self.addCleanup(lambda: webview.windows.remove(self.window) if self.window in webview.windows else None)

    def test_only_the_listed_functions(self):
        self.assertIsNone(self.window._js_api)  # nothing pywebview could walk through with getattr
        self.assertEqual(set(self.window._functions), set(app.Api.PAGE_FUNCTIONS))

    def test_private_parts_cant_be_reached(self):
        # How pywebview finds a function the page names: exposed names first, then getattr on
        # js_api for each part of "a.b.c". With no js_api, nothing else is reachable.
        def lookup(name):
            found = self.window._functions.get(name)
            if found:
                return found
            obj = self.window._js_api
            for part in name.split("."):
                obj = getattr(obj, part, None)
                if obj is None:
                    return None
            return obj
        for name in ("_cfg.update", "_downloader.add", "_window.evaluate_js", "_save",
                     "fetch.__func__", "__class__.__init__.__globals__.update", "info.__globals__"):
            self.assertIsNone(lookup(name), name)

    def test_page_functions_run_no_commands(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.", source)

    def test_bad_arguments_get_a_plain_message(self):
        api = app.Api.__new__(app.Api)
        api._downloader = mock.Mock()
        self.assertEqual(api.cancel("1; rm -rf /"), {"error": "That request isn't valid."})
        api._downloader.cancel.assert_not_called()
        self.assertEqual(api.set_browser("../../etc"), {"error": "That request isn't valid."})


@mock.patch("socket.getaddrinfo", return_value=PUBLIC)
class LinkTest(unittest.TestCase):
    def test_options_are_never_links(self, _):
        for text in ("-x", "--exec=touch /tmp/x", "-https://www.youtube.com/watch?v=1", " --version"):
            with self.assertRaises(safety.UnsafeInput, msg=text):
                safety.check_url(text)

    def test_only_web_links(self, _):
        for text in ("file:///etc/passwd", "javascript:alert(1)", "ftp://example.com/x", "data:text/html,x",
                     "https://user:pw@example.com/", "http://127.0.0.1/", "http://[::1]/", "http://192.168.1.1/x",
                     "https://localhost/", "https://printer.local/"):
            with self.assertRaises(safety.UnsafeInput, msg=text):
                safety.check_url(text)
        self.assertEqual(safety.check_url("youtube.com/watch?v=1"), "https://youtube.com/watch?v=1")

    def test_gallery_dl_gets_the_link_after_double_dash(self, _):
        with tempfile.TemporaryDirectory() as work:
            args = gallery.command("https://www.instagram.com/p/abc/", work, None)
            self.assertEqual(args[-2:], ["--", "https://www.instagram.com/p/abc/"])
            for bad in ("-o", "--exec=x", "file:///etc/passwd"):
                with self.assertRaises(ValueError):
                    gallery.command(bad, work, None)

    def test_spotify_matches_must_be_youtube(self, _):
        self.assertEqual(dl._youtube_link("https://www.youtube.com/watch?v=abc"), "https://www.youtube.com/watch?v=abc")
        for url in ("https://example.com/x", "-x", "file:///etc/passwd"):
            with self.assertRaises(dl.DownloaderError):
                dl._youtube_link(url)


class NetworkGuardTest(unittest.TestCase):
    """Connections are checked when they're made: redirects and DNS rebinding included."""

    def setUp(self):
        answers = {"public.example": PUBLIC, "rebind.example": LOCAL, "mixed.example": LOCAL + PUBLIC}
        self.real = socket.getaddrinfo
        socket.getaddrinfo = lambda host, port, *a, **k: answers.get(host, PUBLIC)
        self.addCleanup(self.restore)
        safety._original_getaddrinfo = None
        safety.install_network_guard()

    def restore(self):
        socket.getaddrinfo = self.real
        safety._original_getaddrinfo = None

    def test_local_answers_are_refused(self):
        with self.assertRaises(OSError):
            socket.getaddrinfo("rebind.example", 443)
        self.assertEqual(socket.getaddrinfo("mixed.example", 443), PUBLIC)  # only the public address
        self.assertEqual(socket.getaddrinfo("public.example", 443), PUBLIC)

    def test_no_proxy_setting_doesnt_open_localhost(self):
        self.restore()
        socket.getaddrinfo = lambda host, port, *a, **k: LOCAL
        self.addCleanup(self.restore)
        with mock.patch("urllib.request.getproxies", return_value={"no": "localhost,127.0.0.1",
                                                                   "https": "http://proxy.lan:3128"}):
            safety.install_network_guard()
        with self.assertRaises(OSError):
            socket.getaddrinfo("localhost", 80)
        self.assertEqual(socket.getaddrinfo("proxy.lan", 3128), LOCAL)  # the Mac's own proxy

    def test_link_check_still_explains_why(self):
        with self.assertRaises(safety.UnsafeInput) as cm:
            safety.check_url("https://rebind.example/video")
        self.assertIn("local network", str(cm.exception))
        self.assertEqual(dl.friendly_error(OSError("[Errno 8] Links to this computer or your local network "
                                                   "aren't allowed.")), dl.LOCAL_NETWORK)


@mock.patch("socket.getaddrinfo", return_value=PUBLIC)
class FetchTest(unittest.TestCase):
    """What Dlr downloads itself: checked redirects, no cookies, size and pixel limits."""

    def test_redirects_drop_cookies_and_logins(self, _):
        req = urllib.request.Request("https://public.example/a", headers={"Cookie": "sid=1", "Authorization": "x",
                                                                          "User-Agent": "Mozilla/5.0"})
        new = safety.CheckedRedirects().redirect_request(req, None, 302, "Found", {}, "https://cdn.example/b")
        self.assertFalse(new.has_header("Cookie"))
        self.assertFalse(new.has_header("Authorization"))
        self.assertEqual(new.full_url, "https://cdn.example/b")

    def test_redirect_hops_are_checked(self, _):
        for target in ("http://127.0.0.1/", "file:///etc/passwd", "http://10.0.0.1/"):
            with self.assertRaises(safety.UnsafeInput):
                safety.CheckedRedirects().redirect_request(urllib.request.Request("https://public.example/"),
                                                           None, 302, "Found", {}, target)

    def test_too_large_is_refused_before_reading(self, _):
        response = mock.Mock(headers={"Content-Length": str(safety.MAX_DOWNLOAD_BYTES + 1)})
        with self.assertRaises(safety.UnsafeInput):
            safety.read_limited(response)
        response.read.assert_not_called()
        small = mock.Mock(headers={}, read=lambda n: b"x" * (safety.MAX_DOWNLOAD_BYTES + 1))
        with self.assertRaises(safety.UnsafeInput):
            safety.read_limited(small)

    def test_images_over_the_pixel_limit_are_refused(self, _):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (40, 30)).save(buf, "PNG")
        with mock.patch.object(safety, "MAX_IMAGE_PIXELS", 1000), warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            self.assertEqual(dl.image_size(buf.getvalue()), (0, 0))
            with mock.patch.object(dl, "fetch_image", return_value=buf.getvalue()):
                self.assertEqual(dl.thumbnail_data_url("https://public.example/t.png"), "")
        self.assertEqual(dl.image_size(buf.getvalue()), (40, 30))

    def test_photo_headers_never_carry_cookies(self, _):
        seen = {}

        class Response(io.BytesIO):
            headers = {}

            def geturl(self):
                return "https://public.example/p.jpg"

        def fake_open(url, headers=None, timeout=15):
            seen.update(headers)
            return Response(b"jpeg")
        with tempfile.TemporaryDirectory() as work, mock.patch.object(safety, "open_url", side_effect=fake_open):
            dl._fetch_file("https://public.example/p.jpg", os.path.join(work, "p.jpg"),
                           {"Cookie": "sessionid=1", "Referer": "https://www.instagram.com/", "X-Token": "t"})
        self.assertNotIn("Cookie", seen)
        self.assertNotIn("X-Token", seen)
        self.assertEqual(seen["Referer"], "https://www.instagram.com/")


class LoginTest(unittest.TestCase):
    def test_gallery_dl_reads_only_the_sites_cookies(self):
        with tempfile.TemporaryDirectory() as work:
            args = gallery.command("https://www.instagram.com/p/abc/", work, None, "chrome")
            self.assertIn("chrome/.instagram.com", args)
            with self.assertRaises(ValueError):
                gallery.command("https://www.instagram.com/p/abc/", work, None, "chrome/.evil.com")

    def test_cookies_are_never_saved(self):
        opts = dl.build_opts("best", "/tmp")
        self.assertNotIn("cookiefile", opts)
        self.assertFalse(opts["cachedir"])
        config = gallery._config("/tmp/work", None)
        self.assertEqual(config["cache"]["file"], ":memory:")
        self.assertIsNone(config["output"]["logfile"])


class FileTest(unittest.TestCase):
    def test_names_from_titles_stay_inside_the_folder(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.realpath(root)
            for title in ("../../etc/passwd", "/etc/hosts", "..", ".hidden", "a/b\\c:d", "‮exe.mp4", "x" * 400):
                src = os.path.join(folder, "src")
                open(src, "w").close()
                final = safety.move_into(folder, src, title, "/../../x")
                self.assertEqual(os.path.dirname(final), folder, title)
                self.assertFalse(os.path.basename(final).startswith("."), title)
                self.assertTrue(final.endswith(".bin"), title)

    def test_existing_files_and_symlinks_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as elsewhere:
            folder = os.path.realpath(root)
            target = os.path.join(elsewhere, "victim.txt")
            Path(target).write_text("keep", encoding="utf-8")
            os.symlink(target, os.path.join(folder, "Video.mp4"))
            src = os.path.join(folder, "src")
            Path(src).write_text("new", encoding="utf-8")
            final = safety.move_into(folder, src, "Video", ".mp4")
            self.assertEqual(os.path.basename(final), "Video (2).mp4")
            self.assertEqual(Path(target).read_text(encoding="utf-8"), "keep")


class MessageTest(unittest.TestCase):
    """Errors never show file paths, user names or cookies."""

    def test_paths_and_cookies_are_removed(self):
        home = os.path.expanduser("~")
        raw = (f"ERROR: unable to open for writing: [Errno 13] Permission denied: '{home}/Downloads/.vd-abc/a b.mp4' "
               "Cookie: sessionid=abc123; csrftoken=xyz")
        shown = dl.friendly_error(Exception(raw[:190]))
        self.assertNotIn(home, shown)
        self.assertNotIn("Downloads", shown)
        text = safety.scrub(raw)
        for secret in (home, "abc123", "xyz", ".vd-abc"):
            self.assertNotIn(secret, text)
        self.assertEqual(safety.scrub("HTTP Error 403: Forbidden"), "HTTP Error 403: Forbidden")

    def test_job_errors_are_scrubbed(self):
        job = dl.Job(1, "https://example.com/v", "best", "/tmp")
        downloader = dl.Downloader.__new__(dl.Downloader)
        downloader._cancelled, downloader._listeners = set(), []
        downloader._queue = mock.Mock(get=mock.Mock(side_effect=[job, SystemExit]))
        downloader._run = mock.Mock(side_effect=dl.DownloaderError(f"Couldn't save {os.path.expanduser('~')}/x.mp4"))
        downloader._retry_after_update = mock.Mock(return_value=False)
        with self.assertRaises(SystemExit):
            downloader._worker()
        self.assertEqual(job.status, "error")
        self.assertNotIn(os.path.expanduser("~"), job.error)


class PageTest(unittest.TestCase):
    """Text from the internet is never inserted into the page as HTML."""

    def test_internet_text_uses_textContent_or_esc(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        for field in ("title", "uploader", "duration", "siteName"):
            self.assertIn(f"el.{field}.textContent", js)
        self.assertNotIn("el.title.innerHTML", js)
        self.assertNotIn("insertAdjacentHTML", js)
        self.assertNotIn("document.write", js)
        self.assertNotIn("eval(", js)

    def test_strict_content_security_policy(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        for rule in ("default-src 'none'", "img-src data:", "connect-src 'none'", "object-src 'none'",
                     "frame-src 'none'", "base-uri 'none'", "form-action 'none'"):
            self.assertIn(rule, html)
        self.assertNotIn("unsafe-inline", html)


if __name__ == "__main__":
    unittest.main()
