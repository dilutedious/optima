"""Flask app factory + route handlers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from flask import (
    Flask, redirect, render_template, request, session, url_for,
)

from .auth import generate_salt, hash_password, verify_password
from .models import Assignment, Constraint, Subject, User
from .priority import rank_assignments
from .scheduler import generate_schedule, calculate_cushion
from .storage import Storage


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def _build_month_grid(user: User, ref: date):
    """Return (events_by_day, week_rows). Each row has 7 date|None cells.
    Builds a 6-week grid starting from the Monday on or before the 1st."""
    first = ref.replace(day=1)
    grid_start = first - timedelta(days=first.weekday())
    rows = []
    cur = grid_start
    for _ in range(6):
        row = []
        for _ in range(7):
            row.append(cur if (cur.month == ref.month or
                               (cur - first).days < 35) else None)
            cur += timedelta(days=1)
        rows.append(row)
        if all(d is None or d.month != ref.month for d in rows[-1]):
            rows.pop()
            break
    events = {}
    for a in user.assignments:
        events.setdefault(a.due_date, []).append({
            "name": a.name,
            "colour": (user.subject_by_id(a.subject_id).colour
                       if user.subject_by_id(a.subject_id) else "#7B68EE"),
        })
    return events, rows


def _default_subjects() -> list[Subject]:
    return [
        Subject(id=1, name="English",              colour="#E5764C"),
        Subject(id=2, name="Mathematics",          colour="#4C8FE5"),
        Subject(id=3, name="Software Engineering", colour="#7B68EE"),
    ]


def create_app(data_dir: Optional[Path] = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = "v0.3-dev-only"
    storage = Storage(data_dir or DATA_DIR)

    @app.route("/")
    def splash():
        return render_template("splash.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            u = (request.form.get("username") or "").strip()
            pw = request.form.get("password") or ""
            user = storage.load_user(u)
            if user is None or not verify_password(pw, user.salt, user.password_hash):
                return render_template("login.html",
                                       error="Wrong username or password.")
            session["user"] = u
            return redirect(url_for("dashboard"))
        return render_template("login.html", error=None)

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            u = (request.form.get("username") or "").strip()
            pw = request.form.get("password") or ""
            if storage.user_exists(u):
                return render_template("signup.html",
                                       error="Username already taken.")
            salt = generate_salt()
            user = User(
                username=u,
                password_hash=hash_password(pw, salt),
                salt=salt,
                subjects=_default_subjects(),
                wake_time=7.0,
                bed_time=22.0,
            )
            storage.save_user(user)
            session["user"] = u
            return redirect(url_for("dashboard"))
        return render_template("signup.html", error=None)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("splash"))

    @app.route("/dashboard")
    def dashboard():
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        ranked = rank_assignments(user.assignments, date.today())
        total_workload, total_free, cushion = calculate_cushion(
            user, date.today())
        return render_template("dashboard.html",
                               user=user, ranked=ranked,
                               total_workload=total_workload,
                               total_free=total_free, cushion=cushion)

    @app.route("/task/new", methods=["GET", "POST"])
    def new_task():
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        if request.method == "POST":
            nid = max((a.id for a in user.assignments), default=0) + 1
            user.assignments.append(Assignment(
                id=nid,
                subject_id=int(request.form.get("subject_id", "1")),
                name=request.form["name"],
                due_date=request.form["due_date"],
                weighting=float(request.form["weighting"]),
                hours_required=float(request.form["hours_required"]),
            ))
            storage.save_user(user)
            return redirect(url_for("dashboard"))
        return render_template("task_form.html", user=user)

    @app.route("/preferences", methods=["GET", "POST"])
    def preferences():
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        if request.method == "POST":
            p = user.preferences
            p.theme = "dark" if request.form.get("theme") == "dark" else "light"
            p.notifications = bool(request.form.get("notifications"))
            user.wake_time = float(request.form.get("wake_time", user.wake_time))
            user.bed_time = float(request.form.get("bed_time", user.bed_time))
            storage.save_user(user)
            return redirect(url_for("preferences"))
        return render_template("preferences.html", user=user)

    @app.route("/subjects/new", methods=["POST"])
    def subjects_new():
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        nid = max((s.id for s in user.subjects), default=0) + 1
        user.subjects.append(Subject(id=nid,
                                     name=request.form["name"],
                                     colour=request.form.get("colour", "#7B68EE")))
        storage.save_user(user)
        return redirect(url_for("preferences"))

    @app.route("/subjects/<int:subject_id>/delete", methods=["POST"])
    def subjects_delete(subject_id: int):
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        user.subjects = [s for s in user.subjects if s.id != subject_id]
        storage.save_user(user)
        return redirect(url_for("preferences"))

    @app.route("/constraints/new", methods=["POST"])
    def constraints_new():
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        nid = max((c.id for c in user.constraints), default=0) + 1
        user.constraints.append(Constraint(
            id=nid,
            name=request.form["name"],
            subject_id=int(request.form["subject_id"]) if request.form.get("subject_id") else None,
            day_of_fortnight=int(request.form["day_of_fortnight"]),
            start_time=float(request.form["start_time"]),
            end_time=float(request.form["end_time"]),
        ))
        storage.save_user(user)
        return redirect(url_for("preferences"))

    @app.route("/constraints/<int:cid>/delete", methods=["POST"])
    def constraints_delete(cid: int):
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        user.constraints = [c for c in user.constraints if c.id != cid]
        storage.save_user(user)
        return redirect(url_for("preferences"))

    @app.route("/monthly")
    def monthly():
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        ref_str = request.args.get("month")
        ref = (datetime.strptime(ref_str, "%Y-%m").date()
               if ref_str else date.today().replace(day=1))
        grid, weeks = _build_month_grid(user, ref)
        prev_ref = (ref.replace(day=1) - timedelta(days=1)).replace(day=1)
        next_year = ref.year + (1 if ref.month == 12 else 0)
        next_month = 1 if ref.month == 12 else ref.month + 1
        next_ref = ref.replace(year=next_year, month=next_month, day=1)
        return render_template("monthly.html",
                               user=user, ref=ref,
                               grid=grid, weeks=weeks,
                               prev_month=prev_ref.strftime("%Y-%m"),
                               next_month=next_ref.strftime("%Y-%m"),
                               today=date.today(),
                               subjects_by_id={s.id: s for s in user.subjects})

    @app.route("/weekly")
    def weekly():
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        days = [monday + timedelta(days=i) for i in range(7)]
        blocks = generate_schedule(user, days)
        return render_template("weekly.html",
                               user=user, days=days, blocks=blocks,
                               hours=list(range(7, 23)))

    return app
