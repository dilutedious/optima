#!/usr/bin/env python3
"""Scheduler performance benchmark.

Measures the two hot paths in the scheduling engine against a range of
timetable sizes, from a realistic single-student load (~37 stored events)
up to an 18x stress test (~666 events). Confirms the greedy / sorted-list
approach is fast enough that the O(log n) interval-tree alternative would
be premature optimisation at any scale a student actually operates at.

Run from the project root:

    python3 tools/benchmark.py

Reproducible: prints the machine + Python version so a reader can compare.
"""

from __future__ import annotations

import platform
import sys
import timeit
from datetime import date, timedelta
from pathlib import Path

# Allow `python3 tools/benchmark.py` from the project root without PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import Assignment, Constraint, Subject, User
from app.scheduler import find_free_slots, generate_schedule


def make_user(n_classes: int, n_assignments: int = 12) -> User:
    """Build a User with `n_classes` fixed weekly events, a third as many
    designated study zones, and a handful of assignments to place."""
    today = date.today()
    term_start = (today - timedelta(days=7)).isoformat()
    u = User(username="bench", password_hash="x", salt="y", term_start=term_start)
    u.subjects = [Subject(id=i, name=f"S{i}", colour="#5e4ae3") for i in range(1, 6)]

    # Fixed events (classes), spread across the 14-day cycle + the day.
    for i in range(n_classes):
        anchor = (today + timedelta(days=i % 14)).isoformat()
        start = 8.0 + (i % 8)
        u.constraints.append(Constraint(
            id=i, name=f"Class{i}", subject_id=(i % 5) + 1,
            start_time=start, end_time=start + 0.75,
            anchor_date=anchor, recurrence="weekly", kind="subject"))

    # Designated study zones so the placer has somewhere to work.
    for i in range(max(1, n_classes // 3)):
        anchor = (today + timedelta(days=i % 14)).isoformat()
        u.constraints.append(Constraint(
            id=10_000 + i, name=f"Study{i}", subject_id=None,
            start_time=16.0, end_time=19.5,
            anchor_date=anchor, recurrence="weekly", kind="study_block"))

    for i in range(n_assignments):
        due = (today + timedelta(days=2 + i)).isoformat()
        u.assignments.append(Assignment(
            id=i, subject_id=(i % 5) + 1, name=f"Task{i}",
            due_date=due, hours_required=5.0, weighting=25.0, type="exam"))
    return u


def main() -> int:
    print(f"{'events':>8} | {'find_free_slots':>16} | {'generate_schedule':>18}")
    print("-" * 52)
    for n in (28, 50, 100, 250, 500):
        u = make_user(n)
        events = len(u.constraints)
        t_ffs = timeit.timeit(lambda: find_free_slots(u), number=200) / 200 * 1000
        t_gen = timeit.timeit(lambda: generate_schedule(u), number=50) / 50 * 1000
        print(f"{events:>8} | {t_ffs:>13.3f} ms | {t_gen:>15.3f} ms")
    print()
    print(f"Machine: {platform.machine()} · Python {sys.version.split()[0]} "
          f"· {platform.system()} {platform.release()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
