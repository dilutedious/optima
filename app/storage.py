"""JSON-backed persistence — one file per user account.

v0.3.0: open + write directly. Atomic temp-file swap arrives in v0.3.1
after a tester (E3) reported a truncated file when they force-quit
mid-save.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


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

    def load_user(self, username: str) -> Optional[dict]:
        p = self.user_path(username)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_user(self, data: dict) -> None:
        # Non-atomic — will switch to a tempfile.mkstemp + os.replace
        # in v0.3.1. Documented at the top of this module.
        p = self.user_path(data["username"])
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
