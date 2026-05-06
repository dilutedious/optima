"""Priority calculator — planning-doc formula with critical override."""

from __future__ import annotations

from datetime import date, datetime
from typing import List

from .models import Assignment


CRITICAL_PRIORITY = 999.0
URGENCY_THRESHOLD_DAYS = 3


def priority_score(assignment: Assignment, today: date) -> float:
    days = assignment.days_remaining(today)
    if days <= URGENCY_THRESHOLD_DAYS:
        return CRITICAL_PRIORITY
    return (assignment.weighting * 10) / max(days, 1)


def rank_assignments(assignments: List[Assignment], today: date) -> List[Assignment]:
    """Annotate score on each assignment and return them sorted by score
    desc, then due date asc."""
    for a in assignments:
        a.priority_score = priority_score(a, today)
    return sorted(assignments,
                  key=lambda a: (-a.priority_score, a.due_date))
