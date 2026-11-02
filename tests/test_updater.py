"""Verified updates (yt-dlp from GitHub, gallery-dl from PyPI) and Deno's checksum. Offline."""
import hashlib
import importlib.util
import io
import unittest
import zipfile
from pathlib import Path

import updater

ROOT = Path(__file__).resolve().parent.parent


def zipped(path: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(path, text)
    return buf.getvalue()


class YtdlpTest(unittest.TestCase):
    def test_good_release(self):
        data = zipped("yt_dlp/version.py", "__version__ = '2026.11.01'\n")
        sums = f"{hashlib.sha256(data).hexdigest()}  yt-dlp\n"
        self.assertEqual(updater.verify(data, sums, "2026.11.01"), hashlib.sha256(data).hexdigest())

    def test_one_changed_byte_is_rejected(self):
        data = zipped("yt_dlp/version.py", "__version__ = '2026.11.01'\n")
        sums = f"{hashlib.sha256(data).hexdigest()}  yt-dlp\n"
        with self.assertRaises(updater.UpdateError):
            updater.verify(data[:-1] + bytes([data[-1] ^ 1]), sums, "2026.11.01")

    def test_wrong_version_inside_is_rejected(self):
        data = zipped("yt_dlp/version.py", "__version__ = '2020.01.01'\n")
        sums = f"{hashlib.sha256(data).hexdigest()}  yt-dlp\n"
        with self.assertRaises(updater.UpdateError):
            updater.verify(data, sums, "2026.11.01")


class GalleryDlTest(unittest.TestCase):
    def test_good_release(self):
        data = zipped("gallery_dl/version.py", '__version__ = "1.33.0"\n')
        digest = hashlib.sha256(data).hexdigest()
        self.assertEqual(updater.verify_gallery_dl(data, digest, "1.33.0"), digest)

    def test_checksum_mismatch_is_rejected(self):
        data = zipped("gallery_dl/version.py", '__version__ = "1.33.0"\n')
        with self.assertRaises(updater.UpdateError):
            updater.verify_gallery_dl(data, "0" * 64, "1.33.0")

    def test_wrong_version_inside_is_rejected(self):
        data = zipped("gallery_dl/version.py", '__version__ = "1.0.0"\n')
        with self.assertRaises(updater.UpdateError):
            updater.verify_gallery_dl(data, hashlib.sha256(data).hexdigest(), "1.33.0")

    def test_only_pypi(self):
        self.assertTrue(updater._allowed_pypi("https://files.pythonhosted.org/packages/x.whl"))
        self.assertTrue(updater._allowed_pypi("https://pypi.org/pypi/gallery-dl/json"))
        self.assertFalse(updater._allowed_pypi("http://pypi.org/pypi/gallery-dl/json"))
        self.assertFalse(updater._allowed_pypi("https://pypi.org.evil.com/x"))
        self.assertFalse(updater._allowed("https://pypi.org/pypi/gallery-dl/json"))  # yt-dlp: GitHub only

    def test_versions(self):
        self.assertGreater(updater.gdl_vtuple("1.33.0"), updater.gdl_vtuple("1.32.19"))
        self.assertEqual(updater.gdl_vtuple("1.33.0rc1"), ())


class DenoChecksumTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("get_deno", ROOT / "packaging" / "get_deno.py")
        self.get_deno = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.get_deno)

    def test_sha256sum_line(self):
        h = "9f0bf660393da2eaff044cdc7444cb08c73f235849b61d224d825a194ce7c98e"
        self.assertEqual(self.get_deno.expected_sha256(f"{h}  deno-aarch64-apple-darwin.zip\n",
                                                       "deno-aarch64-apple-darwin.zip"), h)

    def test_powershell_table(self):
        text = ("\nAlgorithm : SHA256\nHash      : CBA84B26E0DF5AE7F74FC66B86A95B866872A86292EBD84FA1E959927EDD93BF\n"
                "Path      : C:\\a\\deno\\deno\\target\\release\\deno-x86_64-pc-windows-msvc.zip\n")
        self.assertEqual(self.get_deno.expected_sha256(text, "deno-x86_64-pc-windows-msvc.zip"),
                         "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf")

    def test_other_file_is_refused(self):
        with self.assertRaises(SystemExit):
            self.get_deno.expected_sha256("ab" * 32 + "  deno-x86_64-apple-darwin.zip\n", "deno-aarch64-apple-darwin.zip")


if __name__ == "__main__":
    unittest.main()
