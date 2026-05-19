# v1.1 — Calendar editor (snapshot taken 19 May 2026)

This snapshot is the working state at the end of round 4 of feedback, just
before the v1.2 rewrite that introduced designated study blocks, period
presets, sleep windows, task type/importance, and monthly stretch lines.
Kept so the development diary's "calendar editor" milestone can be replayed
end-to-end.

## What's in v1.1 (delta from v1.0)

- `Constraint` is now a recurrence rule (`anchor_date` + `recurrence` of
  none/daily/weekly/fortnightly/monthly/yearly) with `kind`, `skip_dates`,
  and per-date `overrides`. Legacy `day_of_fortnight` still loads.
- `Preferences.time_format` toggles 12-hour vs 24-hour display.
- New JSON API at `/api/events` powers a click-to-add, drag-to-move,
  multi-select editor on `/weekly`. The settings page no longer carries
  the 14-day timetable form.
- Task form takes hours + minutes (instead of decimal hours).

## Why a v1.2 was needed (the round-4 feedback)

Client follow-up after v1.1:

- "Adding subjects is way too time consuming" → in-place editor was the
  right idea but the times still needed to be re-typed per period; build
  *period presets* in Settings (Period 1 7:50–8:30, Period 2 …) that the
  event editor pulls from.
- "It keeps scheduling during sleeping hours, transit, recess, lunch" →
  the scheduler treats every awake-window gap as fair game, which is
  wrong. v1.2 introduces *designated study blocks* (kind=study_block)
  and confines auto-generated study sessions to those zones by default.
- "Sleeping hours aren't represented" → add an explicit Sleep window in
  Preferences, rendered as a translucent overlay across all days.
- Assignment / exam / project distinction: not every task is a weighted
  assessment. v1.2 splits Assignment.type into homework / exam / project
  with categorical *importance* (low / medium / high) for the non-exam
  types and reserves the % weighting field for exams.
- Monthly view: draw a coloured "stretch line" from today to each
  assignment's due date so the runway is visible at a glance.

## Known issue documented at this point

The v1.1 scheduler is greedy day-by-day, so a single assignment can
consume an entire day's free time before any other assignment gets a
session. The v1.2 rewrite round-robins across days to fix the pile-up
visible in the Tue-19 screenshot in `feedback/round4-screenshot.png`.
