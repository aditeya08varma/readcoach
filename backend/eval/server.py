"""GET /admin/eval_report - owned by eval-engineer per contracts/api_contract.md:

    Returns the latest scored benchmark run ... Response shape is up to
    eval-engineer to define, but must include at minimum diagnostic_accuracy,
    question_groundedness, and latency_percentiles so
    /admin/engineering_dashboard can summarize it.

This serves whatever `run_benchmark.py` last wrote to reports/eval_report.json
- it does not re-run the benchmark on every request (that would make real,
billed Claude API calls on every dashboard load). Run `python3
run_benchmark.py` to refresh the report; restart or re-request afterward to
pick it up (the file is re-read on every request, not cached at startup, so a
fresh run_benchmark.py pass is visible without restarting this server).

Run: uvicorn server:app --port 8001 (a separate port from the mastery
service's :8000, since this is a standalone service exactly like
backend/mastery/main.py is - contracts/api_contract.md doesn't say these
must share a process, and eval-engineer's lane is backend/eval/ only).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

REPORT_PATH = Path(__file__).resolve().parent / "reports" / "eval_report.json"

app = FastAPI(title="ReadCoach Eval Service")

# Same gap, same fix as backend/mastery/main.py (see docs/BUILD_LOG.md): no
# CORS config meant any browser preflight would get a flat 405. This service
# isn't called directly by the browser today (the frontend only reaches it
# indirectly, via GET /admin/engineering_dashboard on the mastery service),
# but it's a standalone FastAPI app just like mastery's, so it gets the same
# permissive local-dev CORS rather than silently carrying the same landmine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/admin/eval_report")
def get_eval_report():
    if not REPORT_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "No eval report yet - run `python3 run_benchmark.py` in "
                "backend/eval/ first."
            ),
        )
    with open(REPORT_PATH, encoding="utf-8") as f:
        return json.load(f)
