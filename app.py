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

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for


DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Shared salt across all accounts for this prototype. It's a security smell —
# two users with the same password get the same hash, so a leak is rainbow-
# attackable. Flagged in the v0.2 release notes; per-user salt lands in v0.3.
GLOBAL_SALT = "optima-prototype-salt"

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


def hash_password(plain: str) -> str:
    return hashlib.sha256((GLOBAL_SALT + plain).encode()).hexdigest()


def priority(weight: float, days: int) -> float:
    """Planning-doc formula. Anything inside the critical window jumps to
    999 so a 'due tomorrow' task can't be out-ranked by a heavier task with
    weeks of runway."""
    if days <= 3:
        return 999.0
    return (weight * 10) / max(days, 1)


app = Flask(__name__)
app.secret_key = "v0.2-dev-only"


@app.route("/")
def splash():
    return render_template("splash.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        pw = request.form.get("password") or ""
        user = load_user(u)
        if user is None or user["password_hash"] != hash_password(pw):
            return render_template("login.html", error="Wrong username or password.")
        session["user"] = u
        return redirect(url_for("dashboard"))
    return render_template("login.html", error=None)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        pw = request.form.get("password") or ""
        if user_path(u).exists():
            return render_template("signup.html", error="Username already taken.")
        save_user({
            "username": u,
            "password_hash": hash_password(pw),
            "subjects": list(DEFAULT_SUBJECTS),
            "assignments": [],
            "wake_time": 7.0,
            "bed_time": 22.0,
        })
        session["user"] = u
        return redirect(url_for("dashboard"))
    return render_template("signup.html", error=None)


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    user = load_user(session["user"])
    today = date.today()
    ranked = []
    for a in user["assignments"]:
        due = datetime.strptime(a["due_date"], "%Y-%m-%d").date()
        a["days"] = (due - today).days
        a["score"] = priority(a["weighting"], a["days"])
        ranked.append(a)
    ranked.sort(key=lambda a: -a["score"])
    return render_template("dashboard.html", user=user, ranked=ranked)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("splash"))


if __name__ == "__main__":
    app.run(port=5050, debug=True)
