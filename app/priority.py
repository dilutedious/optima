"""Priority calculator.

Three-tier system (v1.2 + round-4 due_time refinement):

1. **Overdue** (``due_at < now``): score ``OVERDUE_PRIORITY = 9999``. Floats
   above everything so the dashboard puts stale work at the top, and the
   scheduler stops planning future blocks for it.
2. **Critical** (``hours_until_due <= 24``): score
   ``CRITICAL_PRIORITY = 999``. The escalation path in the scheduler is
   triggered the same way the v1.2 "≤3 days" critical check used to.
3. **Otherwise**: score = (``scoring_weight`` * 10) / max(``hours_until_due
   / 24``, 1). Same shape as the old formula but the denominator is now
   fractional days, so two tasks both due "in 2 days" rank differently if
   one's due Friday morning and the other's due Friday evening.

``scoring_weight`` is the user-entered weighting % for exams and the
importance-map value for homework/project. See ``Assignment.scoring_weight``.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from .models import Assignment


OVERDUE_PRIORITY = 9999.0
CRITICAL_PRIORITY = 999.0
CRITICAL_HOURS = 24.0    # ≤24h to due_at flips to critical


def priority_score(assignment: Assignment, now: Optional[datetime] = None) -> float:
    if assignment.completed:
        return 0.0
    hours = assignment.hours_until_due(now)
    if hours < 0:
        return OVERDUE_PRIORITY
    if hours <= CRITICAL_HOURS:
        return CRITICAL_PRIORITY
    # Same formula shape as v1.1, but the denominator is in fractional days
    # so a Friday-9am task and a Friday-11pm task no longer tie.
    days = max(hours / 24.0, 1.0)
    return (assignment.scoring_weight() * 10.0) / days


def rank_assignments(assignments: List[Assignment], now: Optional[datetime] = None) -> List[Assignment]:
    """Order open assignments by priority, descending.

    Tie-break by due_at (earlier first) so two tasks at the same score still
    have a stable, intuitive order. Completed tasks stay on the list until
    their due-at moment passes — finishing early is a win the user should
    still see acknowledged on the dashboard. Once a completed task is past
    its due date, it drops off (and lives on in the history view).
    """
    now_dt = now or datetime.now()
    for a in assignments:
        a.priority_score = priority_score(a, now)
    visible = [
        a for a in assignments
        if not a.completed or a.due_at() > now_dt
    ]
    return sorted(visible, key=lambda a: (-a.priority_score, a.due_at()))
