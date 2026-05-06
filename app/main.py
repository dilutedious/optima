"""Flask app factory + route handlers."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from flask import (
    Flask, redirect, render_template, request, session, url_for,
)

from .auth import hash_password, verify_password
from .priority import rank_assignments
from .scheduler import generate_schedule, calculate_cushion
from .storage import Storage


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


DEFAULT_SUBJECTS = [
    {"id": 1, "name": "English",              "colour": "#E5764C"},
    {"id": 2, "name": "Mathematics",          "colour": "#4C8FE5"},
    {"id": 3, "name": "Software Engineering", "colour": "#7B68EE"},
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
            if user is None or not verify_password(pw, user["password_hash"]):
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
            storage.save_user({
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

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("splash"))

    @app.route("/dashboard")
    def dashboard():
        if "user" not in session:
            return redirect(url_for("login"))
        user = storage.load_user(session["user"])
        ranked = rank_assignments(user["assignments"], date.today())
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
            nid = max((a["id"] for a in user["assignments"]), default=0) + 1
            user["assignments"].append({
                "id": nid,
                "subject_id": int(request.form.get("subject_id", "1")),
                "name": request.form["name"],
                "due_date": request.form["due_date"],
                "weighting": float(request.form["weighting"]),
                "hours_required": float(request.form["hours_required"]),
            })
            storage.save_user(user)
            return redirect(url_for("dashboard"))
        return render_template("task_form.html", user=user)

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
