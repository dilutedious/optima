"""Flask + pywebview entry point.

Launching this module starts a local Flask server on 127.0.0.1:5000 and pops
a native desktop window pointing at it (via pywebview). When the window
closes, the server shuts down.

Running with `--browser` skips pywebview and just leaves the server up so the
app can be inspected in a regular browser — useful during development and
testing.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .auth import (
    generate_salt,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)
from .models import Assignment, Constraint, Preferences, ScheduleBlock, Subject, User
from .priority import rank_assignments
from .scheduler import generate_schedule, calculate_cushion, find_free_slots
from .storage import Storage


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def _current_user(storage: Storage) -> Optional[User]:
    username = session.get("username")
    if not username:
        return None
    return storage.load_user(username)


def create_app(data_dir: Optional[Path] = None) -> Flask:
    data_dir = Path(data_dir or DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    storage = Storage(data_dir)

    app = Flask(__name__)
    app.secret_key = os.environ.get("OPTIMA_SECRET", "dev-only-not-for-prod-do-not-reuse")
    app.config["STORAGE"] = storage

    # -------- routes -----------------------------------------------------

    @app.route("/")
    def splash():
        if session.get("username"):
            return redirect(url_for("dashboard"))
        return render_template("splash.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = storage.load_user(username)
            if not user or not verify_password(password, user.salt, user.password_hash):
                flash("Invalid credentials. Please try again.", "error")
                return render_template("login.html", username=username), 401
            session["username"] = user.username
            return redirect(url_for("dashboard"))
        return render_template("login.html", username="")

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            confirm = request.form.get("confirm") or ""

            ok, err = validate_username(username)
            if not ok:
                flash(err, "error")
                return render_template("signup.html", username=username), 400
            ok, err = validate_password(password)
            if not ok:
                flash(err, "error")
                return render_template("signup.html", username=username), 400
            if password != confirm:
                flash("Passwords do not match.", "error")
                return render_template("signup.html", username=username), 400
            if storage.user_exists(username):
                flash("That username is already taken.", "error")
                return render_template("signup.html", username=username), 400

            salt = generate_salt()
            user = User(
                username=username,
                password_hash=hash_password(password, salt),
                salt=salt,
                term_start=date.today().isoformat(),
            )
            _seed_default_subjects(user)
            storage.save_user(user)
            session["username"] = user.username
            return redirect(url_for("dashboard"))
        return render_template("signup.html", username="")

    @app.route("/logout")
    def logout():
        session.pop("username", None)
        return redirect(url_for("splash"))

    # -------- protected pages --------------------------------------------

    def _require_user() -> User:
        user = _current_user(storage)
        if user is None:
            abort(401)
        return user

    @app.route("/dashboard")
    def dashboard():
        user = _current_user(storage)
        if user is None:
            return redirect(url_for("login"))
        ranked = rank_assignments(user.assignments)
        result = generate_schedule(user)
        # Persist priority scores + freshly generated blocks so the UI sees
        # the same data the scheduler just produced.
        user.schedule_blocks = result.blocks
        storage.save_user(user)
        cushion_pct = int(min(max(result.cushion, 0.0), 2.0) * 100 / 2)
        return render_template(
            "dashboard.html",
            user=user,
            ranked=ranked[:6],
            cushion=result,
            cushion_pct=cushion_pct,
            today_iso=date.today().isoformat(),
            subjects_by_id={s.id: s for s in user.subjects},
        )

    @app.route("/weekly")
    def weekly():
        user = _current_user(storage)
        if user is None:
            return redirect(url_for("login"))
        # Build a 5-day grid (Mon-Fri) plus optional weekend column.
        week_start = _monday_of(date.today())
        days = [week_start + timedelta(days=i) for i in range(7)]
        grid = _build_week_grid(user, days)
        return render_template(
            "weekly.html",
            user=user,
            days=days,
            grid=grid,
            hours=list(range(7, 23)),
            today=date.today(),
            subjects_by_id={s.id: s for s in user.subjects},
            assignments_by_id={a.id: a for a in user.assignments},
        )

    @app.route("/monthly")
    def monthly():
        user = _current_user(storage)
        if user is None:
            return redirect(url_for("login"))
        ref_str = request.args.get("month")
        ref = datetime.strptime(ref_str, "%Y-%m").date() if ref_str else date.today().replace(day=1)
        grid, weeks = _build_month_grid(user, ref)
        prev_ref = (ref.replace(day=1) - timedelta(days=1)).replace(day=1)
        next_year = ref.year + (1 if ref.month == 12 else 0)
        next_month = 1 if ref.month == 12 else ref.month + 1
        next_ref = ref.replace(year=next_year, month=next_month, day=1)
        return render_template(
            "monthly.html",
            user=user,
            ref=ref,
            grid=grid,
            weeks=weeks,
            prev_month=prev_ref.strftime("%Y-%m"),
            next_month=next_ref.strftime("%Y-%m"),
            today=date.today(),
            subjects_by_id={s.id: s for s in user.subjects},
        )

    @app.route("/preferences", methods=["GET", "POST"])
    def preferences():
        user = _current_user(storage)
        if user is None:
            return redirect(url_for("login"))
        if request.method == "POST":
            p = user.preferences
            p.theme = "dark" if request.form.get("theme") == "dark" else "light"
            p.notifications = bool(request.form.get("notifications"))
            p.auto_save = bool(request.form.get("auto_save"))
            # v0.3: theme + notifications only. High contrast, focus
            # highlights, zoom planned for next iteration.
            storage.save_user(user)
            flash("Preferences saved.", "ok")
            return redirect(url_for("preferences"))
        return render_template("preferences.html", user=user)

    # -------- assignment / subject CRUD ----------------------------------

    @app.route("/tasks/new", methods=["GET", "POST"])
    def new_task():
        user = _require_user()
        if request.method == "POST":
            try:
                subject_id = int(request.form.get("subject_id", "0"))
                weighting = float(request.form.get("weighting", "0"))
                hours = float(request.form.get("hours_required", "0"))
            except ValueError:
                flash("Numbers must be valid.", "error")
                return render_template("task_form.html", user=user, task=None), 400
            name = (request.form.get("name") or "").strip()
            due = (request.form.get("due_date") or "").strip()
            if not name or not due:
                flash("Name and due date are required.", "error")
                return render_template("task_form.html", user=user, task=None), 400
            a = Assignment(
                id=user.next_assignment_id(),
                subject_id=subject_id,
                name=name,
                due_date=due,
                weighting=weighting,
                hours_required=hours,
                est_hours=hours,
            )
            user.assignments.append(a)
            storage.save_user(user)
            return redirect(url_for("dashboard"))
        return render_template("task_form.html", user=user, task=None)

    @app.route("/tasks/<int:task_id>", methods=["GET", "POST"])
    def edit_task(task_id: int):
        user = _require_user()
        task = next((a for a in user.assignments if a.id == task_id), None)
        if task is None:
            abort(404)
        if request.method == "POST":
            action = request.form.get("action")
            if action == "delete":
                user.assignments = [a for a in user.assignments if a.id != task_id]
                storage.save_user(user)
                return redirect(url_for("dashboard"))
            task.subject_id = int(request.form.get("subject_id", task.subject_id))
            task.name = (request.form.get("name") or task.name).strip()
            task.due_date = (request.form.get("due_date") or task.due_date).strip()
            try:
                task.weighting = float(request.form.get("weighting", task.weighting))
                task.hours_required = float(request.form.get("hours_required", task.hours_required))
                task.completion_percent = max(0.0, min(1.0, float(request.form.get("completion_percent", task.completion_percent))))
            except ValueError:
                flash("Numbers must be valid.", "error")
            task.completed = task.completion_percent >= 1.0
            storage.save_user(user)
            return redirect(url_for("dashboard"))
        return render_template("task_form.html", user=user, task=task)

    @app.route("/api/tasks/<int:task_id>/progress", methods=["POST"])
    def api_set_progress(task_id: int):
        user = _require_user()
        try:
            pct = max(0.0, min(1.0, float(request.json.get("completion_percent", 0))))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Invalid number"), 400
        for a in user.assignments:
            if a.id == task_id:
                a.completion_percent = pct
                a.completed = pct >= 1.0
                # Reward XP when a task crosses to complete
                if a.completed:
                    user.study_points += int(a.weighting)
                storage.save_user(user)
                return jsonify(ok=True, completion_percent=pct, study_points=user.study_points)
        return jsonify(ok=False, error="Not found"), 404

    @app.route("/subjects/new", methods=["POST"])
    def new_subject():
        user = _require_user()
        name = (request.form.get("name") or "").strip()
        colour = (request.form.get("colour") or "#7B68EE").strip()
        if not name:
            flash("Subject name is required.", "error")
            return redirect(url_for("preferences"))
        s = Subject(id=user.next_subject_id(), name=name, colour=colour)
        user.subjects.append(s)
        storage.save_user(user)
        return redirect(url_for("preferences"))

    @app.route("/subjects/<int:subject_id>/delete", methods=["POST"])
    def delete_subject(subject_id: int):
        user = _require_user()
        user.subjects = [s for s in user.subjects if s.id != subject_id]
        # Unassign any assignments that reference this subject.
        for a in user.assignments:
            if a.subject_id == subject_id:
                a.subject_id = 0
        storage.save_user(user)
        return redirect(url_for("preferences"))

    @app.route("/constraints/new", methods=["POST"])
    def new_constraint():
        user = _require_user()
        try:
            start = float(request.form.get("start_time", "0"))
            end = float(request.form.get("end_time", "0"))
            day_idx = int(request.form.get("day_of_fortnight", "0"))
        except ValueError:
            flash("Constraint times must be numbers.", "error")
            return redirect(url_for("preferences"))
        c = Constraint(
            name=(request.form.get("name") or "Class").strip(),
            subject_id=int(request.form.get("subject_id", "0")) or None,
            day_of_fortnight=max(0, min(13, day_idx)),
            start_time=start,
            end_time=end,
            is_study_period=bool(request.form.get("is_study_period")),
            is_half_period=bool(request.form.get("is_half_period")),
        )
        user.constraints.append(c)
        storage.save_user(user)
        return redirect(url_for("preferences"))

    @app.route("/constraints/<int:idx>/delete", methods=["POST"])
    def delete_constraint(idx: int):
        user = _require_user()
        if 0 <= idx < len(user.constraints):
            user.constraints.pop(idx)
            storage.save_user(user)
        return redirect(url_for("preferences"))

    # -------- error pages ------------------------------------------------

    @app.errorhandler(401)
    def _401(e):
        return render_template("error.html", code=401, message="Please log in to continue."), 401

    @app.errorhandler(404)
    def _404(e):
        return render_template("error.html", code=404, message="That page doesn't exist."), 404

    return app


# ----------- helpers used by routes --------------------------------------

def _seed_default_subjects(user: User) -> None:
    palette = [
        ("English", "#E5764C"),
        ("Mathematics", "#4C8FE5"),
        ("Software Engineering", "#7B68EE"),
        ("Physics", "#36B37E"),
        ("Modern History", "#D4AC0D"),
    ]
    for i, (name, col) in enumerate(palette, start=1):
        user.subjects.append(Subject(id=i, name=name, colour=col))


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _build_week_grid(user: User, days: list[date]) -> dict[str, list]:
    """Build a dict[date_iso] -> list of {kind, name, colour, start, end}."""
    grid: dict[str, list] = {d.isoformat(): [] for d in days}
    # Constraints (classes)
    for d in days:
        day_idx = (d - datetime.strptime(user.term_start, "%Y-%m-%d").date()).days % 14 if user.term_start else 0
        for c in user.constraints:
            if c.day_of_fortnight != day_idx:
                continue
            subj = user.subject_by_id(c.subject_id) if c.subject_id else None
            grid[d.isoformat()].append({
                "kind": "class",
                "name": c.name,
                "colour": (subj.colour if subj else "#9aa0a6"),
                "start": c.start_time,
                "end": c.end_time,
                "is_study_period": c.is_study_period,
            })
    # Study blocks
    for b in user.schedule_blocks:
        if b.date_iso not in grid:
            continue
        a = next((aa for aa in user.assignments if aa.id == b.assignment_id), None)
        if a is None:
            continue
        subj = user.subject_by_id(a.subject_id) if a else None
        grid[b.date_iso].append({
            "kind": "block",
            "name": a.name,
            "colour": (subj.colour if subj else "#7B68EE"),
            "start": b.start_time,
            "end": b.start_time + b.duration,
            "completed": b.completed,
        })
    return grid


def _build_month_grid(user: User, ref: date) -> tuple[dict, list[list[date | None]]]:
    """Return (events_by_day, week_rows). Each row has 7 date|None cells."""
    first = ref.replace(day=1)
    # First day of the calendar grid — back up to Monday.
    grid_start = first - timedelta(days=first.weekday())
    rows: list[list[date | None]] = []
    cur = grid_start
    for _ in range(6):
        row = []
        for _ in range(7):
            row.append(cur if (cur.month == ref.month or (cur.month != ref.month and (cur - first).days < 35)) else None)
            cur += timedelta(days=1)
        rows.append(row)
        if cur.month != ref.month and rows[-1][-1] and rows[-1][-1].month != ref.month:  # type: ignore[index]
            # If the last row is entirely next month, drop it.
            if all(d is None or d.month != ref.month for d in rows[-1]):
                rows.pop()
                break
    events: dict[str, list[dict]] = {}
    for a in user.assignments:
        events.setdefault(a.due_date, []).append({
            "name": a.name,
            "colour": (user.subject_by_id(a.subject_id).colour if user.subject_by_id(a.subject_id) else "#7B68EE"),
            "completed": a.completed,
            "kind": "due",
        })
    for b in user.schedule_blocks:
        events.setdefault(b.date_iso, []).append({
            "name": next((a.name for a in user.assignments if a.id == b.assignment_id), "Study"),
            "colour": "#7B68EE",
            "completed": b.completed,
            "kind": "block",
        })
    return events, rows


# --------- launcher ------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="optima")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open the app in your default browser instead of a native window.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OPTIMA_PORT", "5050")),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )
    args = parser.parse_args(argv)

    app = create_app()

    if args.browser:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
        return 0

    # Start Flask in a background thread; pywebview owns the main thread.
    def _serve():
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    try:
        import webview  # type: ignore
    except ImportError:
        print(
            "pywebview is not installed — falling back to browser mode. "
            "Run with --browser to skip this message.",
            file=sys.stderr,
        )
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
        return 0

    webview.create_window(
        "Optima — Automated Study Flow",
        f"http://{args.host}:{args.port}/",
        width=1280,
        height=820,
        min_size=(960, 640),
    )
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
