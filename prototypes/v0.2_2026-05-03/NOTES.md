# Optima v0.2 — Prototype #2

**Snapshot date:** 2026-05-03 (Sunday, end of Week 3)

## What's new since v0.1
- **Real authentication** with SHA-256 password hashing (no per-user salt yet)
- **JSON persistence** — each account saves to `data/<username>.json`
- **Signup flow** that seeds default subjects
- **Priority calculator** with the `(weight * 10) / max(days, 1)` formula and
  the `<=3 days → critical` urgency override from the planning spec
- **Greedy scheduling engine** that drops 30–120 min study blocks into the
  morning of each day, sorted by priority
- **Weekly view** with a 7-day grid
- **Cushion gauge** (numeric ratio only — donut SVG lands in v0.3)
- **KPI strip** on the dashboard

## Still missing (planned for v0.3)
- Monthly view
- Preferences page (theme, contrast, focus highlights, zoom)
- Splash auto-redirect / animation
- Per-user salt — global salt is a security smell that one tester flagged
- Atomic JSON writes (raised after one tester reported a truncated save when
  they force-quit the app)
- Conflict resolver for fixed events / classes
- Subject and constraint CRUD

## Known bugs
- Two same-day study blocks can overlap on the weekly grid
  (the scheduler doesn't currently advance the cursor enough when two tasks
  share a day)
- Sidebar icons for Monthly + Settings are dead links (intentional, will wire
  up in v0.3)
- Cushion ratio assumes 8 fixed hours/day — should derive from constraints
  once they're added in v0.3

## How to run
```bash
pip3 install Flask
python3 app.py
```
Then open http://127.0.0.1:5050/
