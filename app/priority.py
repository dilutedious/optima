"""Priority calculator.

Two-tier system, as specified in the client interview:
1. Urgency override: any assignment with <= 3 days remaining is "critical"
   (priority 999) regardless of weighting — this guarantees imminent deadlines
   never get buried under a long-term task with higher weighting.
2. Otherwise: score = (weighting * 10) / max(days_remaining, 1). Higher
   weighting bumps the score; longer time-to-due drops it. The *10 scale
   factor exists so common HSC weightings (5..30) produce scores in a useful
   range (~5..200) for visual ranking.
"""

from __future__ import annotations

from datetime import date
from typing import List

from .models import Assignment


CRITICAL_PRIORITY = 999.0
URGENCY_THRESHOLD_DAYS = 3


def priority_score(assignment: Assignment, today: date | None = None) -> float:
    if assignment.completed:
        return 0.0
    days = assignment.days_remaining(today)
    if days <= URGENCY_THRESHOLD_DAYS:
        return CRITICAL_PRIORITY
    return (assignment.weighting * 10.0) / max(days, 1)


def rank_assignments(assignments: List[Assignment], today: date | None = None) -> List[Assignment]:
    for a in assignments:
        a.priority_score = priority_score(a, today)
    # stable sort: critical first, then by score desc, then earliest due date
    return sorted(
        [a for a in assignments if not a.completed],
        key=lambda a: (-a.priority_score, a.due_date),
    )
