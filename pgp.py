"""Checks OpenPGP signatures (RFC 4880 / RFC 9580, version 4, RSA) against a public key pinned in
this file. Used to verify yt-dlp's signed checksum list (SHA2-256SUMS.sig) before an update is
trusted: the checksums prove the download matches the list, and the signature proves yt-dlp's
maintainers made the list.

Only what that needs is supported: binary or text signatures (types 0x00 and 0x01), RSA keys and
SHA-256/384/512. Anything else, a key other than the pinned one, or any parsing problem means
"not verified". Pure Python, no gpg needed.
"""
import base64
import hashlib
import hmac
import re

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

_DIGEST_INFO = {  # hash algorithm id: (hashlib name, DER DigestInfo prefix for PKCS #1 v1.5)
    8: ("sha256", bytes.fromhex("3031300d060960864801650304020105000420")),
    9: ("sha384", bytes.fromhex("3041300d060960864801650304020205000430")),
    10: ("sha512", bytes.fromhex("3051300d060960864801650304020305000440")),
}
_RSA = (1, 3)  # RSA (Encrypt or Sign), RSA Sign-Only
_TAG_SIGNATURE, _TAG_PUBLIC_KEY, _TAG_PUBLIC_SUBKEY = 2, 6, 14


class BadSignature(ValueError):
    """The signature is missing, damaged, by another key, or doesn't match the data."""


def _dearmor(text: str) -> bytes:
    m = re.search(r"-----BEGIN PGP [A-Z ]+-----\r?\n(.*?)-----END PGP [A-Z ]+-----", text, re.S)
    if not m:
        raise BadSignature("not an armored OpenPGP block")
    body = m.group(1)
    # Skip armor headers (up to the first empty line), then drop the "=XXXX" CRC-24 line.
    if re.search(r"^\s*$", body, re.M):
        body = re.split(r"\r?\n\s*\r?\n", body, maxsplit=1)[-1]
    lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith("=")]
    try:
        return base64.b64decode("".join(lines), validate=True)
    except ValueError:
        raise BadSignature("damaged armor") from None


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
                if i + 1 >= len(data):
                    raise BadSignature("truncated packet")
                length, i = ((o1 - 192) << 8) + data[i + 1] + 192, i + 2
            elif o1 == 255:
                length, i = int.from_bytes(data[i + 1:i + 5], "big"), i + 5
            else:
                raise BadSignature("partial lengths aren't supported")
        else:  # old format
            tag, kind = (first >> 2) & 0x0F, first & 0x03
            if kind == 3:
                raise BadSignature("indeterminate lengths aren't supported")
            size = (1, 2, 4)[kind]
            length, i = int.from_bytes(data[i:i + size], "big"), i + size
        if i + length > len(data):
            raise BadSignature("truncated packet")
        yield tag, data[i:i + length]
        i += length


def _mpi(data: bytes, i: int) -> tuple[int, int]:
    if i + 2 > len(data):
        raise BadSignature("truncated number")
    bits = int.from_bytes(data[i:i + 2], "big")
    size = (bits + 7) // 8
    if i + 2 + size > len(data):
        raise BadSignature("truncated number")
    return int.from_bytes(data[i + 2:i + 2 + size], "big"), i + 2 + size


def rsa_keys(armored: str) -> dict[bytes, tuple[int, int, str]]:
    """{key ID (8 bytes): (n, e, fingerprint hex)} for every v4 RSA key and subkey in a key block."""
    keys = {}
    for tag, body in _packets(_dearmor(armored)):
        if tag not in (_TAG_PUBLIC_KEY, _TAG_PUBLIC_SUBKEY) or len(body) < 6 or body[0] != 4:
            continue
        if body[5] not in _RSA:
            continue
        n, i = _mpi(body, 6)
        e, _ = _mpi(body, i)
        fingerprint = hashlib.sha1(b"\x99" + len(body).to_bytes(2, "big") + body).digest()
        keys[fingerprint[-8:]] = (n, e, fingerprint.hex().upper())
    return keys


def primary_fingerprint(armored: str) -> str:
    for tag, body in _packets(_dearmor(armored)):
        if tag == _TAG_PUBLIC_KEY:
            return hashlib.sha1(b"\x99" + len(body).to_bytes(2, "big") + body).hexdigest().upper()
    raise BadSignature("no public key in the block")


def _subpackets(data: bytes):
    i = 0
    while i < len(data):
        o1 = data[i]
        if o1 < 192:
            length, i = o1, i + 1
        elif o1 < 255:
            length, i = ((o1 - 192) << 8) + data[i + 1] + 192, i + 2
        else:
            length, i = int.from_bytes(data[i + 1:i + 5], "big"), i + 5
        if length < 1 or i + length > len(data):
            raise BadSignature("damaged subpacket")
        yield data[i] & 0x7F, data[i + 1:i + length]
        i += length


def _issuers(hashed: bytes, unhashed: bytes) -> set[bytes]:
    """Key IDs the signature names (issuer, or the last 8 bytes of the issuer fingerprint)."""
    found = set()
    for area in (hashed, unhashed):
        for kind, value in _subpackets(area):
            if kind == 16 and len(value) == 8:
                found.add(value)
            elif kind == 33 and len(value) == 21 and value[0] == 4:
                found.add(value[-8:])
    return found


def _canonical_text(data: bytes) -> bytes:
    return re.sub(rb"\r?\n", b"\r\n", data)


def verify(data: bytes, signature: bytes, armored_key: str, fingerprint: str) -> str:
    """Check a detached binary signature over data with the pinned key. Returns the fingerprint of
    the (sub)key that made it; raises BadSignature otherwise."""
    if primary_fingerprint(armored_key) != fingerprint.replace(" ", "").upper():
        raise BadSignature("the pinned key doesn't match its fingerprint")
    keys = rsa_keys(armored_key)
    packets = [body for tag, body in _packets(signature) if tag == _TAG_SIGNATURE]
    if len(packets) != 1:
        raise BadSignature("expected exactly one signature")
    sig = packets[0]
    if len(sig) < 6 or sig[0] != 4:
        raise BadSignature("only version 4 signatures are supported")
    sig_type, pub_algo, hash_algo = sig[1], sig[2], sig[3]
    if sig_type not in (0x00, 0x01) or pub_algo not in _RSA or hash_algo not in _DIGEST_INFO:
        raise BadSignature("unsupported signature type or algorithm")
    hashed_len = int.from_bytes(sig[4:6], "big")
    hashed_end = 6 + hashed_len
    if hashed_end + 2 > len(sig):
        raise BadSignature("truncated signature")
    unhashed_len = int.from_bytes(sig[hashed_end:hashed_end + 2], "big")
    unhashed_end = hashed_end + 2 + unhashed_len
    if unhashed_end + 2 > len(sig):
        raise BadSignature("truncated signature")
    hashed, unhashed = sig[6:hashed_end], sig[hashed_end + 2:unhashed_end]
    left16 = sig[unhashed_end:unhashed_end + 2]
    s, end = _mpi(sig, unhashed_end + 2)
    if end != len(sig):
        raise BadSignature("unexpected data after the signature")
    issuers = _issuers(hashed, unhashed) & set(keys)
    if not issuers:
        raise BadSignature("signed by a key other than the pinned one")

    name, prefix = _DIGEST_INFO[hash_algo]
    h = hashlib.new(name)
    h.update(_canonical_text(data) if sig_type == 0x01 else data)
    h.update(sig[:hashed_end])
    h.update(b"\x04\xff" + hashed_end.to_bytes(4, "big"))
    digest = h.digest()
    if not hmac.compare_digest(digest[:2], left16):
        raise BadSignature("the signature doesn't match the data")
    for key_id in issuers:
        n, e, key_fingerprint = keys[key_id]
        k = (n.bit_length() + 7) // 8
        if not 0 < s < n or k < 256:  # at least 2048-bit RSA
            continue
        expected = prefix + digest
        if k < len(expected) + 11:
            continue
        encoded = b"\x00\x01" + b"\xff" * (k - len(expected) - 3) + b"\x00" + expected
        if hmac.compare_digest(pow(s, e, n).to_bytes(k, "big"), encoded):
            return key_fingerprint
    raise BadSignature("the signature doesn't match the data")
