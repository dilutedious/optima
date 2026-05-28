#!/usr/bin/env bash
# Smoke test — a short shell session that walks one real user journey end to
# end: create an account, add a subject, add a constraint (calendar event),
# add three assignments, generate a schedule, switch themes, toggle an
# accessibility setting, then delete everything. Re-run before every prototype
# release as a "the happy path still works over real HTTP" check.
#
# It boots its own Flask server on a spare port pointed at a throwaway data
# dir, so it never touches your real data/ folder, and tears the server down
# on exit. Each step asserts the HTTP status code; any mismatch fails the run.
#
#   bash tools/smoke_test.sh      # exit 0 = the whole journey worked
set -euo pipefail

PORT="${OPTIMA_SMOKE_PORT:-5077}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$(mktemp -d)"
JAR="$DATA/cookies.txt"
BASE="http://127.0.0.1:${PORT}"

cd "$ROOT"

# --- boot a server on an isolated data dir --------------------------------
python3 -c "
from pathlib import Path
from app.main import create_app
app = create_app(Path('$DATA'))
app.run(host='127.0.0.1', port=$PORT, debug=False, use_reloader=False)
" >"$DATA/server.log" 2>&1 &
SERVER_PID=$!
disown "$SERVER_PID" 2>/dev/null || true

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$DATA"
}
trap cleanup EXIT

# Wait for the server to answer before we start poking it.
for _ in $(seq 1 50); do
  if curl -sf -o /dev/null "$BASE/"; then break; fi
  sleep 0.1
done

FAILURES=0
# check <expected-code> <label> <curl-args...>
check() {
  local expected="$1"; shift
  local label="$1"; shift
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -c "$JAR" "$@")"
  if [ "$code" = "$expected" ]; then
    printf '  %s  %s\n' "$code" "$label"
  else
    printf '  %s  %s   <-- FAIL (wanted %s)\n' "$code" "$label" "$expected"
    FAILURES=$((FAILURES + 1))
  fi
}

echo "Smoke journey against $BASE (throwaway data dir)"
echo

# 1. Create an account (signup logs us in and seeds 5 default subjects 1-5).
check 302 "create account"        -X POST "$BASE/signup" \
  --data "username=smoke&password=test1234&confirm=test1234"

# 2. Add a subject (becomes id 6).
check 302 "add subject"           -X POST "$BASE/subjects/new" \
  --data "name=Smoke Subject&colour=%237B68EE"

# 3. Add a constraint / calendar event (id 1; 14:00-15:00 clears sleep window).
check 200 "add constraint"        -X POST "$BASE/api/events" \
  -H 'Content-Type: application/json' \
  --data '{"name":"Maths class","subject_id":1,"start_time":14.0,"end_time":15.0,"anchor_date":"2026-12-01","recurrence":"weekly","kind":"subject"}'

# 4. Add three assignments (ids 1, 2, 3).
check 302 "add assignment 1"      -X POST "$BASE/tasks/new" \
  --data "name=Essay&subject_id=1&type=homework&importance=high&hours_required=3&due_date=2026-12-01&due_time=09:00"
check 302 "add assignment 2"      -X POST "$BASE/tasks/new" \
  --data "name=Lab report&subject_id=1&type=homework&importance=medium&hours_required=2&due_date=2026-12-03&due_time=09:00"
check 302 "add assignment 3"      -X POST "$BASE/tasks/new" \
  --data "name=Exam revision&subject_id=1&type=exam&importance=high&weighting=30&hours_required=5&due_date=2026-12-05&due_time=09:00"

# 5. Generate a schedule (the dashboard regenerates it on load).
check 200 "generate schedule"     "$BASE/dashboard"

# 6. Switch themes (light -> dark) via preferences.
check 302 "switch theme to dark"  -X POST "$BASE/preferences" \
  --data "theme=dark&time_format=24h&zoom=100"

# 7. Toggle an accessibility setting (high contrast on).
check 302 "toggle high contrast"  -X POST "$BASE/preferences" \
  --data "theme=dark&high_contrast=on&time_format=24h&zoom=100"

# 8. Delete everything we made.
check 200 "delete constraint"     -X DELETE "$BASE/api/events/1?scope=all"
check 302 "delete assignment 1"   -X POST "$BASE/tasks/1" --data "action=delete"
check 302 "delete assignment 2"   -X POST "$BASE/tasks/2" --data "action=delete"
check 302 "delete assignment 3"   -X POST "$BASE/tasks/3" --data "action=delete"
check 302 "delete subject"        -X POST "$BASE/subjects/6/delete"

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "PASS — full journey completed cleanly"
  exit 0
else
  echo "FAIL — $FAILURES step(s) returned an unexpected status"
  exit 1
fi
