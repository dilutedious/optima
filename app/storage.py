"""JSON-backed persistence for Optima users.

Each user has their own file in data/users/<username>.json. Writes go
through an atomic temp-file swap so a power loss or crash mid-save
never corrupts the master copy.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from .models import User


def _safe_filename(username: str) -> str:
    return re.sub(r"[^A-Za-z0-9._@-]", "_", username).lower()


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.users_dir = self.data_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def user_path(self, username: str) -> Path:
        return self.users_dir / f"{_safe_filename(username)}.json"

    def user_exists(self, username: str) -> bool:
        return self.user_path(username).exists()

    def load_user(self, username: str) -> Optional[User]:
        p = self.user_path(username)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return User.from_dict(json.load(f))

    def save_user(self, user: User) -> None:
        """Atomic write: temp file in the same directory, fsync, rename."""
        path = self.user_path(user.username)
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json",
                                   dir=str(self.users_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(user.to_dict(), f, indent=2)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def list_users(self) -> list[str]:
        return [p.stem for p in self.users_dir.glob("*.json")]
