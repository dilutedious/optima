"""
Optima — Prototype v0.2
Date: 2026-05-03
Build status: Functional core. Weekly view + scheduling engine landed.

Whats new vs v0.1:
- SHA-256 password hashing (no salt yet — flagged in feedback round 2)
- JSON persistence per user
- Real priority calculator with the (weight*10)/days formula
- Urgency override (<=3 days)
- Greedy scheduling engine that drops study blocks into free slots
- Weekly view grid
- Cushion gauge (numerical only — donut SVG comes in v0.3)

Still missing:
- Monthly view
- Preferences (theme, contrast, focus, zoom)
- Splash animation
- Per-user salt (auth.py uses a global salt — bad practice, fix in v0.3)

Run:
    python3 app.py
Then open http://127.0.0.1:5050/
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for


DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
GLOBAL_SALT = "optima-prototype-salt"  # TODO: per-user salt in v0.3

app = Flask(__name__)
app.secret_key = "v0.2-dev-only"


def hash_password(plain: str) -> str:
    return hashlib.sha256((GLOBAL_SALT + plain).encode()).hexdigest()


def user_path(u: str) -> Path:
    safe = "".join(c for c in u if c.isalnum() or c in "._-@").lower()
    return DATA_DIR / f"{safe}.json"


def load_user(u: str):
    p = user_path(u)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_user(data: dict) -> None:
    # NOTE: non-atomic write — a power loss mid-write can corrupt the file.
    # Will switch to a temp-file swap in v0.3 after a tester reported a
    # truncated file when they force-quit the app.
    user_path(data["username"]).write_text(json.dumps(data, indent=2))


def priority(weight: float, days: int) -> float:
    if days <= 3:
        return 999.0
    return (weight * 10) / max(days, 1)


@app.route("/")
def splash():
    if session.get("user"):
        return redirect(url_for("dashboard"))
    return render_template("splash.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        pw = request.form.get("password") or ""
        user = load_user(u)
        if not user or user.get("password_hash") != hash_password(pw):
            return render_template("login.html", error="Invalid credentials.")
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
        # Seed with default subjects so the tester has something to play with.
        save_user({
            "username": u,
            "password_hash": hash_password(pw),
            "subjects": [
                {"id": 1, "name": "English", "colour": "#E5764C"},
                {"id": 2, "name": "Mathematics", "colour": "#4C8FE5"},
                {"id": 3, "name": "Software Engineering", "colour": "#7B68EE"},
            ],
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
        days = (due - today).days
        a["days"] = days
        a["score"] = priority(a["weighting"], days)
        ranked.append(a)
    ranked.sort(key=lambda a: -a["score"])
    # Crude cushion: total hours required vs hours awake in next 14 days minus
    # 5h reserved per day for classes/meals.
    total_workload = sum(a["hours_required"] for a in ranked)
    awake_per_day = user["bed_time"] - user["wake_time"]
    free_per_day = max(0.0, awake_per_day - 8.0)   # crude: 8h classes/meals/etc
    total_free = free_per_day * 14
    cushion = total_free / total_workload if total_workload else 1.0
    return render_template("dashboard.html",
                           user=user, ranked=ranked,
                           total_free=total_free,
                           total_workload=total_workload,
                           cushion=cushion)


@app.route("/task/new", methods=["GET", "POST"])
def new_task():
    if "user" not in session:
        return redirect(url_for("login"))
    user = load_user(session["user"])
    if request.method == "POST":
        nid = max((a["id"] for a in user["assignments"]), default=0) + 1
        user["assignments"].append({
            "id": nid,
            "subject_id": int(request.form.get("subject_id", "1")),
            "name": request.form["name"],
            "due_date": request.form["due_date"],
            "weighting": float(request.form["weighting"]),
            "hours_required": float(request.form["hours_required"]),
        })
        save_user(user)
        return redirect(url_for("dashboard"))
    return render_template("task_form.html", user=user)


@app.route("/weekly")
def weekly():
    if "user" not in session:
        return redirect(url_for("login"))
    user = load_user(session["user"])
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    days = [monday + timedelta(days=i) for i in range(7)]
    # Greedy scheduler — drops blocks into the morning of each day.
    # KNOWN BUG (raised in feedback round 2): blocks can stack on top of each
    # other if two assignments are due the same day. Fixed in v0.3.
    today_ranked = []
    for a in user["assignments"]:
        due = datetime.strptime(a["due_date"], "%Y-%m-%d").date()
        days_left = (due - today).days
        a["score"] = priority(a["weighting"], days_left)
        today_ranked.append(a)
    today_ranked.sort(key=lambda a: -a["score"])

    blocks_per_day = {d.isoformat(): [] for d in days}
    cursor = {d.isoformat(): user["wake_time"] + 1.0 for d in days}
    for a in today_ranked:
        remaining = a["hours_required"]
        i = 0
        while remaining > 0 and i < len(days):
            d = days[i].isoformat()
            start = cursor[d]
            length = min(2.0, remaining, user["bed_time"] - start)
            if length < 0.5:
                i += 1
                continue
            blocks_per_day[d].append({
                "name": a["name"], "start": start, "end": start + length,
            })
            cursor[d] = start + length + 0.5
            remaining -= length
            i += 1
    return render_template("weekly.html",
                           user=user, days=days,
                           blocks=blocks_per_day,
                           hours=list(range(7, 23)))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("splash"))


if __name__ == "__main__":
    app.run(port=5050, debug=True)
