<p align="center">
  <img src="optima.png" alt="Optima" width="128">
</p>

# Optima — Automated Study Flow

A Python desktop study scheduler for HSC students. Takes your timetable,
classes, assignments, and life constraints and generates an optimised plan
across a 14-day rotating cycle.

Built as part of HSC Software Engineering, 2026. Developer: Julian C.
Built for an HSC peer (client anonymised).

## Running

```bash
# 1. Install dependencies (Python 3.11+)
pip3 install -r requirements.txt

# 2. Launch — opens a native desktop window
python3 run.py

# Or open it in your default browser instead
python3 run.py --browser
```

The app stores all user data under `data/users/<username>.json`.

## Documentation

The full documentation suite lives on Google Docs. PDF exports will be
committed to this repo once finalised.

## Project layout

```
Optima/
├── run.py                     # launcher
├── app/                       # Flask app + scheduling engine
│   ├── main.py                # routes, app factory, login rate-limiting,
│   │                          # server-side validation helpers, pywebview launch
│   ├── auth.py                # SHA-256 + per-user salt + timing-safe compare
│   ├── models.py              # User, Subject, Assignment, Constraint, ...
│   ├── priority.py            # priority score with urgency override
│   ├── scheduler.py           # greedy placer using bisect.insort over sorted
│   │                          # FreeSlot intervals + cushion gauge
│   ├── storage.py             # atomic-write JSON persistence
│   ├── templates/             # Jinja2
│   └── static/                # CSS (custom-property palette), JS, images
├── data/                      # user JSON files (created on first run)
├── prototypes/                # v0.1, v0.2, v0.3, v1.1 snapshots
└── feedback/                  # survey, interview prompts, round questionnaires
```
