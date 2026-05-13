"""Domain models for Optima.

Mirrors the Class Diagram from the planning document: User, Subject,
Assignment, Constraint, ScheduleBlock. Designed so each object can round-trip
through JSON via .to_dict() / .from_dict() without losing precision.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import List, Optional


@dataclass
class Subject:
    id: int
    name: str
    colour: str = "#7B68EE"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Subject":
        return cls(id=int(d["id"]), name=d["name"], colour=d.get("colour", "#7B68EE"))


@dataclass
class Constraint:
    """A fixed event such as a class period in the user's 14-day rotation."""

    name: str
    subject_id: Optional[int]
    day_of_fortnight: int  # 0..13
    start_time: float       # hours, e.g. 9.25 for 9:15am
    end_time: float
    is_half_period: bool = False
    is_study_period: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Constraint":
        return cls(
            name=d["name"],
            subject_id=d.get("subject_id"),
            day_of_fortnight=int(d["day_of_fortnight"]),
            start_time=float(d["start_time"]),
            end_time=float(d["end_time"]),
            is_half_period=bool(d.get("is_half_period", False)),
            is_study_period=bool(d.get("is_study_period", False)),
        )


@dataclass
class Assignment:
    id: int
    subject_id: int
    name: str
    due_date: str          # ISO yyyy-mm-dd
    weighting: float       # 0..100
    hours_required: float
    est_hours: float = 0.0
    completion_percent: float = 0.0
    completed: bool = False
    priority_score: float = 0.0

    def days_remaining(self, today: Optional[date] = None) -> int:
        today = today or date.today()
        due = datetime.strptime(self.due_date, "%Y-%m-%d").date()
        return (due - today).days

    def remaining_hours(self) -> float:
        return max(0.0, self.hours_required * (1.0 - self.completion_percent))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Assignment":
        return cls(
            id=int(d["id"]),
            subject_id=int(d["subject_id"]),
            name=d["name"],
            due_date=d["due_date"],
            weighting=float(d["weighting"]),
            hours_required=float(d["hours_required"]),
            est_hours=float(d.get("est_hours", 0.0)),
            completion_percent=float(d.get("completion_percent", 0.0)),
            completed=bool(d.get("completed", False)),
            priority_score=float(d.get("priority_score", 0.0)),
        )


@dataclass
class ScheduleBlock:
    """A block of time allocated for study on a particular assignment."""

    assignment_id: int
    date_iso: str          # yyyy-mm-dd
    start_time: float
    duration: float        # hours
    completed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduleBlock":
        return cls(
            assignment_id=int(d["assignment_id"]),
            date_iso=d["date_iso"],
            start_time=float(d["start_time"]),
            duration=float(d["duration"]),
            completed=bool(d.get("completed", False)),
        )


@dataclass
class Preferences:
    theme: str = "light"               # 'light' | 'dark'
    notifications: bool = True
    auto_save: bool = True
    high_contrast: bool = False
    focus_highlights: bool = True
    zoom: int = 100                    # percent

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Preferences":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class User:
    username: str
    password_hash: str
    salt: str
    study_points: int = 0
    wake_time: float = 6.5
    bed_time: float = 22.5
    term_start: str = ""              # ISO date when Week A starts
    subjects: List[Subject] = field(default_factory=list)
    constraints: List[Constraint] = field(default_factory=list)
    assignments: List[Assignment] = field(default_factory=list)
    schedule_blocks: List[ScheduleBlock] = field(default_factory=list)
    preferences: Preferences = field(default_factory=Preferences)

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "password_hash": self.password_hash,
            "salt": self.salt,
            "study_points": self.study_points,
            "wake_time": self.wake_time,
            "bed_time": self.bed_time,
            "term_start": self.term_start,
            "subjects": [s.to_dict() for s in self.subjects],
            "constraints": [c.to_dict() for c in self.constraints],
            "assignments": [a.to_dict() for a in self.assignments],
            "schedule_blocks": [b.to_dict() for b in self.schedule_blocks],
            "preferences": self.preferences.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "User":
        return cls(
            username=d["username"],
            password_hash=d["password_hash"],
            salt=d["salt"],
            study_points=int(d.get("study_points", 0)),
            wake_time=float(d.get("wake_time", 6.5)),
            bed_time=float(d.get("bed_time", 22.5)),
            term_start=d.get("term_start", ""),
            subjects=[Subject.from_dict(x) for x in d.get("subjects", [])],
            constraints=[Constraint.from_dict(x) for x in d.get("constraints", [])],
            assignments=[Assignment.from_dict(x) for x in d.get("assignments", [])],
            schedule_blocks=[ScheduleBlock.from_dict(x) for x in d.get("schedule_blocks", [])],
            preferences=Preferences.from_dict(d.get("preferences", {})),
        )

    def next_subject_id(self) -> int:
        return max((s.id for s in self.subjects), default=0) + 1

    def next_assignment_id(self) -> int:
        return max((a.id for a in self.assignments), default=0) + 1

    def subject_by_id(self, sid: int) -> Optional[Subject]:
        for s in self.subjects:
            if s.id == sid:
                return s
        return None
