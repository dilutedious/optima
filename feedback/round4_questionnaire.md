# Optima — Round 4 questionnaire

Issued alongside prototype 1.1 on Tuesday 19 May 2026 to the client
(C). Round 4 is a focused post-v1.0 follow-up after a few days of
real use; only the client is being re-engaged this round because the v1.1
delta is small (one feature area).

## What's new since v1.0

- **Interactive weekly editor** — click an empty slot to add an event,
  click an existing event to edit, drag to move (5-min snap),
  shift / cmd-click to multi-select, Delete to remove. Repeating events
  prompt "this one vs all" on edit / move / delete.
- **Constraint = recurrence rule** under the hood (`anchor_date` +
  recurrence one of none / daily / weekly / fortnightly / monthly /
  yearly), with `kind` (subject / extracurricular / appointment / study
  / other), `skip_dates`, and per-date `overrides`.
- **12-hour / 24-hour time format** preference.
- **Hours + minutes** task input (replaces decimal hours).
- Class-entry form removed from Settings — Weekly view is the canonical
  editor now.

## Questions

1. After three days of real use: faster or slower to set up a week's
   classes than v1.0's form?
2. Anything in the new editor that surprised you, in a bad way?
3. Schedule output — does it still pick reasonable times, or has the
   change made it worse anywhere?
4. Sleep / transit / lunch — does the app know about them yet? (Expected
   answer: no. Asking so we capture the gap.)
5. Free notes.

## Deadline

Reply by Wed 20 May. This is a short loop — anything that turns up here
goes straight into a v1.2 sprint over the weekend.
