# Optima — Round 2 questionnaire

Issued alongside prototype 0.2 on Sunday 3 May 2026 to evaluators E1, E2, E3
and client (C).

## What's new since 0.1

- **Real signup / login** with SHA-256 password hashing (single shared salt
  for now — per-user salt is coming in v0.3).
- **JSON persistence** — each account saves to `data/<username>.json`.
- **Signup flow** seeds five default subjects.
- **Priority calculator** using the planning-document formula
  `(weighting * 10) / max(days_remaining, 1)`, with `<=3 days → critical`
  override.
- **Greedy scheduling engine** that drops 30–120 min study blocks into the
  morning of each day, sorted by priority.
- **Weekly view** with a 7-day grid, solid class blocks (none yet — see
  known bugs below) and dashed study blocks.
- **Cushion gauge** (numeric ratio only — donut SVG lands in v0.3).
- **KPI strip** on the dashboard.

## Known limitations (please don't waste time reporting these)

- Two same-day study blocks can overlap on the weekly grid. I know.
- Settings and Monthly icons in the sidebar are dead links.
- Cushion ratio assumes a flat 8 free hours per day — will fix in v0.3 once
  the constraint CRUD is in.
- Can't add your own subjects or class periods yet.

## Questions

1. Did anything *regress* from v0.1? Did anything you reported in round 1
   get fixed to your satisfaction?
2. Does the priority order on the dashboard agree with the order you would
   have chosen yourself? If not, give me one example.
3. The weekly view — do the dashed study blocks land in slots that make
   sense?
4. Did you lose any data, or see anything that looked corrupted or wrong?
5. Security — nothing to test directly, but anything you noticed that
   worried you?
6. Free notes.

## Deadline

By Tuesday 5 May, please. Week 4 is the hardening sprint and I want to know
what to prioritise before I dive in.
