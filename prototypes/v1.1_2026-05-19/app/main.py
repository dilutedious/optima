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
import time
from collections import defaultdict
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
from .crypto import derive_key, encrypt, decrypt
from .models import Assignment, Constraint, Preferences, ScheduleBlock, Subject, User
from .priority import rank_assignments
from .scheduler import generate_schedule, calculate_cushion, find_free_slots
from .storage import Storage


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


# ---------------------------------------------------------------------------
# Login rate-limiting
# Per-username sliding window. After MAX_FAILS failures within WINDOW seconds,
# further attempts are rejected for COOLDOWN seconds. Lives in-process; resets
# on application restart, which is fine for an offline desktop app.
# ---------------------------------------------------------------------------
MAX_FAILS = 5
WINDOW = 5 * 60      # 5 minutes
COOLDOWN = 60        # 60 seconds lockout
_LOGIN_FAILS: dict[str, list[float]] = defaultdict(list)
_LOGIN_LOCKED_UNTIL: dict[str, float] = {}


def _login_locked_seconds(username: str) -> int:
    """If the username is currently locked out, return remaining seconds; else 0."""
    locked_until = _LOGIN_LOCKED_UNTIL.get(username, 0.0)
    remaining = locked_until - time.time()
    return int(remaining) if remaining > 0 else 0


def _record_login_failure(username: str) -> int:
    """Track a failure and apply lockout if the threshold is exceeded.

    Returns the cooldown seconds (0 if not yet locked).
    """
    now = time.time()
    bucket = [t for t in _LOGIN_FAILS[username] if now - t < WINDOW]
    bucket.append(now)
    _LOGIN_FAILS[username] = bucket
    if len(bucket) >= MAX_FAILS:
        _LOGIN_LOCKED_UNTIL[username] = now + COOLDOWN
        _LOGIN_FAILS[username] = []
        return COOLDOWN
    return 0


def _clear_login_failures(username: str) -> None:
    _LOGIN_FAILS.pop(username, None)
    _LOGIN_LOCKED_UNTIL.pop(username, None)


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------
def _coerce_float(raw, *, default: float = 0.0, lo: float | None = None,
                  hi: float | None = None) -> tuple[float, Optional[str]]:
    """Convert raw to float, optionally clamping. Returns (value, error)."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default, "must be a number"
    if lo is not None and v < lo:
        return default, f"must be at least {lo}"
    if hi is not None and v > hi:
        return default, f"must be at most {hi}"
    return v, None


def _coerce_int(raw, *, default: int = 0, lo: int | None = None,
                hi: int | None = None) -> tuple[int, Optional[str]]:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default, "must be an integer"
    if lo is not None and v < lo:
        return default, f"must be at least {lo}"
    if hi is not None and v > hi:
        return default, f"must be at most {hi}"
    return v, None


def _coerce_hours_minutes(hours_raw, minutes_raw, *, decimal_fallback=None,
                          lo: float = 0.0, hi: float = 200.0) -> tuple[float, Optional[str]]:
    """Combine "hours" + "minutes" form fields into a decimal-hours float.

    If both are blank (or unparseable) the caller-supplied ``decimal_fallback``
    field is parsed instead — that keeps the API and old serialisations
    working when only ``hours_required`` is posted.
    """
    h_present = hours_raw not in (None, "")
    m_present = minutes_raw not in (None, "")
    if h_present or m_present:
        h, err = _coerce_int(hours_raw or 0, lo=0, hi=int(hi))
        if err:
            return 0.0, f"hours {err}"
        m, err = _coerce_int(minutes_raw or 0, lo=0, hi=59)
        if err:
            return 0.0, f"minutes {err}"
        total = h + m / 60.0
        if total < lo:
            return 0.0, f"must be at least {lo}"
        if total > hi:
            return 0.0, f"must be at most {hi}"
        # Snap to the nearest minute so rounding never re-creates noise.
        return round(total * 60) / 60.0, None
    return _coerce_float(decimal_fallback, lo=lo, hi=hi)


def _coerce_date(raw, *, allow_past: bool = False) -> tuple[Optional[date], Optional[str]]:
    if not raw:
        return None, "is required"
    try:
        d = datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None, "must look like YYYY-MM-DD"
    if not allow_past and d < date.today():
        return None, "must be today or later"
    return d, None


def _current_user(storage: Storage) -> Optional[User]:
    username = session.get("username")
    if not username:
        return None
    user = storage.load_user(username)
    if user and user.migrate_constraints():
        # Heal legacy constraint data once on first access in this process.
        storage.save_user(user)
    return user


def _session_key() -> Optional[bytes]:
    """The user's derived encryption key, stored hex-encoded in the session."""
    hex_key = session.get("derived_key")
    if not hex_key:
        return None
    try:
        return bytes.fromhex(hex_key)
    except ValueError:
        return None


def _set_session_key(password: str, salt_hex: str) -> None:
    session["derived_key"] = derive_key(password, salt_hex).hex()


def _decrypt_note(token: str) -> str:
    """Best-effort decrypt of a private note. Returns empty string on failure
    so the UI can still render the rest of the task."""
    key = _session_key()
    if not token or not key:
        return ""
    try:
        return decrypt(token, key)
    except ValueError:
        return ""


def _encrypt_note(plain: str) -> str:
    plain = (plain or "").strip()
    if not plain:
        return ""
    key = _session_key()
    if not key:
        # Should never happen in a logged-in flow, but if the session lost
        # its key, refuse to silently lose the user's text — store as
        # plaintext with a leading marker so we can detect on next decrypt.
        return ""
    return encrypt(plain, key)


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

            cooldown = _login_locked_seconds(username)
            if cooldown > 0:
                flash(
                    f"Too many failed attempts. Try again in {cooldown}s.",
                    "error",
                )
                return render_template("login.html", username=username), 429

            user = storage.load_user(username)
            if not user or not verify_password(password, user.salt, user.password_hash):
                lockout = _record_login_failure(username)
                if lockout:
                    flash(
                        f"Too many failed attempts. Account locked for {lockout}s.",
                        "error",
                    )
                else:
                    flash("Invalid credentials. Please try again.", "error")
                return render_template("login.html", username=username), 401

            _clear_login_failures(username)
            session["username"] = user.username
            _set_session_key(password, user.salt)
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
            _set_session_key(password, salt)
            return redirect(url_for("dashboard"))
        return render_template("signup.html", username="")

    @app.route("/logout")
    def logout():
        session.pop("username", None)
        session.pop("derived_key", None)
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
        # Optional ?week=YYYY-MM-DD argument lets the user paginate weeks; the
        # JS layer needs this for prev/next without a full reload.
        anchor_str = request.args.get("week")
        try:
            anchor = datetime.strptime(anchor_str, "%Y-%m-%d").date() if anchor_str else date.today()
        except ValueError:
            anchor = date.today()
        week_start = _monday_of(anchor)
        days = [week_start + timedelta(days=i) for i in range(7)]
        return render_template(
            "weekly.html",
            user=user,
            days=days,
            week_start=week_start,
            prev_week=(week_start - timedelta(days=7)).isoformat(),
            next_week=(week_start + timedelta(days=7)).isoformat(),
            hours=list(range(7, 23)),
            today=date.today(),
            subjects_by_id={s.id: s for s in user.subjects},
            assignments_by_id={a.id: a for a in user.assignments},
        )

    # -------- calendar JSON API ------------------------------------------
    # The weekly view drives all of its CRUD through these endpoints so the
    # user can click-to-add, drag-to-move, multi-delete etc. without page
    # reloads. The wire format always speaks decimal hours.

    def _parse_date(raw: str) -> Optional[date]:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    def _expand_constraints(user: User, start: date, end: date) -> list[dict]:
        """All Constraint occurrences in [start, end] (inclusive) as dicts."""
        out: list[dict] = []
        cur = start
        while cur <= end:
            for c in user.constraints:
                if c.occurs_on(cur):
                    view = c.occurrence_view(cur)
                    subj = user.subject_by_id(c.subject_id) if c.subject_id else None
                    view["subject_name"] = subj.name if subj else None
                    view["colour"] = subj.colour if subj else "#9aa0a6"
                    out.append(view)
            cur += timedelta(days=1)
        return out

    def _expand_blocks(user: User, start: date, end: date) -> list[dict]:
        out: list[dict] = []
        for b in user.schedule_blocks:
            bd = _parse_date(b.date_iso)
            if bd is None or bd < start or bd > end:
                continue
            a = next((aa for aa in user.assignments if aa.id == b.assignment_id), None)
            subj = user.subject_by_id(a.subject_id) if a else None
            out.append({
                "assignment_id": b.assignment_id,
                "date": b.date_iso,
                "start_time": b.start_time,
                "end_time": b.start_time + b.duration,
                "name": a.name if a else "Study session",
                "colour": subj.colour if subj else "#7B68EE",
                "completed": b.completed,
            })
        return out

    @app.route("/api/events")
    def api_events_list():
        user = _require_user()
        start = _parse_date(request.args.get("start", "")) or date.today()
        end = _parse_date(request.args.get("end", "")) or (start + timedelta(days=6))
        if end < start:
            start, end = end, start
        return jsonify(
            events=_expand_constraints(user, start, end),
            blocks=_expand_blocks(user, start, end),
            subjects=[{"id": s.id, "name": s.name, "colour": s.colour} for s in user.subjects],
            time_format=user.preferences.time_format,
        )

    def _coerce_event_payload(payload: dict) -> tuple[dict, list[str]]:
        """Validate the JSON body for create/update. Returns (clean, errors)."""
        errors: list[str] = []
        name = (payload.get("name") or "").strip() or "Event"
        if len(name) > 120:
            errors.append("Event name must be 120 characters or fewer.")
        start, err = _coerce_float(payload.get("start_time"), lo=0.0, hi=24.0)
        if err:
            errors.append(f"Start time {err}.")
        end, err = _coerce_float(payload.get("end_time"), lo=0.0, hi=24.0)
        if err:
            errors.append(f"End time {err}.")
        if not errors and end <= start:
            errors.append("End time must be after start time.")
        # Snap to 5-min grid so we never store sub-minute noise.
        start = round(start * 12) / 12
        end = round(end * 12) / 12
        recurrence = payload.get("recurrence", "weekly")
        from .models import RECURRENCES as _R, EVENT_KINDS as _K
        if recurrence not in _R:
            errors.append("Unknown recurrence.")
            recurrence = "weekly"
        kind = payload.get("kind", "subject")
        if kind not in _K:
            errors.append("Unknown event kind.")
            kind = "subject"
        anchor_date = (payload.get("anchor_date") or "").strip()
        if not _parse_date(anchor_date):
            errors.append("Anchor date must be YYYY-MM-DD.")
        sid_raw = payload.get("subject_id")
        subject_id: Optional[int] = None
        if sid_raw not in (None, "", 0, "0"):
            try:
                subject_id = int(sid_raw)
            except (TypeError, ValueError):
                errors.append("Subject id must be an integer.")
        return ({
            "name": name,
            "start_time": start,
            "end_time": end,
            "recurrence": recurrence,
            "kind": kind,
            "anchor_date": anchor_date,
            "subject_id": subject_id,
            "is_study_period": bool(payload.get("is_study_period")),
            "is_half_period": bool(payload.get("is_half_period")),
        }, errors)

    @app.route("/api/events", methods=["POST"])
    def api_event_create():
        user = _require_user()
        clean, errors = _coerce_event_payload(request.get_json(silent=True) or {})
        if errors:
            return jsonify(ok=False, errors=errors), 400
        if clean["subject_id"] and not any(s.id == clean["subject_id"] for s in user.subjects):
            return jsonify(ok=False, errors=["Unknown subject."]), 400
        c = Constraint(
            id=user.next_constraint_id(),
            name=clean["name"],
            subject_id=clean["subject_id"],
            start_time=clean["start_time"],
            end_time=clean["end_time"],
            anchor_date=clean["anchor_date"],
            recurrence=clean["recurrence"],
            kind=clean["kind"],
            is_study_period=clean["is_study_period"],
            is_half_period=clean["is_half_period"],
        )
        user.constraints.append(c)
        storage.save_user(user)
        return jsonify(ok=True, id=c.id)

    @app.route("/api/events/<int:cid>", methods=["PUT", "PATCH"])
    def api_event_update(cid: int):
        user = _require_user()
        c = user.constraint_by_id(cid)
        if c is None:
            return jsonify(ok=False, errors=["Event not found."]), 404
        body = request.get_json(silent=True) or {}
        scope = body.get("scope", "all")   # "all" or "this"
        if scope not in ("all", "this"):
            return jsonify(ok=False, errors=["scope must be 'all' or 'this'."]), 400

        if scope == "this":
            # Edit only one occurrence by storing an override keyed on that date.
            on_date = body.get("on_date")
            if not _parse_date(on_date or ""):
                return jsonify(ok=False, errors=["on_date is required for scope=this."]), 400
            override = c.overrides.get(on_date, {})
            for field_name in ("name", "start_time", "end_time"):
                if field_name in body:
                    if field_name in ("start_time", "end_time"):
                        v, err = _coerce_float(body[field_name], lo=0.0, hi=24.0)
                        if err:
                            return jsonify(ok=False, errors=[f"{field_name} {err}."]), 400
                        override[field_name] = round(v * 12) / 12
                    else:
                        override[field_name] = str(body[field_name]).strip()[:120]
            # Validate the resulting times for this instance.
            eff_start = override.get("start_time", c.start_time)
            eff_end = override.get("end_time", c.end_time)
            if eff_end <= eff_start:
                return jsonify(ok=False, errors=["End must be after start."]), 400
            c.overrides[on_date] = override
            storage.save_user(user)
            return jsonify(ok=True)

        # scope == "all" — edit the master event.
        merged = {
            "name": body.get("name", c.name),
            "start_time": body.get("start_time", c.start_time),
            "end_time": body.get("end_time", c.end_time),
            "recurrence": body.get("recurrence", c.recurrence),
            "kind": body.get("kind", c.kind),
            "anchor_date": body.get("anchor_date", c.anchor_date),
            "subject_id": body.get("subject_id", c.subject_id),
            "is_study_period": body.get("is_study_period", c.is_study_period),
            "is_half_period": body.get("is_half_period", c.is_half_period),
        }
        clean, errors = _coerce_event_payload(merged)
        if errors:
            return jsonify(ok=False, errors=errors), 400
        if clean["subject_id"] and not any(s.id == clean["subject_id"] for s in user.subjects):
            return jsonify(ok=False, errors=["Unknown subject."]), 400
        c.name = clean["name"]
        c.start_time = clean["start_time"]
        c.end_time = clean["end_time"]
        c.recurrence = clean["recurrence"]
        c.kind = clean["kind"]
        c.anchor_date = clean["anchor_date"]
        c.subject_id = clean["subject_id"]
        c.is_study_period = clean["is_study_period"]
        c.is_half_period = clean["is_half_period"]
        storage.save_user(user)
        return jsonify(ok=True)

    @app.route("/api/events/<int:cid>", methods=["DELETE"])
    def api_event_delete(cid: int):
        user = _require_user()
        c = user.constraint_by_id(cid)
        if c is None:
            return jsonify(ok=False, errors=["Event not found."]), 404
        scope = request.args.get("scope", "all")
        if scope == "this":
            on_date = request.args.get("date")
            if not _parse_date(on_date or ""):
                return jsonify(ok=False, errors=["date query param required when scope=this."]), 400
            if on_date not in c.skip_dates:
                c.skip_dates.append(on_date)
            # Drop any override that no longer applies.
            c.overrides.pop(on_date, None)
            storage.save_user(user)
            return jsonify(ok=True)
        if scope == "all":
            user.constraints = [x for x in user.constraints if x.id != cid]
            storage.save_user(user)
            return jsonify(ok=True)
        return jsonify(ok=False, errors=["scope must be 'all' or 'this'."]), 400

    @app.route("/api/events/move", methods=["POST"])
    def api_events_move():
        """Bulk-move occurrences (drag handler ships one request per drop).

        Body: {moves: [{id, on_date, new_start, new_end, scope}]} — each move
        is treated as an override on that one instance unless scope=all.
        """
        user = _require_user()
        moves = (request.get_json(silent=True) or {}).get("moves") or []
        if not isinstance(moves, list):
            return jsonify(ok=False, errors=["moves must be a list."]), 400
        errors: list[str] = []
        for m in moves:
            try:
                cid = int(m.get("id"))
            except (TypeError, ValueError):
                errors.append("Each move needs an integer id.")
                continue
            c = user.constraint_by_id(cid)
            if c is None:
                errors.append(f"Event {cid} not found.")
                continue
            start, err = _coerce_float(m.get("new_start"), lo=0.0, hi=24.0)
            if err:
                errors.append(f"Move for {cid}: start {err}.")
                continue
            end, err = _coerce_float(m.get("new_end"), lo=0.0, hi=24.0)
            if err:
                errors.append(f"Move for {cid}: end {err}.")
                continue
            if end <= start:
                errors.append(f"Move for {cid}: end must be after start.")
                continue
            start = round(start * 12) / 12
            end = round(end * 12) / 12
            scope = m.get("scope", "this")
            if scope == "all":
                delta = start - c.start_time
                c.start_time = start
                c.end_time = c.end_time + delta
                if c.end_time <= c.start_time:
                    c.end_time = end
            else:
                on_date = m.get("on_date")
                if not _parse_date(on_date or ""):
                    errors.append(f"Move for {cid}: on_date required when scope=this.")
                    continue
                ov = c.overrides.get(on_date, {})
                ov["start_time"] = start
                ov["end_time"] = end
                c.overrides[on_date] = ov
        storage.save_user(user)
        if errors:
            return jsonify(ok=False, errors=errors), 400
        return jsonify(ok=True)

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
            p.high_contrast = bool(request.form.get("high_contrast"))
            p.focus_highlights = bool(request.form.get("focus_highlights"))
            p.time_format = "12h" if request.form.get("time_format") == "12h" else "24h"
            try:
                p.zoom = max(75, min(150, int(request.form.get("zoom", "100"))))
            except ValueError:
                p.zoom = 100
            # Optional term-start update (the new week-A anchor).
            ts = (request.form.get("term_start") or "").strip()
            if ts:
                try:
                    datetime.strptime(ts, "%Y-%m-%d")
                    user.term_start = ts
                except ValueError:
                    flash("Term start must look like YYYY-MM-DD.", "error")
            storage.save_user(user)
            flash("Preferences saved.", "ok")
            return redirect(url_for("preferences"))
        return render_template("preferences.html", user=user)

    # -------- assignment / subject CRUD ----------------------------------

    @app.route("/tasks/new", methods=["GET", "POST"])
    def new_task():
        user = _require_user()
        if request.method == "POST":
            errors: list[str] = []

            name = (request.form.get("name") or "").strip()
            if not name:
                errors.append("Task name is required.")
            elif len(name) > 120:
                errors.append("Task name must be 120 characters or fewer.")

            subject_id, err = _coerce_int(request.form.get("subject_id"), lo=0)
            if err:
                errors.append(f"Subject id {err}.")
            elif subject_id and not any(s.id == subject_id for s in user.subjects):
                errors.append("Unknown subject.")

            weighting, err = _coerce_float(request.form.get("weighting"), lo=0.0, hi=100.0)
            if err:
                errors.append(f"Weighting {err}.")

            hours, err = _coerce_hours_minutes(
                request.form.get("hours_required_h"),
                request.form.get("hours_required_m"),
                decimal_fallback=request.form.get("hours_required"),
                lo=0.0, hi=200.0,
            )
            if err:
                errors.append(f"Estimated time {err}.")

            due, err = _coerce_date(request.form.get("due_date"), allow_past=False)
            if err:
                errors.append(f"Due date {err}.")

            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("task_form.html", user=user, task=None), 400

            private_notes_plain = request.form.get("private_notes", "")
            a = Assignment(
                id=user.next_assignment_id(),
                subject_id=subject_id,
                name=name,
                due_date=due.isoformat(),
                weighting=weighting,
                hours_required=hours,
                est_hours=hours,
                private_notes_encrypted=_encrypt_note(private_notes_plain),
            )
            user.assignments.append(a)
            storage.save_user(user)
            return redirect(url_for("dashboard"))
        return render_template("task_form.html", user=user, task=None, private_notes_plain="")

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
                task.completion_percent = max(0.0, min(1.0, float(request.form.get("completion_percent", task.completion_percent))))
            except ValueError:
                flash("Numbers must be valid.", "error")
            hours, err = _coerce_hours_minutes(
                request.form.get("hours_required_h"),
                request.form.get("hours_required_m"),
                decimal_fallback=request.form.get("hours_required", task.hours_required),
                lo=0.0, hi=200.0,
            )
            if err:
                flash(f"Estimated time {err}.", "error")
            else:
                task.hours_required = hours
            task.completed = task.completion_percent >= 1.0
            # Update private notes (re-encrypt) if the field was submitted.
            if "private_notes" in request.form:
                task.private_notes_encrypted = _encrypt_note(
                    request.form.get("private_notes", "")
                )
            storage.save_user(user)
            return redirect(url_for("dashboard"))
        # Decrypt for editing
        plain = _decrypt_note(task.private_notes_encrypted)
        return render_template("task_form.html", user=user, task=task,
                               private_notes_plain=plain)

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

    # Constraint create/delete now lives behind the JSON /api/events routes
    # — the weekly view is the canonical editor and goes through those.

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
