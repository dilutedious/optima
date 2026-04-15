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


@app.route("/")
def splash():
    return render_template("splash.html")


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/signup")
def signup():
    return render_template("signup.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
