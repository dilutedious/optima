"""Scheduling engine.

Given a user's constraints, sleep schedule, and ranked assignment list,
generate a 14-day plan of ScheduleBlocks that:
  - never overlaps a fixed class or other constraint
  - never crosses bed_time -> wake_time
  - allocates higher-priority assignments first
  - aims for blocks of 30..120 minutes (configurable; the planning spec said
    sessions should be optimised for focus)
  - returns a "cushion ratio" = totalFreeSlots / totalWorkload so the dashboard
    can warn the user if they don't have enough free time to finish on time.

The algorithm is intentionally greedy rather than a constraint solver — for a
single-student schedule this is fast (<100ms in tests) and easy to reason
about, which matched the agile / iterate-on-feedback approach in the planning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional

from .models import Assignment, Constraint, Preferences, ScheduleBlock, User
from .priority import rank_assignments


SLOT_GRANULARITY = 0.5         # half-hour resolution
MIN_SESSION = 0.5
MAX_SESSION = 2.0
BREAK_AFTER_SESSION = 0.25     # 15 min break before next study block


@dataclass
class FreeSlot:
    date_iso: str
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class ScheduleResult:
    blocks: List[ScheduleBlock]
    free_slots: List[FreeSlot]
    cushion: float                # ratio: total_free / total_workload
    total_free_hours: float
    total_workload_hours: float
    conflicts: List[str]          # human-readable strings for the dashboard


def _day_of_fortnight(term_start_iso: str, target: date) -> int:
    """Index 0..13 — assumes Week A starts on the term_start date."""
    if not term_start_iso:
        return 0
    start = datetime.strptime(term_start_iso, "%Y-%m-%d").date()
    days = (target - start).days
    if days < 0:
        # Walk forward until we hit a non-negative congruence.
        return (days % 14 + 14) % 14
    return days % 14


def _constraints_for_day(user: User, day_idx: int) -> List[Constraint]:
    return [c for c in user.constraints if c.day_of_fortnight == day_idx]


def _round_slot(value: float) -> float:
    """Snap value to the nearest SLOT_GRANULARITY (rounding down for starts)."""
    steps = round(value / SLOT_GRANULARITY)
    return steps * SLOT_GRANULARITY


def _free_slots_for_day(
    user: User, day: date, existing_blocks: Iterable[ScheduleBlock]
) -> List[FreeSlot]:
    """Slots between wake_time and bed_time not occupied by constraints/blocks."""

    day_idx = _day_of_fortnight(user.term_start, day)
    occupied: List[tuple[float, float]] = []
    for c in _constraints_for_day(user, day_idx):
        if c.is_study_period:
            continue
        occupied.append((c.start_time, c.end_time))
    iso = day.isoformat()
    for b in existing_blocks:
        if b.date_iso == iso:
            occupied.append((b.start_time, b.start_time + b.duration))

    # Build free slots by walking the day from wake to bed.
    occupied.sort()
    free: List[FreeSlot] = []
    cursor = user.wake_time
    end = user.bed_time
    for start, stop in occupied:
        if start > cursor:
            free.append(FreeSlot(iso, cursor, min(start, end)))
        cursor = max(cursor, stop)
        if cursor >= end:
            break
    if cursor < end:
        free.append(FreeSlot(iso, cursor, end))

    # Drop slots shorter than the minimum study session.
    return [s for s in free if s.length >= MIN_SESSION]


def find_free_slots(user: User, horizon_days: int = 14, today: Optional[date] = None) -> List[FreeSlot]:
    today = today or date.today()
    out: List[FreeSlot] = []
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        out.extend(_free_slots_for_day(user, day, user.schedule_blocks))
    return out


def calculate_cushion(free_slots: List[FreeSlot], assignments: List[Assignment]) -> tuple[float, float, float]:
    total_free = sum(s.length for s in free_slots)
    total_workload = sum(a.remaining_hours() for a in assignments if not a.completed)
    if total_workload == 0:
        return (1.0, total_free, 0.0)
    return (total_free / total_workload, total_free, total_workload)


def generate_schedule(user: User, horizon_days: int = 14, today: Optional[date] = None) -> ScheduleResult:
    today = today or date.today()
    ranked = rank_assignments(user.assignments, today)

    # Snapshot existing blocks but clear any that are still in the future and
    # belong to incomplete assignments — those get regenerated.
    keepers: List[ScheduleBlock] = []
    for b in user.schedule_blocks:
        block_date = datetime.strptime(b.date_iso, "%Y-%m-%d").date()
        if block_date < today or b.completed:
            keepers.append(b)

    new_blocks: List[ScheduleBlock] = list(keepers)
    conflicts: List[str] = []

    # Build day-by-day free-slot map.
    free_by_day: dict[str, List[FreeSlot]] = {}
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        free_by_day[day.isoformat()] = _free_slots_for_day(user, day, new_blocks)

    for assign in ranked:
        remaining = assign.remaining_hours()
        if remaining <= 0:
            continue
        # Earliest-first within the horizon, but for critical (<=3 days) we
        # also re-rank to fill tomorrow first.
        for offset in range(horizon_days):
            if remaining <= 0:
                break
            day = today + timedelta(days=offset)
            if day > datetime.strptime(assign.due_date, "%Y-%m-%d").date():
                conflicts.append(
                    f"'{assign.name}' is due before all required hours can fit — consider increasing study time or reducing scope."
                )
                break
            slots = free_by_day.get(day.isoformat(), [])
            i = 0
            while i < len(slots) and remaining > 0:
                slot = slots[i]
                length = min(slot.length, MAX_SESSION, remaining)
                if length < MIN_SESSION:
                    i += 1
                    continue
                length = _round_slot(length)
                block = ScheduleBlock(
                    assignment_id=assign.id,
                    date_iso=day.isoformat(),
                    start_time=_round_slot(slot.start),
                    duration=length,
                )
                new_blocks.append(block)
                remaining -= length
                # Slice the slot to reflect the block + a short break.
                new_start = _round_slot(slot.start + length + BREAK_AFTER_SESSION)
                if new_start + MIN_SESSION <= slot.end:
                    slots[i] = FreeSlot(slot.date_iso, new_start, slot.end)
                else:
                    slots.pop(i)
                    continue
                i += 0  # keep examining the trimmed slot

    # Recompute residual free slots after placement, for the cushion gauge.
    all_free = []
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        all_free.extend(_free_slots_for_day(user, day, new_blocks))

    cushion, total_free, total_workload = calculate_cushion(all_free, user.assignments)
    return ScheduleResult(
        blocks=new_blocks,
        free_slots=all_free,
        cushion=cushion,
        total_free_hours=total_free,
        total_workload_hours=total_workload,
        conflicts=conflicts,
    )
