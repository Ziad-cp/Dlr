"""The OpenPGP verifier that guards every yt-dlp update (pgp.py). Offline.

Bad signatures are crafted with a throwaway test key, so each one is correctly signed and has
exactly one flaw: if the verifier accepted it, it would be because that one check is missing.
"""
import base64
import hashlib
import random
import time
import unittest
from pathlib import Path

import pgp

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ytdlp-2026.10.26"

# Throwaway RSA keys made only for these tests (2048-bit, and a too-small 1024-bit one).
TEST_N = int(
    "87a52c60f406ce3a4403c89c333b6d00ba7b8e725d6591c69721bcb8e77f8c3e17bc782c489a3c0aacc654fc"
    "bbe8d7679048eb5495cb5dea4fbbf64609d33fb48aef9ffb41393391d3a249c7d83a73a082f1521512f48815"
    "dbb0b3c3465691f5ff0101e83455997a2c25b0688c7a258a0c146775191756d40dad8de5c5e53c72798b26c3"
    "aa747e624f089ac1270ade3b8fe3eedf5c7fb488acfb6419419bd9bb461be06f7b678a13ff693590a1f62b48"
    "524ced2bfd89bde0b350a577993a18535010764341c4639435621d4b8000d4c3c56a54f4d08d3e48c4cbc201"
    "1ef1075a8f56cb2841ad82ba4eb2f4e41989289ff7882fff3453bb9fd88ec74c7140f731", 16)
TEST_D = int(
    "d5882f5470d245d3733e818f63172980fc0f852e83d860a33f46dcd0379d92282d3583f832529a3233ca03ff"
    "d7cfb34854da759bb23372a468e07bcfc5a7c7a16f15c9c2bdea4e4441e438416122a2e30b3ed8f853de9e5b"
    "ca7b60810739408cffe1961ef443cc578727cd8cc7978180cf834f5a0725b68a1afe1b629b254300a7796fdb"
    "dcba034776f15d6a8344a0e20819ea301ed828e96b54411d14a2ef0ec4979c6e7108f915f0a790d6092c833c"
    "160d378664c4e990db8283b3746589ce9e7924a647ea504114950a4a9632aa2774fec09618b64f0be4339ebd"
    "1ca4e721a8d712856af479f1e79aff294d9d63d2cc5e3da464a7c18d65257e0c680551", 16)
WEAK_N = int(
    "e38dfde94e3dd7a2b910dabff24653bb0bbb6f01dc6e4e80bece24190aa1a9008e31ecec56f80f8d596e29a9"
    "0ac204eb156ba21991b7024827709d9dd37d2bbd5be0003ba6b49afe3ffe0815c2ae188d6c9c6328c42daa43"
    "0652aca98312f2460d1241b3bb85844063e244b37b1c51c2ad6af8a593f6c7342dee19447b8eb057", 16)
WEAK_D = int(
    "449c1b62ace4988fc79cfd57c284d1da23bf6fc8efdd926ddf19e868647c39a8a1370c687610751ff946ede8"
    "ba05a5d5fbaf6840ad5eb0a170c2d3c332711b2e7b66e1737961cbb35359ba698f54321eef0b4f79ceca17b9"
    "e40544cf515c2e62263a61c454cfe0ae362ffd4779e21fddbb1bf233e7a51ee87f9a3f4c36c01a81", 16)

E = 65537
KEY_CREATED = 1_700_000_000
NOW = 1_800_000_000
DATA = b"e51e69e89489f199530f13d32a4342da3ddb2cf34842f364603a066db05afbf3  yt-dlp\n"
DIGEST_INFO = {
    1: bytes.fromhex("3020300c06082a864886f70d020505000410"),  # MD5
    2: bytes.fromhex("3021300906052b0e03021a05000414"),  # SHA-1
    8: bytes.fromhex("3031300d060960864801650304020105000420"),  # SHA-256
    10: bytes.fromhex("3051300d060960864801650304020305000440"),  # SHA-512
    11: bytes.fromhex("302d300d06096086480165030402040500041c"),  # SHA-224
}
HASHES = {1: "md5", 2: "sha1", 8: "sha256", 10: "sha512", 11: "sha224"}


def mpi(n: int) -> bytes:
    return n.bit_length().to_bytes(2, "big") + n.to_bytes((n.bit_length() + 7) // 8, "big")


def packet(tag: int, body: bytes) -> bytes:
    return bytes([0xC0 | tag, 0xFF]) + len(body).to_bytes(4, "big") + body


def sub(kind: int, value: bytes, critical: bool = False) -> bytes:
    assert len(value) + 1 < 192
    return bytes([len(value) + 1, kind | (0x80 if critical else 0)]) + value


def crc24(data: bytes) -> int:
    crc = 0xB704CE
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def armor(data: bytes) -> str:
    text = base64.b64encode(data).decode()
    lines = "\n".join(text[i:i + 64] for i in range(0, len(text), 64))
    crc = base64.b64encode(crc24(data).to_bytes(3, "big")).decode()
    return f"-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n{lines}\n={crc}\n-----END PGP PUBLIC KEY BLOCK-----\n"


class Key:
    def __init__(self, n=None, d=None, created=KEY_CREATED, algo=1):
        self.n, self.d = n or TEST_N, d or TEST_D
        self.body = b"\x04" + created.to_bytes(4, "big") + bytes([algo]) + mpi(self.n) + mpi(E)
        self.material = b"\x99" + len(self.body).to_bytes(2, "big") + self.body
        self.fpr = hashlib.sha1(self.material).digest()
        self.created = created

    def issuer(self) -> bytes:
        return sub(33, b"\x04" + self.fpr)

    def sign(self, hashed_input: bytes, hashed: bytes, unhashed: bytes = b"", sig_type=0x00,
             hash_algo=8, pub_algo=1, version=4, s=None, encode=mpi, left16=None) -> bytes:
        prefix = bytes([version, sig_type, pub_algo, hash_algo]) + len(hashed).to_bytes(2, "big") + hashed
        digest = hashlib.new(HASHES[hash_algo], hashed_input + prefix + b"\x04\xff"
                             + len(prefix).to_bytes(4, "big")).digest()
        k = (self.n.bit_length() + 7) // 8
        expected = DIGEST_INFO[hash_algo] + digest
        em = b"\x00\x01" + b"\xff" * (k - len(expected) - 3) + b"\x00" + expected
        s = pow(int.from_bytes(em, "big"), self.d, self.n) if s is None else s
        left16 = digest[:2] if left16 is None else left16
        return prefix + len(unhashed).to_bytes(2, "big") + unhashed + left16 + encode(s)

    def block(self, uid=b"Test <test@example.invalid>", key_flags=b"\x03", expires=None, extra=b"",
              self_sig=True) -> str:
        hashed = self.issuer() + sub(2, (self.created + 1).to_bytes(4, "big"))
        if key_flags is not None:
            hashed += sub(27, key_flags)
        if expires is not None:
            hashed += sub(9, (expires - self.created).to_bytes(4, "big"))
        cert = self.sign(self.material + b"\xb4" + len(uid).to_bytes(4, "big") + uid, hashed, sig_type=0x13)
        packets = packet(6, self.body) + packet(13, uid) + (packet(2, cert) if self_sig else b"") + extra
        return armor(packets)

    def fingerprint(self) -> str:
        return self.fpr.hex().upper()


KEY = Key()


def signed(data: bytes = DATA, key: Key = KEY, hashed: bytes = None, unhashed: bytes = None, **kw) -> bytes:
    if hashed is None:
        hashed = key.issuer() + sub(2, (NOW - 3600).to_bytes(4, "big"))
    if unhashed is None:
        unhashed = sub(16, key.fpr[-8:])
    return packet(2, key.sign(data, hashed, unhashed, **kw))


def check(sig: bytes, data: bytes = DATA, key: Key = KEY, block: str = None, now=NOW) -> str:
    return pgp.verify(data, sig, block or key.block(), key.fingerprint(), now=now)


class GoodSignatureTest(unittest.TestCase):
    """Positive controls: without them, the rejections below would prove nothing."""

    def test_crafted_signature_is_accepted(self):
        self.assertEqual(check(signed()), KEY.fingerprint())

    def test_real_yt_dlp_release_is_accepted(self):
        data, sig = (FIXTURES / "SHA2-256SUMS").read_bytes(), (FIXTURES / "SHA2-256SUMS.sig").read_bytes()
        self.assertEqual(pgp.verify(data, sig, pgp.YTDLP_PUBLIC_KEY, pgp.YTDLP_FINGERPRINT),
                         "AC0CBBE6848D6A873464AF4E57CF65933B5A7581")


class RejectTest(unittest.TestCase):
    def rejects(self, sig: bytes, **kw):
        with self.assertRaises(pgp.BadSignature):
            check(sig, **kw)

    # ---- hash algorithms ----
    def test_md5_sha1_sha224_are_refused(self):
        for algo in (1, 2, 11):
            self.rejects(signed(hash_algo=algo))

    def test_sha512_is_allowed(self):
        self.assertEqual(check(signed(hash_algo=10)), KEY.fingerprint())

    # ---- issuer ----
    def test_issuer_only_in_unhashed_area(self):
        hashed = sub(2, (NOW - 60).to_bytes(4, "big"))
        self.rejects(signed(hashed=hashed, unhashed=KEY.issuer() + sub(16, KEY.fpr[-8:])))

    def test_no_issuer_at_all(self):
        self.rejects(signed(hashed=sub(2, (NOW - 60).to_bytes(4, "big")), unhashed=b""))

    def test_issuer_fingerprint_of_another_key(self):
        other = Key(created=KEY_CREATED + 1)  # same RSA numbers, different fingerprint
        hashed = other.issuer() + sub(2, (NOW - 60).to_bytes(4, "big"))
        self.rejects(signed(hashed=hashed))

    def test_issuer_key_id_of_another_key(self):
        self.rejects(signed(unhashed=sub(16, b"\x01" * 8)))
        hashed = KEY.issuer() + sub(16, b"\x01" * 8) + sub(2, (NOW - 60).to_bytes(4, "big"))
        self.rejects(signed(hashed=hashed, unhashed=b""))

    def test_issuer_fingerprint_with_wrong_version(self):
        hashed = sub(33, b"\x05" + KEY.fpr) + sub(2, (NOW - 60).to_bytes(4, "big"))
        self.rejects(signed(hashed=hashed))

    def test_key_with_another_fingerprint_pinned(self):
        with self.assertRaises(pgp.BadSignature):
            pgp.verify(DATA, signed(), KEY.block(), "00" * 20, now=NOW)
        with self.assertRaises(pgp.BadSignature):  # yt-dlp's real pin, a different key block
            pgp.verify(DATA, signed(), KEY.block(), pgp.YTDLP_FINGERPRINT, now=NOW)

    def test_signature_by_a_subkey(self):
        subkey = Key(created=KEY_CREATED + 5)
        block = KEY.block(extra=packet(14, subkey.body))
        self.rejects(signed(key=subkey, hashed=subkey.issuer() + sub(2, (NOW - 60).to_bytes(4, "big"))),
                     block=block)

    # ---- signature type, version, algorithm ----
    def test_only_binary_documents(self):
        for sig_type in (0x01, 0x02, 0x10, 0x13, 0x18, 0x1F, 0x40):
            self.rejects(signed(sig_type=sig_type))

    def test_text_signature_of_same_text_is_refused(self):
        self.rejects(signed(data=DATA.replace(b"\n", b"\r\n"), sig_type=0x01))

    def test_other_versions(self):
        for version in (3, 5, 6):
            self.rejects(signed(version=version))

    def test_other_public_key_algorithm(self):
        for algo in (3, 16, 17, 22):
            self.rejects(signed(pub_algo=algo))

    # ---- times ----
    def test_missing_creation_time(self):
        self.rejects(signed(hashed=KEY.issuer()))

    def test_creation_time_only_unhashed(self):
        self.rejects(signed(hashed=KEY.issuer(), unhashed=sub(2, (NOW - 60).to_bytes(4, "big"))))

    def test_two_creation_times(self):
        hashed = KEY.issuer() + sub(2, (NOW - 60).to_bytes(4, "big")) + sub(2, (NOW - 30).to_bytes(4, "big"))
        self.rejects(signed(hashed=hashed))

    def test_created_in_the_future(self):
        self.rejects(signed(hashed=KEY.issuer() + sub(2, (NOW + 2 * 86400).to_bytes(4, "big"))))
        # a little clock difference is fine
        self.assertTrue(check(signed(hashed=KEY.issuer() + sub(2, (NOW + 600).to_bytes(4, "big")))))

    def test_created_before_the_key(self):
        self.rejects(signed(hashed=KEY.issuer() + sub(2, (KEY_CREATED - 1).to_bytes(4, "big"))))

    def test_expired_signature(self):
        hashed = KEY.issuer() + sub(2, (NOW - 7200).to_bytes(4, "big")) + sub(3, (3600).to_bytes(4, "big"))
        self.rejects(signed(hashed=hashed))
        hashed = KEY.issuer() + sub(2, (NOW - 7200).to_bytes(4, "big")) + sub(3, (86400).to_bytes(4, "big"))
        self.assertTrue(check(signed(hashed=hashed)))  # still within its lifetime

    def test_expired_key(self):
        self.rejects(signed(), block=KEY.block(expires=NOW - 60))
        self.assertTrue(check(signed(), block=KEY.block(expires=NOW + 86400)))

    def test_signature_made_after_the_key_expired(self):
        block = KEY.block(expires=NOW - 7200)
        self.rejects(signed(hashed=KEY.issuer() + sub(2, (NOW - 3600).to_bytes(4, "big"))), block=block, now=NOW)

    # ---- the pinned key itself ----
    def test_revoked_key(self):
        revocation = packet(2, KEY.sign(KEY.material, KEY.issuer() + sub(2, KEY_CREATED.to_bytes(4, "big")),
                                        sig_type=0x20))
        self.rejects(signed(), block=KEY.block(extra=revocation))

    def test_key_not_allowed_to_sign(self):
        self.rejects(signed(), block=KEY.block(key_flags=b"\x01"))

    def test_key_without_self_signature(self):
        self.rejects(signed(), block=KEY.block(self_sig=False))

    def test_key_with_forged_self_signature(self):
        block = KEY.block()
        raw = bytearray(pgp._dearmor(block))
        raw[-3] ^= 1  # inside the self-signature's RSA value
        self.rejects(signed(), block=armor(bytes(raw)))

    def test_damaged_armor_checksum(self):
        block = KEY.block()
        lines = block.splitlines()
        crc = next(i for i, line in enumerate(lines) if line.startswith("="))
        lines[crc] = "=AAAA"
        self.rejects(signed(), block="\n".join(lines) + "\n")

    def test_small_rsa_key(self):
        weak = Key(n=WEAK_N, d=WEAK_D)
        self.rejects(signed(key=weak, hashed=weak.issuer() + sub(2, (NOW - 60).to_bytes(4, "big")),
                            unhashed=b""), key=weak)

    # ---- packets ----
    def test_extra_packets(self):
        sig = signed()
        marker = packet(10, b"PGP")
        literal = packet(11, b"b\x00\x00\x00\x00\x00" + DATA)
        for bad in (sig + marker, marker + sig, literal + sig, sig + literal, sig + b"\x00", sig + b"\xc2"):
            self.rejects(bad)

    def test_two_signatures(self):
        self.rejects(signed() + signed())
        self.rejects(signed() + signed(hash_algo=10))

    def test_old_style_and_partial_lengths(self):
        body = signed()[6:]
        self.assertTrue(check(bytes([0x89]) + len(body).to_bytes(2, "big") + body))  # old format is fine
        self.rejects(bytes([0x8B]) + body)  # indeterminate length
        self.rejects(bytes([0xC2, 0xE5]) + body)  # partial length
        self.rejects(bytes([0xC2, 0xFF]) + (len(body) + 1).to_bytes(4, "big") + body)  # claims more

    def test_too_large(self):
        self.rejects(signed(unhashed=sub(16, KEY.fpr[-8:]) + sub(20, b"x" * 180) * 100))

    # ---- subpackets and numbers ----
    def test_unknown_critical_subpacket(self):
        hashed = KEY.issuer() + sub(2, (NOW - 60).to_bytes(4, "big")) + sub(99, b"x", critical=True)
        self.rejects(signed(hashed=hashed))
        self.rejects(signed(unhashed=sub(16, KEY.fpr[-8:]) + sub(99, b"x", critical=True)))
        self.rejects(signed(unhashed=sub(16, KEY.fpr[-8:]) + sub(99, b"x")))  # unsigned: refused too
        self.rejects(signed(unhashed=sub(16, KEY.fpr[-8:]) * 2))
        self.assertTrue(check(signed(unhashed=b"")))  # no unhashed data at all is fine
        hashed = KEY.issuer() + sub(2, (NOW - 60).to_bytes(4, "big")) + sub(99, b"x")
        self.assertTrue(check(signed(hashed=hashed)))  # unknown but not critical: ignored

    def test_malformed_subpacket_lengths(self):
        good = KEY.issuer() + sub(2, (NOW - 60).to_bytes(4, "big"))
        for bad in (good + b"\x05\x02\x00", good + b"\xc0", good + b"\xff\x00\x00", good + b"\x00",
                    good + b"\xff\xff\xff\xff\xff\x02"):
            self.rejects(signed(hashed=bad))
            self.rejects(signed(unhashed=bad))

    def test_wrong_sized_values(self):
        self.rejects(signed(hashed=KEY.issuer() + sub(2, (NOW - 60).to_bytes(5, "big"))))
        self.rejects(signed(hashed=sub(33, b"\x04" + KEY.fpr + b"\x00") + sub(2, (NOW - 60).to_bytes(4, "big"))))

    def test_badly_encoded_signature_number(self):
        def declared(extra):
            return lambda n: (n.bit_length() + extra).to_bytes(2, "big") + n.to_bytes((n.bit_length() + 7) // 8, "big")
        for extra in (1, -1, 8):
            self.rejects(signed(encode=declared(extra)))
        self.rejects(signed(encode=lambda n: (0).to_bytes(2, "big")))
        self.rejects(signed(encode=lambda n: mpi(n)[:-1]))  # cut short
        self.rejects(signed(encode=lambda n: mpi(n) + b"\x00"))  # data after the number

    def test_signature_value_not_below_the_modulus(self):
        self.rejects(signed(s=KEY.n))
        self.rejects(signed(s=KEY.n + 1))
        self.rejects(signed(s=1))

    def test_changed_data_or_left16(self):
        self.rejects(signed(), data=DATA + b"\n")
        self.rejects(signed(left16=b"\x00\x00"))


class FuzzTest(unittest.TestCase):
    """Random, truncated and bit-flipped input: always BadSignature, never a crash, hang or accept."""

    def setUp(self):
        self.data = (FIXTURES / "SHA2-256SUMS").read_bytes()
        self.sig = (FIXTURES / "SHA2-256SUMS.sig").read_bytes()

    def assert_refused(self, sig: bytes):
        started = time.monotonic()
        try:
            pgp.verify(self.data, sig, pgp.YTDLP_PUBLIC_KEY, pgp.YTDLP_FINGERPRINT)
        except pgp.BadSignature:
            pass
        else:
            self.fail(f"accepted a damaged signature: {sig.hex()}")
        self.assertLess(time.monotonic() - started, 2)

    def test_every_truncation(self):
        for end in range(len(self.sig)):
            self.assert_refused(self.sig[:end])

    def test_every_bit_flip_in_the_header_and_subpackets(self):
        for i in range(min(len(self.sig), 80)):
            for bit in range(8):
                changed = bytearray(self.sig)
                changed[i] ^= 1 << bit
                self.assert_refused(bytes(changed))

    def test_random_mutations_and_noise(self):
        rng = random.Random(1234)
        for _ in range(600):
            changed = bytearray(self.sig)
            for _ in range(rng.randint(1, 6)):
                op = rng.random()
                pos = rng.randrange(len(changed))
                if op < 0.5:
                    changed[pos] = rng.randrange(256)
                elif op < 0.75:
                    changed.insert(pos, rng.randrange(256))
                elif len(changed) > 1:
                    del changed[pos]
            self.assert_refused(bytes(changed))
        for size in (0, 1, 2, 5, 64, 566, 4096, 20000):
            self.assert_refused(rng.randbytes(size))
            self.assert_refused(bytes([0xC2]) + rng.randbytes(size))

    def test_odd_types_never_crash(self):
        for sig in (None, "text", 12, [1, 2], bytearray(self.sig)):
            with self.assertRaises(pgp.BadSignature):
                pgp.verify(self.data, sig, pgp.YTDLP_PUBLIC_KEY, pgp.YTDLP_FINGERPRINT)


if __name__ == "__main__":
    unittest.main()
