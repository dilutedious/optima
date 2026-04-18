"""
Optima — Prototype v0.1
Date: 2026-04-22
Build status: Skeleton only.

Whats here:
- Splash + login form (no real auth — any creds get you in)
- Dashboard with three hard-coded mock tasks so I can show the layout to
  testers before plumbing the real engine.
- No JSON yet. No scheduler. No weekly/monthly views. Settings is just a
  placeholder.

Run:
    python3 app.py
Then open http://127.0.0.1:5050/
"""

from flask import Flask, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = "v0.1-dev-only"

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
