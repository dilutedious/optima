"""Priority calculator — planning-doc formula with critical override."""

from __future__ import annotations

from datetime import date, datetime
from typing import List


CRITICAL_PRIORITY = 999.0
URGENCY_THRESHOLD_DAYS = 3


def priority_score(weighting: float, days_remaining: int) -> float:
    if days_remaining <= URGENCY_THRESHOLD_DAYS:
        return CRITICAL_PRIORITY
    return (weighting * 10) / max(days_remaining, 1)


def rank_assignments(assignments: List[dict], today: date) -> List[dict]:
    """Annotate each assignment with `days` + `score` and return them sorted
    by score descending; tie-break by due_date so two equally-urgent tasks
    get a stable order."""
    out = []
    for a in assignments:
        due = datetime.strptime(a["due_date"], "%Y-%m-%d").date()
        a["days"] = (due - today).days
        a["score"] = priority_score(a["weighting"], a["days"])
        out.append(a)
    out.sort(key=lambda a: (-a["score"], a["due_date"]))
    return out
