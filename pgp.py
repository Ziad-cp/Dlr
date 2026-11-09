"""Checks OpenPGP signatures (RFC 4880 / RFC 9580, version 4, RSA) against a public key pinned in
this file. Used to verify yt-dlp's signed checksum list (SHA2-256SUMS.sig) before an update is
trusted: the checksums prove the download matches the list, and the signature proves yt-dlp's
maintainers made the list. Pure Python, no gpg needed.

A signature is accepted only if ALL of these hold; anything else, including any parsing problem
or odd input, means "not verified" (BadSignature), never a crash:

- The pinned key block parses, its CRC-24 matches, its primary key has the pinned fingerprint, is
  a version 4 RSA key of at least 2048 bits, carries a valid self-signature (checked with the key
  itself), is allowed to sign, isn't revoked and hasn't expired. Subkeys are never used.
- The signature input is exactly one signature packet and nothing else (no other or trailing
  packets, no multiple signatures, no partial or indeterminate lengths), at most 16 KB.
- Version 4, type 0x00 (binary document) only, RSA, and SHA-256, SHA-384 or SHA-512 (MD5, SHA-1,
  RIPEMD-160 and SHA-224 are refused).
- The hashed area names the issuer by the pinned key's full fingerprint; no issuer key ID anywhere
  (hashed or unhashed) names a different key. Nothing in the unhashed area is trusted, and it may
  hold only the issuer's key ID, once: anything else there is refused.
- Exactly one hashed creation time, not before the key was made and at most a day in the future;
  not past a signature expiration time, if one is set.
- No unknown subpacket marked critical; no repeated or damaged subpackets; every number is encoded
  with exactly the bits it declares; no data after the signature value.
- The PKCS #1 v1.5 encoding of the digest matches exactly (compared in full, in constant time).
"""
import base64
import hashlib
import hmac
import re
import time

# yt-dlp's release signing key, exactly as published at
# https://github.com/yt-dlp/yt-dlp/blob/master/public.key
# Its fingerprint is pinned below as well: a changed key block is refused, not trusted.
YTDLP_PUBLIC_KEY = """\
-----BEGIN PGP PUBLIC KEY BLOCK-----

mQINBGP78C4BEAD0rF9zjGPAt0thlt5C1ebzccAVX7Nb1v+eqQjk+WEZdTETVCg3
WAM5ngArlHdm/fZqzUgO+pAYrB60GKeg7ffUDf+S0XFKEZdeRLYeAaqqKhSibVal
DjvOBOztu3W607HLETQAqA7wTPuIt2WqmpL60NIcyr27LxqmgdN3mNvZ2iLO+bP0
nKR/C+PgE9H4ytywDa12zMx6PmZCnVOOOu6XZEFmdUxxdQ9fFDqd9LcBKY2LDOcS
Yo1saY0YWiZWHtzVoZu1kOzjnS5Fjq/yBHJLImDH7pNxHm7s/PnaurpmQFtDFruk
t+2lhDnpKUmGr/I/3IHqH/X+9nPoS4uiqQ5HpblB8BK+4WfpaiEg75LnvuOPfZIP
KYyXa/0A7QojMwgOrD88ozT+VCkKkkJ+ijXZ7gHNjmcBaUdKK7fDIEOYI63Lyc6Q
WkGQTigFffSUXWHDCO9aXNhP3ejqFWgGMtCUsrbkcJkWuWY7q5ARy/05HbSM3K4D
U9eqtnxmiV1WQ8nXuI9JgJQRvh5PTkny5LtxqzcmqvWO9TjHBbrs14BPEO9fcXxK
L/CFBbzXDSvvAgArdqqlMoncQ/yicTlfL6qzJ8EKFiqW14QMTdAn6SuuZTodXCTi
InwoT7WjjuFPKKdvfH1GP4bnqdzTnzLxCSDIEtfyfPsIX+9GI7Jkk/zZjQARAQAB
tDdTaW1vbiBTYXdpY2tpICh5dC1kbHAgc2lnbmluZyBrZXkpIDxjb250YWN0QGdy
dWI0ay54eXo+iQJOBBMBCgA4FiEErAy75oSNaoc0ZK9OV89lkztadYEFAmP78C4C
GwMFCwkIBwIGFQoJCAsCBBYCAwECHgECF4AACgkQV89lkztadYEVqQ//cW7TxhXg
7Xbh2EZQzXml0egn6j8QaV9KzGragMiShrlvTO2zXfLXqyizrFP4AspgjSn/4NrI
8mluom+Yi+qr7DXT4BjQqIM9y3AjwZPdywe912Lxcw52NNoPZCm24I9T7ySc8lmR
FQvZC0w4H/VTNj/2lgJ1dwMflpwvNRiWa5YzcFGlCUeDIPskLx9++AJE+xwU3LYm
jQQsPBqpHHiTBEJzMLl+rfd9Fg4N+QNzpFkTDW3EPerLuvJniSBBwZthqxeAtw4M
UiAXh6JvCc2hJkKCoygRfM281MeolvmsGNyQm+axlB0vyldiPP6BnaRgZlx+l6MU
cPqgHblb7RW5j9lfr6OYL7SceBIHNv0CFrt1OnkGo/tVMwcs8LH3Ae4a7UJlIceL
V54aRxSsZU7w4iX+PB79BWkEsQzwKrUuJVOeL4UDwWajp75OFaUqbS/slDDVXvK5
OIeuth3mA/adjdvgjPxhRQjA3l69rRWIJDrqBSHldmRsnX6cvXTDy8wSXZgy51lP
m4IVLHnCy9m4SaGGoAsfTZS0cC9FgjUIyTyrq9M67wOMpUxnuB0aRZgJE1DsI23E
qdvcSNVlO+39xM/KPWUEh6b83wMn88QeW+DCVGWACQq5N3YdPnAJa50617fGbY6I
gXIoRHXkDqe23PZ/jURYCv0sjVtjPoVC+bg=
=bJkn
-----END PGP PUBLIC KEY BLOCK-----
"""
YTDLP_FINGERPRINT = "AC0CBBE6848D6A873464AF4E57CF65933B5A7581"

_DIGEST_INFO = {  # allowed hash algorithms: id -> (hashlib name, DER DigestInfo prefix, PKCS #1 v1.5)
    8: ("sha256", bytes.fromhex("3031300d060960864801650304020105000420")),
    9: ("sha384", bytes.fromhex("3041300d060960864801650304020205000430")),
    10: ("sha512", bytes.fromhex("3051300d060960864801650304020305000440")),
}  # MD5 (1), SHA-1 (2), RIPEMD-160 (3), SHA-224 (11) and anything else are refused
_RSA = 1
_MIN_RSA_BITS = 2048
_TAG_SIGNATURE, _TAG_PUBLIC_KEY, _TAG_USER_ID, _TAG_PUBLIC_SUBKEY = 2, 6, 13, 14
_BINARY_DOCUMENT = 0x00
_CERTIFICATIONS = (0x10, 0x11, 0x12, 0x13)
_KEY_REVOCATION = 0x20
# Hashed subpackets this module understands; any other one marked "critical" makes the signature invalid.
_SUB_CREATED, _SUB_SIG_EXPIRES, _SUB_KEY_EXPIRES, _SUB_ISSUER, _SUB_FLAGS, _SUB_ISSUER_FPR = 2, 3, 9, 16, 27, 33
_KNOWN = {_SUB_CREATED, _SUB_SIG_EXPIRES, _SUB_KEY_EXPIRES, _SUB_ISSUER, _SUB_FLAGS, _SUB_ISSUER_FPR,
          11, 21, 22, 23, 25, 30}  # preferences and features: informational only
_CAN_SIGN = 0x02
CLOCK_SKEW = 24 * 3600  # a signature dated at most a day in the future is still accepted
MAX_SIGNATURE = 16 * 1024


class BadSignature(ValueError):
    """The signature is missing, damaged, by another key, expired, or doesn't match the data."""


def _crc24(data: bytes) -> int:
    crc = 0xB704CE
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def _dearmor(text: str) -> bytes:
    """The bytes of an ASCII-armored block; its CRC-24 checksum must match if present."""
    m = re.fullmatch(r"\s*-----BEGIN PGP PUBLIC KEY BLOCK-----\r?\n(.*?)-----END PGP PUBLIC KEY BLOCK-----\s*",
                     text, re.S)
    if not m:
        raise BadSignature("not an armored OpenPGP public key block")
    body = m.group(1)
    if re.search(r"^\s*$", body, re.M):  # skip armor headers, up to the first empty line
        body = re.split(r"\r?\n\s*\r?\n", body, maxsplit=1)[-1]
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    crc = lines.pop()[1:] if lines and lines[-1].startswith("=") else None
    try:
        data = base64.b64decode("".join(lines), validate=True)
        if crc is not None and int.from_bytes(base64.b64decode(crc, validate=True), "big") != _crc24(data):
            raise BadSignature("the armor checksum doesn't match")
    except ValueError as e:
        raise BadSignature(str(e) if isinstance(e, BadSignature) else "damaged armor") from None
    return data


def _packets(data: bytes):
    """Yield (tag, body) for each packet. Partial and indeterminate lengths are refused."""
    i = 0
    while i < len(data):
        first = data[i]
        i += 1
        if not first & 0x80:
            raise BadSignature("not an OpenPGP packet")
        if first & 0x40:  # new format
            tag = first & 0x3F
            if i >= len(data):
                raise BadSignature("truncated packet")
            o1 = data[i]
            if o1 < 192:
                length, i = o1, i + 1
            elif o1 < 224:
                if i + 2 > len(data):
                    raise BadSignature("truncated packet")
                length, i = ((o1 - 192) << 8) + data[i + 1] + 192, i + 2
            elif o1 == 255:
                if i + 5 > len(data):
                    raise BadSignature("truncated packet")
                length, i = int.from_bytes(data[i + 1:i + 5], "big"), i + 5
            else:
                raise BadSignature("partial lengths aren't supported")
        else:  # old format
            tag, kind = (first >> 2) & 0x0F, first & 0x03
            if kind == 3:
                raise BadSignature("indeterminate lengths aren't supported")
            size = (1, 2, 4)[kind]
            if i + size > len(data):
                raise BadSignature("truncated packet")
            length, i = int.from_bytes(data[i:i + size], "big"), i + size
        if i + length > len(data):
            raise BadSignature("truncated packet")
        yield tag, data[i:i + length]
        i += length


def _mpi(data: bytes, i: int) -> tuple[int, int]:
    """A multiprecision integer, which must be encoded with exactly the bit count it declares."""
    if i + 2 > len(data):
        raise BadSignature("truncated number")
    bits = int.from_bytes(data[i:i + 2], "big")
    size = (bits + 7) // 8
    if bits == 0 or i + 2 + size > len(data):
        raise BadSignature("truncated number")
    value = int.from_bytes(data[i + 2:i + 2 + size], "big")
    if value.bit_length() != bits:
        raise BadSignature("badly encoded number")
    return value, i + 2 + size


def _subpackets(data: bytes) -> list[tuple[int, bool, bytes]]:
    """(type, critical, value) for each subpacket; any length problem is refused."""
    found, i = [], 0
    while i < len(data):
        o1 = data[i]
        if o1 < 192:
            length, i = o1, i + 1
        elif o1 < 255:
            if i + 2 > len(data):
                raise BadSignature("damaged subpacket")
            length, i = ((o1 - 192) << 8) + data[i + 1] + 192, i + 2
        else:
            if i + 5 > len(data):
                raise BadSignature("damaged subpacket")
            length, i = int.from_bytes(data[i + 1:i + 5], "big"), i + 5
        if length < 1 or i + length > len(data):
            raise BadSignature("damaged subpacket")
        found.append((data[i] & 0x7F, bool(data[i] & 0x80), data[i + 1:i + length]))
        i += length
    return found


class _Signature:
    """A parsed version 4 signature packet."""

    def __init__(self, body: bytes):
        if len(body) < 6 or body[0] != 4:
            raise BadSignature("only version 4 signatures are supported")
        self.type, self.pub_algo, self.hash_algo = body[1], body[2], body[3]
        hashed_end = 6 + int.from_bytes(body[4:6], "big")
        if hashed_end + 2 > len(body):
            raise BadSignature("truncated signature")
        unhashed_end = hashed_end + 2 + int.from_bytes(body[hashed_end:hashed_end + 2], "big")
        if unhashed_end + 2 > len(body):
            raise BadSignature("truncated signature")
        self.hashed = _subpackets(body[6:hashed_end])
        self.unhashed = _subpackets(body[hashed_end + 2:unhashed_end])
        self.prefix = body[:hashed_end]  # what the hash covers, besides the data
        self.left16 = body[unhashed_end:unhashed_end + 2]
        self.s, end = _mpi(body, unhashed_end + 2)
        if end != len(body):
            raise BadSignature("unexpected data after the signature")
        for kind, critical, _ in self.hashed + self.unhashed:
            if critical and kind not in _KNOWN:
                raise BadSignature("unknown critical subpacket")

    def hashed_value(self, kind: int, size: int):
        """The one value of a hashed subpacket kind (None if absent); duplicates are refused."""
        values = [value for k, _, value in self.hashed if k == kind]
        if len(values) > 1:
            raise BadSignature("repeated subpacket")
        if values and len(values[0]) != size:
            raise BadSignature("damaged subpacket")
        return values[0] if values else None

    def created(self) -> int:
        value = self.hashed_value(_SUB_CREATED, 4)
        if value is None:
            raise BadSignature("the signature has no creation time")
        return int.from_bytes(value, "big")

    def lifetime(self, kind: int):
        """Seconds a signature (or key) stays valid after its creation; None = forever."""
        value = self.hashed_value(kind, 4)
        seconds = int.from_bytes(value, "big") if value is not None else 0
        return seconds or None

    def check(self, digest_input: bytes, key: "_Key"):
        """The RSA signature over digest_input (data, or certified key material) with key."""
        if self.pub_algo != key.algo or self.hash_algo not in _DIGEST_INFO:
            raise BadSignature("unsupported signature algorithm")
        name, prefix = _DIGEST_INFO[self.hash_algo]
        h = hashlib.new(name)
        h.update(digest_input)
        h.update(self.prefix)
        h.update(b"\x04\xff" + len(self.prefix).to_bytes(4, "big"))
        digest = h.digest()
        k = (key.n.bit_length() + 7) // 8
        expected = prefix + digest
        if not 0 < self.s < key.n or (self.s.bit_length() + 7) // 8 > k or k < len(expected) + 11:
            raise BadSignature("the signature doesn't match the data")
        encoded = b"\x00\x01" + b"\xff" * (k - len(expected) - 3) + b"\x00" + expected
        if not (hmac.compare_digest(digest[:2], self.left16)
                and hmac.compare_digest(pow(self.s, key.e, key.n).to_bytes(k, "big"), encoded)):
            raise BadSignature("the signature doesn't match the data")


class _Key:
    """The pinned primary key: an RSA key of at least 2048 bits, self-certified, not revoked."""

    def __init__(self, armored: str, fingerprint: str):
        packets = list(_packets(_dearmor(armored)))
        if not packets or packets[0][0] != _TAG_PUBLIC_KEY:
            raise BadSignature("no public key in the block")
        self.body = body = packets[0][1]
        self.fingerprint = hashlib.sha1(self.material).hexdigest().upper()
        if self.fingerprint != fingerprint.replace(" ", "").upper():
            raise BadSignature("the pinned key doesn't match its fingerprint")
        if len(body) < 6 or body[0] != 4 or body[5] != _RSA:
            raise BadSignature("the pinned key must be a version 4 RSA key")
        self.created, self.algo = int.from_bytes(body[1:5], "big"), body[5]
        self.n, i = _mpi(body, 6)
        self.e, end = _mpi(body, i)
        if end != len(body) or self.n.bit_length() < _MIN_RSA_BITS or self.e < 3 or not self.e & 1:
            raise BadSignature("the pinned key is too weak or damaged")
        self.key_id = bytes.fromhex(self.fingerprint)[-8:]
        self.expires = None
        certified = False
        user_id = None
        for tag, packet in packets[1:]:
            if tag == _TAG_PUBLIC_SUBKEY:
                break  # subkeys aren't used: only the primary key may sign updates
            if tag == _TAG_USER_ID:
                user_id = packet
            elif tag == _TAG_SIGNATURE:
                sig = _Signature(packet)
                if sig.type == _KEY_REVOCATION:
                    raise BadSignature("the pinned key has been revoked")
                if sig.type in _CERTIFICATIONS and user_id is not None and self.issued(sig):
                    sig.check(self.material + b"\xb4" + len(user_id).to_bytes(4, "big") + user_id, self)
                    flags = sig.hashed_value(_SUB_FLAGS, 1)
                    if flags is not None and not flags[0] & _CAN_SIGN:
                        raise BadSignature("the pinned key isn't allowed to sign")
                    lifetime = sig.lifetime(_SUB_KEY_EXPIRES)
                    self.expires = self.created + lifetime if lifetime else None
                    certified = True
        if not certified:
            raise BadSignature("the pinned key has no valid self-signature")

    @property
    def material(self) -> bytes:
        return b"\x99" + len(self.body).to_bytes(2, "big") + self.body

    def issued(self, sig: _Signature) -> bool:
        """True if the signature's hashed issuer fingerprint is this key's (and no issuer subpacket
        anywhere names another key)."""
        issuer = sig.hashed_value(_SUB_ISSUER_FPR, 21)
        if issuer is None or issuer != b"\x04" + bytes.fromhex(self.fingerprint):
            return False
        return all(value == self.key_id for kind, _, value in sig.hashed + sig.unhashed if kind == _SUB_ISSUER)


def primary_fingerprint(armored: str) -> str:
    for tag, body in _packets(_dearmor(armored)):
        if tag == _TAG_PUBLIC_KEY:
            return hashlib.sha1(b"\x99" + len(body).to_bytes(2, "big") + body).hexdigest().upper()
    raise BadSignature("no public key in the block")


def verify(data: bytes, signature: bytes, armored_key: str, fingerprint: str, now: float | None = None) -> str:
    """Check a detached binary-document signature over data, made by the pinned primary key.
    Returns the key's fingerprint; raises BadSignature for anything else (see the module notes)."""
    try:
        key = _Key(armored_key, fingerprint)
        if not isinstance(signature, bytes) or len(signature) > MAX_SIGNATURE:
            raise BadSignature("not a signature")
        packets = list(_packets(signature))
        if len(packets) != 1 or packets[0][0] != _TAG_SIGNATURE:
            raise BadSignature("expected exactly one signature packet and nothing else")
        sig = _Signature(packets[0][1])
        if sig.type != _BINARY_DOCUMENT:
            raise BadSignature("only binary document signatures are accepted")
        if not key.issued(sig):
            raise BadSignature("signed by a key other than the pinned one")
        # The unhashed area isn't covered by the signature, so it may hold nothing but the
        # issuer's key ID (once): any other content there is refused rather than ignored.
        if len(sig.unhashed) > 1 or any(kind != _SUB_ISSUER or critical for kind, critical, _ in sig.unhashed):
            raise BadSignature("unexpected unsigned data in the signature")
        now = time.time() if now is None else now
        created = sig.created()
        if created < key.created or created > now + CLOCK_SKEW:
            raise BadSignature("the signature's date isn't possible")
        lifetime = sig.lifetime(_SUB_SIG_EXPIRES)
        if lifetime is not None and now >= created + lifetime:
            raise BadSignature("the signature has expired")
        if key.expires is not None and (now >= key.expires or created >= key.expires):
            raise BadSignature("the pinned key has expired")
        sig.check(data, key)
        return key.fingerprint
    except BadSignature:
        raise
    except Exception:  # never anything but "not verified" for odd input
        raise BadSignature("damaged signature") from None
