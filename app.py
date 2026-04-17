"""Optima — Day 1 scaffold (Tue 14 Apr 2026).

Single-file Flask app for now. The package split comes when there's enough
code to justify it; right now there's a splash and that's it.

Run:
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python3 app.py

Then open http://127.0.0.1:5050/
"""

from flask import Flask, render_template

app = Flask(__name__)
app.secret_key = "v0.1-dev-only"

# Hard-coded for the v0.1 walkthrough so testers can react to a layout
# with real-looking values. Will be replaced by real data in v0.2.
MOCK_TASKS = [
    {"name": "Software Eng Folio Submission", "subject": "SE",   "due": "2026-05-29",
     "weighting": 30, "hours": 12, "score": 9999, "colour": "#7B68EE", "crit": True},
    {"name": "Maths Assignment 2",            "subject": "Maths","due": "2026-05-02",
     "weighting": 20, "hours": 4,  "score": 50,   "colour": "#34c759", "crit": False},
    {"name": "Physics Practical Report",      "subject": "Phys", "due": "2026-05-10",
     "weighting": 15, "hours": 3,  "score": 21,   "colour": "#ff9f0a", "crit": False},
]


@app.route("/")
def splash():
    return render_template("splash.html")


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/signup")
def signup():
    return render_template("signup.html")


@app.route("/dashboard")
def dashboard():
    # No real auth yet — anyone hitting this URL sees the mock dashboard.
    return render_template("dashboard.html", user="tester", tasks=MOCK_TASKS)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
