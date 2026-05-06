"""Authentication — SHA-256 password hashing.

v0.3.0: still using a single shared salt across all accounts.
Per-user salt is the next commit.
"""

from __future__ import annotations

import hashlib


GLOBAL_SALT = "optima-prototype-salt"


def hash_password(plain: str) -> str:
    return hashlib.sha256((GLOBAL_SALT + plain).encode("utf-8")).hexdigest()


def verify_password(plain: str, expected_hash: str) -> bool:
    return hash_password(plain) == expected_hash
