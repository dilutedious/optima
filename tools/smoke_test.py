#!/usr/bin/env python3
"""Route smoke test.

Boots the app with a throwaway data dir, signs up a user, seeds one task,
then GETs every registered route and confirms each responds with a sane
status code — 200 (OK), 302 (redirect, e.g. logged-in / -> dashboard), or
404 (correctly reporting a missing resource). Anything 500-level is a
failure. This is a "nothing is on fire" check, not functional testing.

Run from the project root:

    python3 tools/smoke_test.py     # exit 0 = all routes healthy
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import create_app

OK_CODES = {200, 302, 404}


def subst(path: str) -> str:
    """Fill URL params with plausible ids so the rule resolves."""
    for token in ("<int:task_id>", "<int:cid>", "<int:pid>", "<int:subject_id>"):
        path = path.replace(token, "1")
    return path


def main() -> int:
    app = create_app(Path(tempfile.mkdtemp()))
    app.config.update(TESTING=True)
    c = app.test_client()

    rules = [r for r in app.url_map.iter_rules() if r.endpoint != "static"]
    get_rules = sorted((r for r in rules if "GET" in r.methods), key=str)
    # Hold /logout to the very end so it doesn't clear the session mid-sweep.
    get_rules = [r for r in get_rules if str(r) != "/logout"] + \
                [r for r in get_rules if str(r) == "/logout"]

    # Log in + seed a real task so /tasks/<id> resolves to something.
    c.post("/signup", data={"username": "smoke", "password": "test1234",
                            "confirm": "test1234"})
    c.post("/tasks/new", data={
        "name": "Smoke task", "subject_id": "1",
        "task_type": "exam", "weighting": "20",
        "hours_required": "3", "due_date": "2026-12-01", "due_time": "09:00",
    })  # first assignment gets id 1, so subst()'s "1" resolves it

    print(f"{len(rules)} registered rules · {len(get_rules)} GET routes\n")
    failures = 0
    for rule in get_rules:
        path = subst(str(rule))
        code = c.get(path).status_code
        bad = code not in OK_CODES
        failures += bad
        print(f"  {code:>3}  GET {path}{'   <-- FAIL' if bad else ''}")

    print(f"\n{'PASS' if failures == 0 else 'FAIL'} — "
          f"{len(get_rules) - failures}/{len(get_rules)} routes healthy")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
