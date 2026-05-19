"""Stdlib-only symmetric encryption / decryption for Optima.

Used to keep a user's "private notes" on each assignment encrypted at rest
inside ``data/users/<username>.json``. The threat model is "someone steals
my laptop": even if they open the JSON in a text editor, the private-notes
field is opaque without the user's password.

Why not use the ``cryptography`` library?
    Adding it would pull a Rust toolchain dependency, which the brief
    deliberately avoids — Optima ships in Python stdlib only. The
    SHA-256 / PBKDF2-HMAC primitives in ``hashlib`` and the CSPRNG in
    ``secrets`` are enough to construct a reasonable symmetric cipher
    for the threat model.

Algorithm
---------
* Key derivation: PBKDF2-HMAC-SHA-256, 200 000 iterations, 32-byte key.
* Encryption: a stream cipher using SHA-256 as a PRNG in CTR mode.
  For each block we hash ``key || nonce || counter`` and XOR the output
  against the plaintext. This is what Bruce Schneier calls "the cipher
  you build when you only have a hash function" — not as fast or
  conventional as AES-256-CTR but cryptographically reasonable.
* Authentication: HMAC-SHA-256 over (nonce || ciphertext) appended as
  a 32-byte tag, verified before decryption (encrypt-then-MAC).

A ciphertext token looks like ``base64(nonce || ciphertext || mac)``
where ``nonce`` is 16 random bytes and ``mac`` is the 32-byte HMAC.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional


PBKDF2_ITERATIONS = 200_000
KEY_LEN = 32
NONCE_LEN = 16
MAC_LEN = 32
_BLOCK_SIZE = hashlib.sha256().digest_size  # 32


def derive_key(password: str, salt_hex: str) -> bytes:
    """Derive a 32-byte key from password + the user's salt (hex string)."""
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=KEY_LEN
    )


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """SHA-256 in counter mode — produce ``length`` pseudo-random bytes."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt + authenticate ``plaintext``; return a base64 token."""
    if plaintext == "":
        return ""
    if len(key) != KEY_LEN:
        raise ValueError("key must be 32 bytes")
    nonce = secrets.token_bytes(NONCE_LEN)
    data = plaintext.encode("utf-8")
    ks = _keystream(key, nonce, len(data))
    ct = bytes(p ^ k for p, k in zip(data, ks))
    mac = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + ct + mac).decode("ascii")


def decrypt(token: str, key: bytes) -> str:
    """Verify + decrypt a token produced by :func:`encrypt`."""
    if token == "":
        return ""
    if len(key) != KEY_LEN:
        raise ValueError("key must be 32 bytes")
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise ValueError("token is not valid base64") from exc
    if len(raw) < NONCE_LEN + MAC_LEN:
        raise ValueError("token too short")
    nonce, body, mac = raw[:NONCE_LEN], raw[NONCE_LEN:-MAC_LEN], raw[-MAC_LEN:]
    expected = hmac.new(key, nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("authentication failed — wrong key or tampering")
    ks = _keystream(key, nonce, len(body))
    pt = bytes(c ^ k for c, k in zip(body, ks))
    return pt.decode("utf-8")


# ---------------------------------------------------------------------------
# Self-test (run as: python -m app.crypto)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    salt = secrets.token_hex(16)
    key = derive_key("correcthorsebatterystaple", salt)
    msg = "Mr Brown's marking on this essay felt unfair — keep this private."
    token = encrypt(msg, key)
    assert decrypt(token, key) == msg
    # Wrong key fails
    bad = derive_key("not the right password", salt)
    try:
        decrypt(token, bad)
        assert False, "should have failed authentication"
    except ValueError:
        pass
    # Tampered token fails
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    try:
        decrypt(tampered, key)
        assert False, "should have failed authentication"
    except ValueError:
        pass
    print(f"crypto self-test PASSED ({len(token)} chars for {len(msg)}-byte plaintext)")
