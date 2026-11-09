"""Verified updates (yt-dlp from GitHub, signature-checked; gallery-dl from PyPI) and the pinned
FFmpeg and Deno. Offline."""
import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import pgp
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


FIXTURES = ROOT / "tests" / "fixtures" / "ytdlp-2026.10.26"


def _mpi(n: int) -> bytes:
    return n.bit_length().to_bytes(2, "big") + n.to_bytes((n.bit_length() + 7) // 8, "big")


def other_key() -> str:
    """An armored RSA public key that isn't yt-dlp's."""
    body = b"\x04" + (1700000000).to_bytes(4, "big") + b"\x01" + _mpi((1 << 4095) + 12345) + _mpi(65537)
    packet = bytes([0xC6, ((len(body) - 192) >> 8) + 192, (len(body) - 192) & 0xFF]) + body
    import base64
    return ("-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n" + base64.b64encode(packet).decode()
            + "\n-----END PGP PUBLIC KEY BLOCK-----\n")


class SignatureTest(unittest.TestCase):
    """yt-dlp's SHA2-256SUMS must carry a valid signature from its pinned release key."""

    def setUp(self):
        self.sums = (FIXTURES / "SHA2-256SUMS").read_bytes()
        self.sig = (FIXTURES / "SHA2-256SUMS.sig").read_bytes()

    def test_real_release_signature(self):
        self.assertEqual(updater.verify_signature(self.sums, self.sig), pgp.YTDLP_FINGERPRINT)

    def test_pinned_key_matches_its_fingerprint(self):
        self.assertEqual(pgp.primary_fingerprint(pgp.YTDLP_PUBLIC_KEY), "AC0CBBE6848D6A873464AF4E57CF65933B5A7581")

    def test_changed_checksum_list_is_rejected(self):
        changed = self.sums.replace(b"  yt-dlp\n", b"  yt-dlp \n", 1)
        with self.assertRaises(updater.UpdateError):
            updater.verify_signature(changed, self.sig)
        flipped = bytes([self.sums[0] ^ 1]) + self.sums[1:]
        with self.assertRaises(updater.UpdateError):
            updater.verify_signature(flipped, self.sig)

    def test_damaged_or_missing_signature_is_rejected(self):
        for sig in (b"", self.sig[:-1], self.sig[:-3] + bytes([self.sig[-3] ^ 1]) + self.sig[-2:], b"not a signature"):
            with self.assertRaises(updater.UpdateError):
                updater.verify_signature(self.sums, sig)

    def test_other_key_is_refused(self):
        key = other_key()
        with self.assertRaises(pgp.BadSignature):
            pgp.verify(self.sums, self.sig, key, pgp.primary_fingerprint(key))
        with self.assertRaises(pgp.BadSignature):  # a swapped key block doesn't match the pinned fingerprint
            pgp.verify(self.sums, self.sig, key, pgp.YTDLP_FINGERPRINT)


def fake_release(tag: str, signature: bytes, sums: bytes = None):
    data = zipped("yt_dlp/version.py", f"__version__ = '{tag}'\n")
    sums = sums if sums is not None else f"{hashlib.sha256(data).hexdigest()}  yt-dlp\n".encode()
    files = {"SHA2-256SUMS": sums, "SHA2-256SUMS.sig": signature, "yt-dlp": data}

    def get(url, limit, method="GET", **kw):
        if url.endswith("/latest"):
            return f"https://github.com/yt-dlp/yt-dlp/releases/tag/{tag}", b""
        return url, files[url.rsplit("/", 1)[-1]]
    return get


class InstallTest(unittest.TestCase):
    """A release whose checksum list isn't signed by yt-dlp's key is never installed."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        names = {"UPDATE_DIR": self.dir, "ZIP": self.dir / "yt-dlp.zip", "MANIFEST": self.dir / "manifest.json",
                 "STATE": self.dir / "state.json", "SUMS": self.dir / "SHA2-256SUMS",
                 "SIGNATURE": self.dir / "SHA2-256SUMS.sig"}
        for name, value in names.items():
            patcher = mock.patch.object(updater, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(updater.active, {"version": "2026.10.26", "pending": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unsigned_release_is_not_installed(self):
        sig = (FIXTURES / "SHA2-256SUMS.sig").read_bytes()  # signs a different list
        with mock.patch.object(updater, "_get", side_effect=fake_release("2026.12.01", sig)):
            changed, message = updater.install_latest()
        self.assertFalse(changed)
        self.assertIn("isn't signed by yt-dlp's release key", message)
        self.assertFalse((self.dir / "yt-dlp.zip").exists())
        self.assertFalse((self.dir / "manifest.json").exists())

    def test_saved_update_without_its_signature_is_not_used(self):
        data = zipped("yt_dlp/version.py", "__version__ = '2026.12.01'\n")
        (self.dir / "yt-dlp.zip").write_bytes(data)
        (self.dir / "manifest.json").write_text(json.dumps(
            {"version": "2026.12.01", "sha256": hashlib.sha256(data).hexdigest()}), encoding="utf-8")
        with mock.patch.object(updater.sys, "frozen", True, create=True), \
                mock.patch.object(updater, "builtin_version", return_value="2026.10.26"):
            active = updater.activate()
        self.assertEqual(active["source"], "built-in")
        self.assertIn("couldn't be verified", active["note"])
        self.assertFalse((self.dir / "yt-dlp.zip").exists())


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BundledToolsTest(unittest.TestCase):
    """FFmpeg and Deno: pinned versions, pinned SHA-256s, official addresses only."""

    def test_deno_is_pinned(self):
        get_deno = _load("get_deno")
        self.assertRegex(get_deno.VERSION, r"^\d+\.\d+\.\d+$")
        self.assertRegex(get_deno.SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(get_deno.URL, f"https://github.com/denoland/deno/releases/download/v{get_deno.VERSION}/"
                                       "deno-aarch64-apple-darwin.zip")
        self.assertTrue(get_deno._allowed("https://objects.githubusercontent.com/x"))
        for url in ("http://github.com/x", "https://github.com.evil.com/x", "https://example.com/deno.zip"):
            self.assertFalse(get_deno._allowed(url), url)

    def test_ffmpeg_is_pinned(self):
        get_ffmpeg = _load("get_ffmpeg")
        self.assertRegex(get_ffmpeg.VERSION, r"^\d+\.\d+(\.\d+)?$")
        self.assertEqual(set(get_ffmpeg.FILES), {"ffmpeg", "ffprobe"})
        for digest in get_ffmpeg.FILES.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertNotIn("latest", get_ffmpeg.URL)
        self.assertIn(get_ffmpeg.VERSION, get_ffmpeg.URL)
        self.assertTrue(get_ffmpeg._allowed("https://ffmpeg.martin-riedl.de/download/x.zip"))
        for url in ("http://ffmpeg.martin-riedl.de/x", "https://ffmpeg.martin-riedl.de.evil.com/x"):
            self.assertFalse(get_ffmpeg._allowed(url), url)


if __name__ == "__main__":
    unittest.main()
