"""Link rules: sites, share links, tracking parameters, and redirect checks. Offline."""
import socket
import unittest
from unittest import mock

import links
import safety

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]


@mock.patch("socket.getaddrinfo", return_value=PUBLIC)
class LinksTest(unittest.TestCase):
    def test_site(self, _):
        self.assertEqual(links.site("https://vm.tiktok.com/ZS123/"), "tiktok")
        self.assertEqual(links.site("https://www.instagram.com/p/abc/"), "instagram")
        self.assertEqual(links.site("https://redd.it/abc"), "reddit")
        self.assertEqual(links.site("https://v.redd.it/abc"), "reddit")
        self.assertEqual(links.site("https://x.com/a/status/1"), "x")
        self.assertEqual(links.site("https://example.com/"), "")
        self.assertEqual(links.site("https://notreddit.com/"), "")

    def test_clean_drops_tracking(self, _):
        self.assertEqual(links.clean("https://www.instagram.com/reel/abc/?igsh=xyz"),
                         "https://www.instagram.com/reel/abc/")
        self.assertEqual(links.clean("https://www.tiktok.com/@a/video/1?_t=8&_r=1&_d=sec&u_code=x&timestamp=9&lang=en"),
                         "https://www.tiktok.com/@a/video/1?lang=en")
        # YouTube's start time stays; its share tracker goes.
        self.assertEqual(links.clean("https://youtu.be/abc?si=zz&t=30"), "https://youtu.be/abc?t=30")
        self.assertEqual(links.clean("https://www.youtube.com/watch?v=abc&list=PL1"),
                         "https://www.youtube.com/watch?v=abc&list=PL1")

    def test_share_links(self, _):
        for url in ("https://vm.tiktok.com/ZGdm3K8rk/", "https://vt.tiktok.com/ZS4ghQ5py/",
                    "https://www.tiktok.com/t/ZTRC5xgJp", "https://www.instagram.com/share/reel/_gdkGEJBn",
                    "https://www.instagram.com/share/_a7bsO89b", "https://www.reddit.com/r/cats/s/mqNof1kbPG",
                    "https://redd.it/6rrwyj", "https://spotify.link/abc"):
            self.assertTrue(links.is_share_link(url), url)
        for url in ("https://www.tiktok.com/@a/video/1", "https://www.instagram.com/p/abc/",
                    "https://www.reddit.com/r/cats/comments/abc/x/"):
            self.assertFalse(links.is_share_link(url), url)

    def test_resolve_follows_share_link(self, _):
        with mock.patch("links._follow", return_value="https://www.instagram.com/reel/DJvkjAlvNc8/?igsh=abc"):
            self.assertEqual(links.resolve("https://www.instagram.com/share/reel/_gdkGEJBn"),
                             "https://www.instagram.com/reel/DJvkjAlvNc8/")

    def test_resolve_login_page_names_the_post(self, _):
        login = "https://www.instagram.com/accounts/login/?next=%2Freel%2FDJvkjAlvNc8%2F"
        with mock.patch("links._follow", return_value=login):
            self.assertEqual(links.resolve("https://www.instagram.com/share/reel/_gdkGEJBn"),
                             "https://www.instagram.com/reel/DJvkjAlvNc8/")

    def test_resolve_keeps_original_when_offline(self, _):
        with mock.patch("links._follow", side_effect=OSError):
            self.assertEqual(links.resolve("https://vm.tiktok.com/ZGdm3K8rk/"), "https://vm.tiktok.com/ZGdm3K8rk/")

    def test_redirect_to_local_network_is_refused(self, _):
        handler = links._CheckedRedirects()
        for target in ("http://127.0.0.1/admin", "http://192.168.1.1/", "http://localhost:8080/"):
            with self.assertRaises(safety.UnsafeInput):
                handler.redirect_request(None, None, 302, "Found", {}, target)

    def test_resolve_refuses_local_hop(self, _):
        with mock.patch("links._follow", side_effect=safety.UnsafeInput("no")):
            with self.assertRaises(safety.UnsafeInput):
                links.resolve("https://vm.tiktok.com/ZGdm3K8rk/")

    def test_photos_and_stories(self, _):
        self.assertTrue(links.is_photo_link("https://www.tiktok.com/@a/photo/7266832970353233185"))
        self.assertTrue(links.is_photo_link("https://www.reddit.com/gallery/abc"))
        self.assertTrue(links.is_photo_link("https://i.redd.it/abc.jpg"))
        self.assertFalse(links.is_photo_link("https://www.tiktok.com/@a/video/1"))
        self.assertTrue(links.is_story("https://www.instagram.com/stories/someone/123/"))
        self.assertTrue(links.is_story("https://www.instagram.com/stories/highlights/18090946048123978/"))
        self.assertFalse(links.is_story("https://www.instagram.com/p/abc/"))


if __name__ == "__main__":
    unittest.main()
