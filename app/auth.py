"""Authentication — SHA-256 password hashing with per-user salt.

Stores no plaintext passwords. Salts are randomly generated per account
and prepended to the password before hashing — the same plain password
produces a different hash for each user, so a leaked store can't be
rainbow-attacked.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_salt() -> str:
    return secrets.token_hex(16)


def hash_password(plain: str, salt: str) -> str:
    h = hashlib.sha256()
    h.update(salt.encode("utf-8"))
    h.update(plain.encode("utf-8"))
    return h.hexdigest()


def verify_password(plain: str, salt: str, expected_hash: str) -> bool:
    return secrets.compare_digest(hash_password(plain, salt), expected_hash)
