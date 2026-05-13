# Optima v0.3 — Prototype #3

**Snapshot date:** 2026-05-13 (Wednesday, end of Week 4)

## What's new since v0.2
- **Monthly view** with assignment due dates spotted on the calendar grid
- **Preferences page** with theme switching (light/dark) + auto-save + notifications
- **Per-user salt** generated at signup (replaces the global salt from v0.2 — flagged by tester #2)
- **Atomic JSON writes** via temp-file swap (fixes the corruption issue tester #3 hit on v0.2)
- **Subject and constraint CRUD** so users can model their 14-day rotation properly
- **Conflict resolver** — the scheduler now respects existing study blocks and class periods, fixing the v0.2 overlap bug
- **Edit/delete task** flow
- **Progress slider** on each task card with inline AJAX save

## What's still missing for v1.0
- **Accessibility extras** — high contrast mode, focus highlights, zoom (planned)
- **Splash auto-redirect** so the brand screen flows into the login automatically
- **Dashboard XP counter** wired to the gamification spec (currently increments silently)
- A few smaller polish items raised in feedback round 3

## How to run
```bash
pip3 install -r requirements.txt
python3 run.py            # native window
python3 run.py --browser  # browser fallback
```
