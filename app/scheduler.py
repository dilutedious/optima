"""Scheduling engine — v0.3 with conflict resolver.

The greedy placer now respects fixed constraints. find_free_slots(user, d)
subtracts every class period and other constraint on that day from the
awake window and returns the residual intervals; the placer walks those
in order and emits 30-120 minute study sessions with a 15-minute break
between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List

from .models import Assignment, Constraint, ScheduleBlock, User
from .priority import rank_assignments


MIN_SESSION = 0.5
MAX_SESSION = 2.0
BREAK_AFTER_SESSION = 0.25  # 15 minutes (down from 30 — feels less generous)


@dataclass(order=True)
class FreeSlot:
    """An open interval of unoccupied time on a single date."""
    date_iso: str
    start: float
    end: float = field(compare=False)

    @property
    def length(self) -> float:
        return self.end - self.start


def _fortnight_index(target: date, term_start: date) -> int:
    """Day 0..13 inside the 14-day rotating cycle."""
    return (target - term_start).days % 14


def find_free_slots(user: User, target_date: date,
                    term_start: date | None = None) -> List[FreeSlot]:
    """Awake window minus class periods on this date."""
    term_start = term_start or target_date - timedelta(
        days=(target_date - target_date).days)  # default: assume day 0
    dof = _fortnight_index(target_date, term_start)
    busy = [(c.start_time, c.end_time)
            for c in user.constraints if c.day_of_fortnight == dof]
    busy.sort()
    iso = target_date.isoformat()
    slots: List[FreeSlot] = []
    cursor = user.wake_time
    for start, end in busy:
        if start > cursor:
            slots.append(FreeSlot(iso, cursor, start))
        cursor = max(cursor, end)
    if cursor < user.bed_time:
        slots.append(FreeSlot(iso, cursor, user.bed_time))
    return [s for s in slots if s.length >= MIN_SESSION]


def generate_schedule(user: User, days: List[date]) -> dict:
    """Greedy placement against the slot list. Each assignment fills the
    earliest fitting slot first; the residual of a partly-consumed slot
    is re-inserted in order for the next assignment to pick up."""
    today = date.today()
    ranked = rank_assignments(list(user.assignments), today)
    blocks_per_day = {d.isoformat(): [] for d in days}

    # Build the day-by-day free-slot table up front
    slot_table: dict[str, List[FreeSlot]] = {
        d.isoformat(): find_free_slots(user, d) for d in days
    }

    for a in ranked:
        remaining = a.remaining_hours()
        for d in days:
            if remaining <= 0:
                break
            iso = d.isoformat()
            slots = slot_table[iso]
            new_slots: List[FreeSlot] = []
            for slot in slots:
                if remaining <= 0:
                    new_slots.append(slot)
                    continue
                length = min(MAX_SESSION, remaining, slot.length)
                if length < MIN_SESSION:
                    new_slots.append(slot)
                    continue
                blocks_per_day[iso].append({
                    "name": a.name,
                    "start": slot.start,
                    "end": slot.start + length,
                })
                remaining -= length
                # Residual of this slot (after the block + a 15-min break)
                resid_start = slot.start + length + BREAK_AFTER_SESSION
                if resid_start < slot.end:
                    new_slots.append(FreeSlot(iso, resid_start, slot.end))
            slot_table[iso] = new_slots
    return blocks_per_day


def calculate_cushion(user: User, today: date,
                      horizon: int = 14) -> tuple[float, float, float]:
    """Workload vs. real free time across the horizon — now uses the
    real free-slot calculation, not the 8h placeholder."""
    total_workload = sum(a.hours_required for a in user.assignments)
    total_free = 0.0
    for i in range(horizon):
        d = today + timedelta(days=i)
        total_free += sum(s.length for s in find_free_slots(user, d))
    cushion = total_free / total_workload if total_workload else 1.0
    return total_workload, total_free, cushion
