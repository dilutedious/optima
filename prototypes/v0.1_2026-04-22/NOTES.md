# Optima v0.1 — Prototype #1

**Snapshot date:** 2026-04-22 (Wednesday, Week 1 of build)

## What's here
- Splash screen with brand
- Login form (no real auth — accepts any input)
- Dashboard with **3 hard-coded mock tasks** so I can show the visual layout to
  testers and validate the priority-card design.

## What's deliberately missing
- No password hashing or user file
- No JSON persistence
- No scheduling engine — priorities are pre-computed
- No weekly view, no monthly view, no preferences
- No cushion gauge (planned for v0.2)
- No "Critical" priority logic — the `crit` flag on the mock task is a static
  boolean. The real urgency-override calculation comes in v0.2.

## Why ship this so early?
The plan documented in the planning folio was for an **Agile** build with a
prototype every ~2 weeks. v0.1 exists to put something in front of the client
quickly to confirm the visual direction before I sink time into the scheduling
engine. Feedback on v0.1 lives in `feedback/round_1.md`.

## How to run
```bash
pip3 install Flask
python3 app.py
```
Then open http://127.0.0.1:5050/

## Known issues (raised during v0.1 testing)
- Sidebar buttons don't go anywhere (acknowledged — wiring routes in v0.2)
- The CRITICAL tag is hard-coded
- No way to add a task
