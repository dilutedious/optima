"""Scheduling engine — greedy placement.

v0.3.0: still the v0.2-style "drop blocks into the morning" placer. The
real conflict resolver (find_free_slots — subtracts class periods from
the awake window) lands later this week.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List

from .models import Assignment, ScheduleBlock, User
from .priority import rank_assignments


MIN_SESSION = 0.5
MAX_SESSION = 2.0
BREAK_AFTER_SESSION = 0.5  # 30 min between back-to-back study blocks


def generate_schedule(user: User, days: List[date]) -> dict:
    """Greedy placement: ranked assignments fill the morning of each day,
    one block per pass. Known to overlap on same-day deadlines — conflict
    resolver is the next sprint."""
    today = date.today()
    ranked = rank_assignments(list(user.assignments), today)
    blocks_per_day = {d.isoformat(): [] for d in days}
    cursor = {d.isoformat(): user.wake_time + 1.0 for d in days}

    for a in ranked:
        remaining = a.remaining_hours()
        i = 0
        while remaining > 0 and i < len(days):
            d = days[i].isoformat()
            start = cursor[d]
            length = min(MAX_SESSION, remaining, user.bed_time - start)
            if length < MIN_SESSION:
                i += 1
                continue
            blocks_per_day[d].append({
                "name": a.name,
                "start": start,
                "end": start + length,
            })
            cursor[d] = start + length + BREAK_AFTER_SESSION
            remaining -= length
            i += 1
    return blocks_per_day


def calculate_cushion(user: User, today: date,
                      horizon: int = 14) -> tuple[float, float, float]:
    """Workload + free + ratio. Free time is the crude awake_window - 8h
    placeholder; will derive from real constraints once they exist."""
    total_workload = sum(a.hours_required for a in user.assignments)
    awake_per_day = user.bed_time - user.wake_time
    free_per_day = max(0.0, awake_per_day - 8.0)
    total_free = free_per_day * horizon
    cushion = total_free / total_workload if total_workload else 1.0
    return total_workload, total_free, cushion
