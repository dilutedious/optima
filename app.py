"""
Optima — in-progress v0.2.

Storage scaffold landed; auth + signup wiring follows in the next commits.
Data shape for a user JSON (the seven domain objects from the planning
document, expressed as nested dicts for now — dataclass refactor is a v0.3
job once the package is split):

    {
      "username": str,
      "password_hash": str,
      "subjects":    [{"id": int, "name": str, "colour": str}, ...],
      "constraints": [{"id": int, "name": str, "day_of_fortnight": int,
                       "start_time": float, "end_time": float}, ...],
      "assignments": [{"id": int, "name": str, "subject_id": int,
                       "due_date": str, "weighting": float,
                       "hours_required": float}, ...],
      "schedule_blocks": [{"assignment_id": int, "date_iso": str,
                            "start_time": float, "duration": float}, ...],
      "wake_time": float,
      "bed_time":  float,
    }
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for


DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Seeded into a fresh account so a tester has something to react to. The
# planning doc lists "client picks their own" as a v0.3 requirement.
DEFAULT_SUBJECTS = [
    {"id": 1, "name": "English",              "colour": "#E5764C"},
    {"id": 2, "name": "Mathematics",          "colour": "#4C8FE5"},
    {"id": 3, "name": "Software Engineering", "colour": "#7B68EE"},
]


def user_path(u: str) -> Path:
    safe = "".join(c for c in u if c.isalnum() or c in "._-@").lower()
    return DATA_DIR / f"{safe}.json"


def load_user(u: str):
    p = user_path(u)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_user(data: dict) -> None:
    # NOTE: non-atomic — a power loss mid-write can corrupt the file.
    # Will switch to a temp-file swap in v0.3 after a tester reports it.
    user_path(data["username"]).write_text(json.dumps(data, indent=2))


app = Flask(__name__)
app.secret_key = "v0.2-dev-only"

MOCK_TASKS = [
    {"name": "Software Eng Folio Submission", "subject": "SE",   "due": "2026-05-29",
     "weighting": 30, "hours": 12, "score": 9999, "colour": "#7B68EE", "crit": True},
    {"name": "Maths Topic Test",              "subject": "Maths","due": "2026-05-22",
     "weighting": 25, "hours": 6,  "score": 50,   "colour": "#4C8FE5", "crit": False},
    {"name": "English Essay Draft",           "subject": "Eng",  "due": "2026-05-30",
     "weighting": 15, "hours": 8,  "score": 12.5, "colour": "#E5764C", "crit": False},
]


@app.route("/")
def splash():
    return render_template("splash.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # No validation yet — just stash the username and go.
        session["user"] = request.form.get("username") or "demo"
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"], tasks=MOCK_TASKS)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("splash"))


if __name__ == "__main__":
    app.run(port=5050, debug=True)
