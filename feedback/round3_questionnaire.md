# Optima — Round 3 questionnaire

Issued alongside prototype 0.3 on Wednesday 13 May 2026 to evaluators E1,
E2, E3 and client (C).

## What's new since 0.2

- **Monthly view** — full calendar grid with assignment due-date dots.
- **Preferences page** with theme switching (light / dark), notifications,
  auto-save toggles.
- **Per-user salt** generated at signup — replaces the global salt from
  v0.2 (flagged by E3 in round 2).
- **Atomic JSON writes** via temp-file swap — fixes the corruption issue
  E3 hit in round 2.
- **Subject and constraint CRUD** so you can model your 14-day rotation
  properly.
- **Conflict resolver** — the scheduler now respects existing study blocks
  and class periods, fixing the Wednesday overlap bug.
- **Edit / delete task** flow.
- **Progress slider** on each task card with inline AJAX save.
- **Cushion donut** SVG replaces the numeric KPI.

## Still missing (planned for v1.0, not v0.3)

- Accessibility extras — high contrast mode, focus highlights, zoom.
- Splash auto-redirect so the brand screen flows into the login
  automatically.
- Dashboard XP counter wired to anything meaningful (currently increments
  silently).
- Final polish pass.

## Questions

1. Does it feel **production-ready**? If not, what's the *one* thing
   stopping you saying yes?
2. Anything you reported in rounds 1 or 2 that is still not fixed?
3. Use it for one real day's planning. What broke?
4. Accessibility — anything painful (colour, type size, contrast,
   keyboard nav)?
5. Free notes.

## Deadline

By Saturday 16 May. Submission is Monday 18 May so I want enough time to
react.
