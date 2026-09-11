#!/usr/bin/env bash
# Starts all four ReadCoach services with one command instead of four
# separate terminals: the mastery backend (:8000), the frontend (:3000),
# the voice bot (:7860), and the eval service (:8001). Ctrl+C stops all
# four together.
#
# The eval service only serves whatever backend/eval/reports/eval_report.json
# already has on disk (run `python3 run_benchmark.py` in backend/eval/ to
# generate or refresh it - see README.md's Metrics section) - starting this
# alongside the other three is what makes the engineering dashboard's own
# eval section actually load instead of 503ing, without needing a fifth
# manual step.
#
# This does not merge them into one process - they're genuinely different
# kinds of processes (a web server, two REST APIs, a real-time voice/WebRTC
# bot) and that's the right architecture, not a shortcut worth undoing.
# This script only removes the friction of juggling four terminals.
#
# An earlier version of this script piped each service's output through
# `sed` to prefix every line with its name. Testing that directly (not just
# reading it and assuming it would work) showed it silently buffers output
# instead of showing it in real time - a service's own startup errors could
# sit invisible for a long time, or vanish entirely if the process gets
# killed before the buffer flushes. That defeats the point of a dev script,
# so this version lets each service write straight to the terminal
# unprefixed instead. Each one already identifies itself clearly in its own
# output (uvicorn names itself, Next.js announces itself, the bot prints
# "Bot ready!"), so this is a real tradeoff (interleaved, unlabeled output)
# made on purpose, not an oversight.

set -e
cd "$(dirname "$0")"

PIDS=()

cleanup() {
  echo ""
  echo "Stopping all services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# --workers 4: this service is genuinely stateless per request (db.py opens
# a fresh connection per call, closes it in a finally, never shares one
# across requests) and the module-level caches it does have (mastery.py's
# taxonomy cache, passage_selection.py's passage cache) are read-only static
# data, one independent copy per worker - safe to run as several processes
# rather than one, against this project's real backend (Postgres/Supabase).
# The one real caveat, worth knowing rather than hitting by surprise: the
# sqlite fallback path (no DATABASE_URL set) has no WAL mode configured, so
# several worker *processes* writing concurrently there can hit real
# "database is locked" errors under load - Postgres has no such limit.
echo "Starting mastery backend on :8000..."
(cd backend/mastery && source .venv/bin/activate && uvicorn main:app --port 8000 --workers 4) &
PIDS+=("$!")

echo "Starting frontend on :3000..."
(cd frontend && npm run dev) &
PIDS+=("$!")

echo "Starting voice bot on :7860..."
(cd backend/voice && source .venv/bin/activate && python bot.py -t webrtc -v) &
PIDS+=("$!")

echo "Starting eval service on :8001..."
(cd backend/eval && source .venv/bin/activate && uvicorn server:app --port 8001) &
PIDS+=("$!")

echo ""
echo "All four starting up. Open http://localhost:3000/read once they're ready."
echo "Press Ctrl+C to stop all four."
echo ""

wait
