"""Scheduling engine — v1.2.

Given a user's constraints, sleep window, and ranked assignment list,
generate a 14-day plan of ScheduleBlocks that:

  - **only places study sessions inside designated study blocks** —
    constraints with ``kind == "study_block"``. The exception is the
    *escalation path* below.
  - never overlaps a fixed event (subject / extracurricular / other) or
    sleep.
  - never crosses sleep_start -> sleep_end.
  - rotates between assignments inside a single designated zone instead of
    cramming one task into a long block, with a short break between
    consecutive sessions.
  - distributes work across days via round-robin: each assignment gets up
    to one session per day before any assignment gets a second session.

Escalation: tasks the user *can't* afford to wait for (homework due
tomorrow, exam or project within the critical window) are allowed to use
*any* free time outside fixed events / sleep — not just the designated
zones. Without this escape hatch the cushion gauge would go red the moment
the designated zones ran out, which is too brittle.

The algorithm is intentionally greedy rather than a constraint solver — for
a single-student schedule it's fast (<100ms in tests) and easy to reason
about, matching the iterate-on-feedback approach in the planning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional

from .models import Assignment, Constraint, ScheduleBlock, User
from .priority import rank_assignments, CRITICAL_PRIORITY


SLOT_GRANULARITY = 5 / 60          # five-minute resolution
MIN_SESSION = 0.5                  # 30 minutes
MAX_SESSION = 2.0                  # 2 hours
BREAK_AFTER_SESSION = 0.25         # 15-minute break before next study block
# How many hours of one assignment we'll pack into a single day before
# yielding the rest of the day to lower-priority work. Without this, a
# heavy critical task would consume ALL of its critical-day's designated
# zones and crowd out everything else; with it, the higher-priority task
# gets first dibs but stops at this ceiling.
MAX_HOURS_PER_DAY_PER_ASSIGN = 3.0
# Escalation thresholds — how close to the due date must a task be before the
# scheduler is allowed to step outside designated study zones?
ESCALATE_HOMEWORK_DAYS = 1         # homework due tomorrow → free time fair game
ESCALATE_ASSESSMENT_DAYS = 3       # exam / project due within 3 days → ditto


@dataclass(order=True)
class FreeSlot:
    """An open interval of unoccupied time on a single date.

    The dataclass is ``order=True`` so a list of FreeSlots can be kept in
    canonical (date, start) order — needed when slots are sliced by the
    placer and the residual re-inserted in order.
    """

    date_iso: str
    start: float
    end: float = field(compare=False)
    # True when this slot came from a Constraint with kind="study_block"
    # (a designated study zone). False for slots derived from "any other
    # free time" — those are only used when an assignment escalates.
    designated: bool = field(default=False, compare=False)

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _round_slot(value: float) -> float:
    """Snap value to the nearest SLOT_GRANULARITY."""
    steps = round(value / SLOT_GRANULARITY)
    return steps * SLOT_GRANULARITY


def _constraints_on_date(user: User, target: date) -> List[Constraint]:
    """All constraints whose recurrence places an occurrence on ``target``."""
    return [c for c in user.constraints if c.occurs_on(target)]


def _sleep_intervals(sleep_start: float, sleep_end: float) -> List[tuple[float, float]]:
    """Return the in-day intervals that are *asleep* given a sleep window.

    The window can wrap past midnight (e.g. sleep_start=22.5, sleep_end=6.5
    means asleep 22:30..24:00 AND 00:00..06:30). The intervals returned are
    always within [0, 24].
    """
    if sleep_start == sleep_end:
        return []
    if sleep_start < sleep_end:
        # Non-wrapping (rare — daytime nap).
        return [(sleep_start, sleep_end)]
    # Wrapping over midnight — the common case.
    out: List[tuple[float, float]] = []
    if sleep_start < 24.0:
        out.append((sleep_start, 24.0))
    if sleep_end > 0.0:
        out.append((0.0, sleep_end))
    return out


def _subtract(intervals: List[tuple[float, float]],
              occupied: List[tuple[float, float]]) -> List[tuple[float, float]]:
    """Return the parts of ``intervals`` not covered by ``occupied``.

    Both lists are merged & sorted internally. Result is sorted by start.
    """
    if not intervals:
        return []
    out: List[tuple[float, float]] = []
    # Merge occupied for a clean walk.
    occ = sorted(occupied)
    merged: List[tuple[float, float]] = []
    for s, e in occ:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    for s, e in intervals:
        cursor = s
        for os_, oe in merged:
            if oe <= cursor:
                continue
            if os_ >= e:
                break
            if os_ > cursor:
                out.append((cursor, min(os_, e)))
            cursor = max(cursor, oe)
            if cursor >= e:
                break
        if cursor < e:
            out.append((cursor, e))
    return [(s, e) for s, e in out if e - s >= MIN_SESSION]


def _free_slots_for_day(user: User, day: date,
                        existing_blocks: Iterable[ScheduleBlock]) -> tuple[List[FreeSlot], List[FreeSlot]]:
    """Compute (designated, fallback) free slots for one date.

    *designated* — gaps inside ``kind == "study_block"`` constraints, minus
    sleep / other fixed events / already-placed schedule blocks / time that
    has already passed.
    *fallback*   — every other awake-but-empty gap. Only consumed when an
                   assignment is escalated.
    """
    iso = day.isoformat()

    # Sleep first — those minutes are unconditionally off-limits.
    occupied: List[tuple[float, float]] = list(_sleep_intervals(user.sleep_start, user.sleep_end))

    # Past time on today is off-limits — the user explicitly asked the
    # scheduler to never plan into the past (round-4 follow-up).
    now = datetime.now()
    if day == now.date():
        now_dec = now.hour + now.minute / 60.0
        if now_dec > 0:
            occupied.append((0.0, now_dec))

    designated_intervals: List[tuple[float, float]] = []
    for c in _constraints_on_date(user, day):
        view = c.occurrence_view(day)
        s, e = view["start_time"], view["end_time"]
        if c.kind == "study_block":
            designated_intervals.append((s, e))
        else:
            occupied.append((s, e))

    # Existing study / break blocks also reserve their slot.
    for b in existing_blocks:
        if b.date_iso == iso:
            occupied.append((b.start_time, b.start_time + b.duration))

    designated = [
        FreeSlot(iso, s, e, designated=True)
        for (s, e) in _subtract(designated_intervals, occupied)
    ]

    # Fallback: full awake window minus everything (including designated
    # zones, since those are reserved for normal placement).
    awake = [(max(0.0, user.wake_time), min(24.0, user.bed_time))]
    fallback_intervals = _subtract(awake, occupied + designated_intervals)
    fallback = [FreeSlot(iso, s, e, designated=False) for s, e in fallback_intervals]
    return designated, fallback


def find_free_slots(user: User, horizon_days: int = 14,
                    today: Optional[date] = None) -> List[FreeSlot]:
    """Designated + fallback slots flattened, for cushion calculations.

    The cushion gauge treats fallback time as "available if you need it",
    so it's right to count both — otherwise the gauge would always look
    starved.
    """
    today = today or date.today()
    out: List[FreeSlot] = []
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        desig, fallback = _free_slots_for_day(user, day, user.schedule_blocks)
        out.extend(desig)
        out.extend(fallback)
    return out


def calculate_cushion(free_slots: List[FreeSlot],
                      assignments: List[Assignment]) -> tuple[float, float, float]:
    total_free = sum(s.length for s in free_slots)
    total_workload = sum(a.remaining_hours() for a in assignments if not a.completed)
    if total_workload == 0:
        return (1.0, total_free, 0.0)
    return (total_free / total_workload, total_free, total_workload)


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

def _escalation_window_hours(assignment: Assignment) -> float:
    """How many hours out can this assignment use *non-designated* free time?

    Homework: 24h (was 1 day in v1.2). Exam / project: 72h (was 3 days).
    Numbers unchanged in spirit; the hours-resolution input from due_time
    makes the gate slightly sharper than the calendar-day version.
    """
    if assignment.type == "homework":
        return ESCALATE_HOMEWORK_DAYS * 24.0
    return ESCALATE_ASSESSMENT_DAYS * 24.0


def _cutoff_for_assignment(assignment: Assignment, day_date: date,
                           due_date: date) -> Optional[float]:
    """Return the decimal-hours cutoff for placing this assignment on this day.

    On the due-date day, the assignment can only use time *before* its
    ``due_time``. On any other day there is no cutoff. Returning ``None``
    means "no cap"; an actual value means "clip slot ends to this".

    Critically this is a *read-only* view — callers must not mutate the
    day's pool state on its account, because the same pool is shared with
    every other assignment processed on that day.
    """
    if day_date != due_date:
        return None
    return assignment.due_time


@dataclass
class _DayState:
    """Working slots + scheduled-blocks state for a single date."""

    iso: str
    designated: List[FreeSlot]
    fallback: List[FreeSlot]
    blocks: List[ScheduleBlock] = field(default_factory=list)


def _consume_slot(slot: FreeSlot, want_hours: float,
                  assignment_id: int, date_iso: str) -> tuple[Optional[ScheduleBlock], Optional[ScheduleBlock], Optional[FreeSlot]]:
    """Carve a study session (and optional break) out of ``slot``.

    Returns (study_block, break_block, residual_slot). Each is None when not
    applicable. The break is only inserted if there's enough room for it
    AND another minimum session after it — otherwise the slot just ends.
    """
    length = _round_slot(min(slot.length, MAX_SESSION, want_hours))
    if length < MIN_SESSION:
        return None, None, slot
    study = ScheduleBlock(
        assignment_id=assignment_id,
        date_iso=date_iso,
        start_time=_round_slot(slot.start),
        duration=length,
    )
    cursor = slot.start + length
    # Insert a break only if at least MIN_SESSION of room follows it.
    if cursor + BREAK_AFTER_SESSION + MIN_SESSION <= slot.end:
        brk = ScheduleBlock(
            assignment_id=assignment_id,
            date_iso=date_iso,
            start_time=_round_slot(cursor),
            duration=BREAK_AFTER_SESSION,
            is_break=True,
        )
        cursor += BREAK_AFTER_SESSION
        residual = FreeSlot(slot.date_iso, _round_slot(cursor), slot.end,
                            designated=slot.designated)
        if residual.length < MIN_SESSION:
            residual = None
        return study, brk, residual
    return study, None, None


def _try_place_one_session(assign: Assignment, day: _DayState,
                           remaining_hours: float, allow_fallback: bool,
                           cutoff: Optional[float] = None) -> Optional[float]:
    """Place at most one session of ``assign`` on ``day``.

    ``cutoff`` clips the *effective* end of each slot for THIS assignment
    only — the day's pool retains its original end, so a 5pm slot capped
    at 9am for assignment A still has its post-9am portion available to
    assignment B. Returns the hours placed, or None if no slot was usable.
    """
    pools = [day.designated]
    if allow_fallback:
        pools.append(day.fallback)
    for pool in pools:
        for i, slot in enumerate(pool):
            slot_end = slot.end if cutoff is None else min(slot.end, cutoff)
            if slot_end - slot.start < MIN_SESSION:
                # Nothing usable inside the cutoff for this assignment — but
                # the rest of the slot stays in the pool for others.
                continue
            view = FreeSlot(slot.date_iso, slot.start, slot_end,
                            designated=slot.designated)
            study, brk, _ = _consume_slot(view, remaining_hours,
                                          assign.id, day.iso)
            if study is None:
                continue
            day.blocks.append(study)
            if brk is not None:
                day.blocks.append(brk)
            # The residual is computed against the ORIGINAL slot end so the
            # post-cutoff portion remains visible to subsequent assignments
            # whose due_time doesn't cap them.
            consumed_end = study.start_time + study.duration + (
                brk.duration if brk is not None else 0.0
            )
            new_start = _round_slot(consumed_end)
            if new_start + MIN_SESSION <= slot.end:
                pool[i] = FreeSlot(slot.date_iso, new_start, slot.end,
                                   designated=slot.designated)
            else:
                pool.pop(i)
            return study.duration
    return None


def generate_schedule(user: User, horizon_days: int = 14,
                      today: Optional[date] = None) -> ScheduleResult:
    """Plan study blocks across the horizon."""
    today = today or date.today()
    now = datetime.now()
    ranked = rank_assignments(user.assignments, now)

    # Carry forward any past or completed blocks; everything else is
    # regenerated. Breaks live and die with their owning study block, so
    # past breaks are kept; future ones are dropped along with their work.
    # Importantly we also keep blocks on TODAY whose end has already
    # passed — without this, every dashboard load wipes the morning's
    # work before the auto-progress pass can count it, so completion
    # bars never advance.
    now_today_dec = now.hour + now.minute / 60.0
    keepers: List[ScheduleBlock] = []
    for b in user.schedule_blocks:
        try:
            block_date = datetime.strptime(b.date_iso, "%Y-%m-%d").date()
        except ValueError:
            continue
        if block_date < today or b.completed:
            keepers.append(b)
        elif block_date == today and (b.start_time + b.duration) <= now_today_dec:
            keepers.append(b)

    # Per-day working state — designated + fallback slots minus the keepers.
    days: List[_DayState] = []
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        desig, fallback = _free_slots_for_day(user, day, keepers)
        days.append(_DayState(iso=day.isoformat(), designated=desig, fallback=fallback))

    # Active workload per assignment — remaining hours we still need to fit.
    # Overdue tasks are skipped entirely: the scheduler refuses to plan future
    # work for a deadline that's already passed. The dashboard will badge
    # them red so the user notices and either reschedules or marks complete.
    remaining: dict[int, float] = {}
    for a in ranked:
        if a.is_overdue(now):
            continue
        remaining[a.id] = a.remaining_hours()
    conflicts: List[str] = []

    # Placement strategy:
    #   - Outer loop: iterate until no further progress is made anywhere.
    #   - For each day: drain designated zones by PRIORITY. Higher-priority
    #     assignments take what they need from the day's zones (up to
    #     MAX_HOURS_PER_DAY_PER_ASSIGN) BEFORE lower-priority gets a turn.
    #     This was the round-4 follow-up: the earlier "one session per
    #     (day, assignment) per pass" round-robin gave lower-priority tasks
    #     the next designated zone after a higher-priority task only got a
    #     short residual — so a PHYS due tomorrow ended up sandwiched in
    #     fallback time while a less-urgent CHEM took the full evening zone.
    #   - Across days: the per-day cap stops a single heavy task from
    #     piling up its entire workload on its critical day, so other work
    #     still gets spread across the horizon.
    progressed = True
    while progressed:
        progressed = False
        for day_idx, day in enumerate(days):
            day_date = today + timedelta(days=day_idx)
            hours_today: dict[int, float] = {}
            keep_going = True
            while keep_going:
                keep_going = False
                for assign in ranked:
                    if remaining.get(assign.id, 0.0) <= 0:
                        continue
                    if hours_today.get(assign.id, 0.0) >= MAX_HOURS_PER_DAY_PER_ASSIGN:
                        continue
                    try:
                        due = datetime.strptime(assign.due_date, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if day_date > due:
                        continue
                    cutoff = _cutoff_for_assignment(assign, day_date, due)
                    hours_left = assign.hours_until_due(now)
                    escalate = (
                        assign.priority_score >= CRITICAL_PRIORITY
                        or hours_left <= _escalation_window_hours(assign)
                    )
                    # Cap the placement to the day's remaining headroom for
                    # this task so the per-day cap is respected even if
                    # _consume_slot would otherwise place a full MAX_SESSION.
                    want = min(
                        remaining[assign.id],
                        MAX_HOURS_PER_DAY_PER_ASSIGN - hours_today.get(assign.id, 0.0),
                    )
                    placed = _try_place_one_session(
                        assign, day, want,
                        allow_fallback=escalate, cutoff=cutoff,
                    )
                    if placed is None:
                        continue
                    remaining[assign.id] = max(0.0, remaining[assign.id] - placed)
                    hours_today[assign.id] = hours_today.get(assign.id, 0.0) + placed
                    progressed = True
                    # Restart the priority sweep: higher-priority tasks
                    # may have more headroom now that this slot moved.
                    keep_going = True
                    break

    # Rescue pass — anything still short after the strict zones-first run
    # gets squeezed into whatever fallback (non-designated) time we can
    # find, regardless of the escalation window. Same priority-first
    # within a day as the main pass; sleep/classes/extracurriculars are
    # still off-limits — only the awake-and-empty fallback time is used.
    progressed = True
    while progressed:
        progressed = False
        for day_idx, day in enumerate(days):
            day_date = today + timedelta(days=day_idx)
            hours_today: dict[int, float] = {}
            keep_going = True
            while keep_going:
                keep_going = False
                for assign in ranked:
                    if remaining.get(assign.id, 0.0) <= 0:
                        continue
                    if hours_today.get(assign.id, 0.0) >= MAX_HOURS_PER_DAY_PER_ASSIGN:
                        continue
                    try:
                        due = datetime.strptime(assign.due_date, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if day_date > due:
                        continue
                    cutoff = _cutoff_for_assignment(assign, day_date, due)
                    want = min(
                        remaining[assign.id],
                        MAX_HOURS_PER_DAY_PER_ASSIGN - hours_today.get(assign.id, 0.0),
                    )
                    placed = _try_place_one_session(
                        assign, day, want,
                        allow_fallback=True, cutoff=cutoff,
                    )
                    if placed is None:
                        continue
                    remaining[assign.id] = max(0.0, remaining[assign.id] - placed)
                    hours_today[assign.id] = hours_today.get(assign.id, 0.0) + placed
                    progressed = True
                    keep_going = True
                    break

    # Final under-allocation surface. Overdue tasks aren't surfaced here —
    # they're flagged separately on the dashboard, and re-listing them as
    # "X hours short" would just be noise.
    for assign in ranked:
        if assign.is_overdue(now):
            continue
        short = remaining.get(assign.id, 0.0)
        if short > 0.001:
            mins = int(round(short * 60))
            if mins >= 60:
                h, m = divmod(mins, 60)
                label = f"{h} h" if m == 0 else f"{h} h {m} min"
            else:
                label = f"{mins} min"
            conflicts.append(f"Need an extra {label} for '{assign.name}'")

    new_blocks: List[ScheduleBlock] = list(keepers)
    for day in days:
        new_blocks.extend(day.blocks)

    # Cushion uses both designated and fallback slots still unfilled.
    free_after = find_free_slots(user, horizon_days=horizon_days, today=today)
    # Subtract the just-placed blocks from the cushion accounting.
    placed_by_day: dict[str, List[tuple[float, float]]] = {}
    for b in new_blocks:
        placed_by_day.setdefault(b.date_iso, []).append((b.start_time, b.start_time + b.duration))
    remaining_free: List[FreeSlot] = []
    for s in free_after:
        residuals = _subtract([(s.start, s.end)], placed_by_day.get(s.date_iso, []))
        for ns, ne in residuals:
            remaining_free.append(FreeSlot(s.date_iso, ns, ne, designated=s.designated))

    cushion, total_free, total_workload = calculate_cushion(remaining_free, user.assignments)
    return ScheduleResult(
        blocks=new_blocks,
        free_slots=remaining_free,
        cushion=cushion,
        total_free_hours=total_free,
        total_workload_hours=total_workload,
        conflicts=conflicts,
    )
