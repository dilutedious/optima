#!/usr/bin/env python3
"""HTTP route check.

POSTs (and PUT/PATCH/DELETEs) to every write endpoint with a valid payload and
asserts each returns a success-ish status — 200 (OK) or 302 (redirect, e.g. a
form post that redirects back to the dashboard). GET pages are swept too. The
point is to catch typos in route rules, missing handlers, and payloads the
server silently rejects — not to test business logic.

Everything runs against the Flask test client on a throwaway data dir, so it
touches neither a real server nor your real ``data/`` folder.

Run from the project root:

    python3 tools/route_check.py     # exit 0 = every route answered 200/302
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import create_app

# Success for a write is "the handler ran and didn't blow up": a 200 page/JSON
# or a 302 redirect. Anything else (400 validation, 404 missing, 5xx crash) is
# a failure for the *valid* payloads we send here.
OK_CODES = {200, 302}

# A fixed future date keeps "due date must be today or later" happy regardless
# of when the check is run.
FUTURE_DATE = "2026-12-01"

# Daytime window — clear of the default 22:30–06:30 sleep range, which the
# event endpoints reject as an overlap.
EVENT_START, EVENT_END = 14.0, 15.0


def main() -> int:
    app = create_app(Path(tempfile.mkdtemp()))
    app.config.update(TESTING=True)
    c = app.test_client()

    # Ordered list of writes. Order matters: create the account first so the
    # session (and its derived key) exists, then create the rows the <id>
    # routes need, then exercise updates, then delete everything last.
    #
    # Each step is (label, callable -> Response). Using closures keeps the
    # request shapes (form vs JSON) explicit and readable.
    steps: list[tuple[str, callable]] = [
        ("GET  /",
         lambda: c.get("/")),
        ("GET  /login",
         lambda: c.get("/login")),
        ("GET  /signup",
         lambda: c.get("/signup")),
        ("POST /signup",
         lambda: c.post("/signup", data={
             "username": "routecheck", "password": "test1234",
             "confirm": "test1234"})),
        # --- pages that need a session (signup logged us in) ---
        ("GET  /dashboard",
         lambda: c.get("/dashboard")),
        ("GET  /weekly",
         lambda: c.get("/weekly")),
        ("GET  /monthly",
         lambda: c.get("/monthly")),
        ("GET  /preferences",
         lambda: c.get("/preferences")),
        ("GET  /tasks/new",
         lambda: c.get("/tasks/new")),
        # --- create rows so the <id> routes below resolve ---
        ("POST /subjects/new",
         lambda: c.post("/subjects/new", data={
             "name": "Route Check Subject", "colour": "#7B68EE"})),
        ("POST /tasks/new",
         lambda: c.post("/tasks/new", data={
             "name": "Route check task", "subject_id": "1",
             "type": "exam", "importance": "high", "weighting": "20",
             "hours_required": "3", "due_date": FUTURE_DATE,
             "due_time": "09:00"})),
        ("GET  /tasks/1",
         lambda: c.get("/tasks/1")),
        ("POST /tasks/1 (edit)",
         lambda: c.post("/tasks/1", data={
             "name": "Route check task (edited)", "subject_id": "1",
             "type": "exam", "importance": "high", "weighting": "25",
             "hours_required": "4", "due_date": FUTURE_DATE,
             "due_time": "10:00", "completion_percent": "0.5"})),
        ("POST /api/tasks/1/progress",
         lambda: c.post("/api/tasks/1/progress",
                        json={"completion_percent": 0.75})),
        # --- calendar API: period, event, move ---
        ("GET  /api/periods",
         lambda: c.get("/api/periods")),
        ("POST /api/periods",
         lambda: c.post("/api/periods", json={
             "name": "Period 1", "start_time": 9.0, "end_time": 10.0})),
        ("GET  /api/events (list)",
         lambda: c.get("/api/events?start=2026-12-01&end=2026-12-07")),
        ("POST /api/events",
         lambda: c.post("/api/events", json={
             "name": "Maths class", "subject_id": 1,
             "start_time": EVENT_START, "end_time": EVENT_END,
             "anchor_date": FUTURE_DATE, "recurrence": "weekly",
             "kind": "subject"})),
        ("GET  /api/subjects/1/next_occurrence",
         lambda: c.get("/api/subjects/1/next_occurrence")),
        ("PATCH /api/events/1",
         lambda: c.patch("/api/events/1", json={
             "scope": "all", "name": "Maths class (moved)",
             "start_time": 15.0, "end_time": 16.0})),
        ("POST /api/events/move",
         lambda: c.post("/api/events/move", json={"moves": [{
             "id": 1, "on_date": FUTURE_DATE,
             "new_start": 16.0, "new_end": 17.0, "scope": "this"}]})),
        # --- deletes last: tear down everything we made ---
        ("DELETE /api/events/1",
         lambda: c.delete("/api/events/1?scope=all")),
        ("DELETE /api/periods/1",
         lambda: c.delete("/api/periods/1")),
        ("POST /tasks/1 (delete)",
         lambda: c.post("/tasks/1", data={"action": "delete"})),
        ("POST /subjects/6/delete",
         lambda: c.post("/subjects/6/delete")),
        ("POST /preferences (theme+a11y)",
         lambda: c.post("/preferences", data={
             "theme": "dark", "high_contrast": "on", "time_format": "12h",
             "zoom": "110"})),
        ("GET  /logout",
         lambda: c.get("/logout")),
    ]

    print(f"Checking {len(steps)} routes against a throwaway data dir\n")
    failures = 0
    for label, call in steps:
        code = call().status_code
        bad = code not in OK_CODES
        failures += bad
        print(f"  {code:>3}  {label}{'   <-- FAIL' if bad else ''}")

    print(f"\n{'PASS' if failures == 0 else 'FAIL'} — "
          f"{len(steps) - failures}/{len(steps)} routes answered 200/302")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
