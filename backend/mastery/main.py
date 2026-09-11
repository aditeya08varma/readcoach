"""
ReadCoach mastery service.

Implements, per contracts/api_contract.md exactly:
  POST /students
  GET  /students/{id}/next_passage
  GET  /students/{id}/mastery
  POST /sessions

Storage is real Postgres (Supabase) when DATABASE_URL is set, local SQLite
otherwise -- see db.py's module docstring for exactly how that switch works.
Schema is contracts/db_schema.sql, unchanged since either backend was added.

POST /sessions was originally missing from api_contract.md; this service's first
version built it as a stand-in at /internal/sessions and flagged the gap. The
orchestrator has since formalized it in api_contract.md as POST /sessions (same
request/response shape), and this file was updated to match that path.
"""
import json
import logging
import math
import os
import sqlite3
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import db
import mastery
import passage_selection
from models import (
    CreateStudentRequest,
    EngineeringDashboardResponse,
    EvalSummary,
    IngestSessionRequest,
    IngestSessionResponse,
    LatencyStages,
    MapCategory,
    MapPassageRef,
    MapSkillNode,
    MasterySkillResponse,
    NextPassageResponse,
    SessionHistoryItem,
    SkillUpdateResponse,
    StoryMapResponse,
    StudentResponse,
)
from recap_client import generate_session_recap

EVAL_SERVICE_URL = os.environ.get("EVAL_SERVICE_URL", "http://localhost:8001")

# A stage's real P50/P95 is only trusted once at least this many real
# sessions have actually reported it - one or two real numbers would make
# a "P95" that looks precise but is really just whichever session happened
# to run. Below this, that stage falls back to the eval service's own
# proxy number (see engineering_dashboard below), same as every stage
# already did before real per-session latency existed at all.
_MIN_REAL_LATENCY_SAMPLES = 3


def _percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (numpy's default convention) - same
    formula as backend/eval/report.percentile, kept as its own small copy
    here rather than a cross-service import: it's under 15 lines of pure
    math with zero dependencies, not shared logic worth the same kind of
    sys.path coupling this project already uses for larger, actively
    shared modules (classify_skill_for_word, TutorSession itself)."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return round(s[0], 1)
    rank = (pct / 100.0) * (len(s) - 1)
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return round(s[lo], 1)
    frac = rank - lo
    return round(s[lo] + (s[hi] - s[lo]) * frac, 1)


def _real_latency_percentiles(cur) -> dict[str, dict[str, float | None]]:
    """Real per-stage P50/P95 across every real session that has ever
    reported `pipeline_latency_ms` (see backend/voice/latency_observer.py -
    before that existed, this column was always null for every session, so
    this always returned nothing at all). A stage with fewer than
    `_MIN_REAL_LATENCY_SAMPLES` real reports comes back as None for both
    percentiles, left for the caller to fall back to the eval proxy."""
    cur.execute("select pipeline_latency_ms from sessions where pipeline_latency_ms is not null")
    samples: dict[str, list[float]] = {"stt_ms": [], "llm_ms": [], "tts_ms": []}
    for row in cur.fetchall():
        raw = row["pipeline_latency_ms"]
        data = raw if isinstance(raw, dict) else json.loads(raw)
        for stage, values in samples.items():
            value = data.get(stage)
            if value is not None:
                values.append(value)
    p50, p95 = {}, {}
    for stage, values in samples.items():
        enough = len(values) >= _MIN_REAL_LATENCY_SAMPLES
        p50[stage] = _percentile(values, 50) if enough else None
        p95[stage] = _percentile(values, 95) if enough else None
    return {"p50_ms": p50, "p95_ms": p95}

logger = logging.getLogger("mastery")

app = FastAPI(title="ReadCoach Mastery Service")

# Real bug found from a real terminal log, not assumed: this service had no
# CORS configuration at all. frontend/lib/api.ts sets Content-Type:
# application/json on every request, including plain GETs, which makes the
# browser send a CORS preflight (OPTIONS) before the real request - and with
# no middleware to answer it, every single call from the frontend to this
# service has been failing at the preflight stage, silently falling back to
# mock data every time, for any student id at all, not only the placeholder
# one flagged earlier. Permissive origins here match the same choice already
# made for the voice bot's own server (backend/voice/bot.py's Pipecat runner
# also allows "*") - fine for local dev/a hackathon demo, would need
# tightening for a real production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_student_or_404(cur: sqlite3.Cursor, student_id: str) -> sqlite3.Row:
    # Real bug found live (see docs/BUILD_LOG.md): `id` is a real Postgres
    # `uuid` column. A non-UUID string like the frontend's old hardcoded
    # placeholder "demo-student-1" made psycopg2 raise
    # InvalidTextRepresentation instead of just finding no row, which
    # produced an unhandled 500 with no CORS headers on it at all (the
    # exception happens too deep for CORSMiddleware to attach them to the
    # error response) - so the browser reported it as a plain network
    # failure ("Failed to fetch") and silently fell back to mock data,
    # exactly masking this the same way the missing CORS config did.
    # Validating the shape first turns that crash into an ordinary, correctly
    # CORS-headered 404, which SQLite (untyped columns, local dev) already
    # produced for the same input without needing this check.
    try:
        uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="student not found")
    cur.execute("select * from students where id = ?", (student_id,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="student not found")
    return row


@app.post("/students", response_model=StudentResponse)
def create_student(req: CreateStudentRequest):
    student_id = str(uuid.uuid4())
    with db.get_cursor() as cur:
        cur.execute(
            "insert into students (id, display_name, grade, created_at) values (?, ?, ?, ?)",
            (student_id, req.display_name, req.grade, _now()),
        )
    return StudentResponse(id=student_id, display_name=req.display_name, grade=req.grade)


# A real gap found from a real screen recording (see docs/BUILD_LOG.md): the
# frontend has always pointed its dashboards at a hardcoded placeholder
# student id, while backend/voice/mastery_client.py independently creates and
# persists its OWN separate demo student in a local file - two different
# "demo students" that never once pointed at the same row, so a parent
# dashboard could never show a real voice session's results no matter how
# many were run. This fixed, well-known id is the single shared demo student
# both sides now ask for, get-or-create, idempotent - so whichever side asks
# first creates it and every side afterward gets that exact same row.
DEMO_STUDENT_ID = "00000000-0000-0000-0000-000000000001"


@app.get("/students/demo", response_model=StudentResponse)
def get_or_create_demo_student():
    with db.get_cursor() as cur:
        cur.execute("select * from students where id = ?", (DEMO_STUDENT_ID,))
        row = cur.fetchone()
        if row is not None:
            return StudentResponse(id=row["id"], display_name=row["display_name"], grade=row["grade"])
        display_name, grade = "Jordan", 2
        cur.execute(
            "insert into students (id, display_name, grade, created_at) values (?, ?, ?, ?)",
            (DEMO_STUDENT_ID, display_name, grade, _now()),
        )
    return StudentResponse(id=DEMO_STUDENT_ID, display_name=display_name, grade=grade)


@app.get("/students/{student_id}/next_passage", response_model=NextPassageResponse)
def next_passage(student_id: str):
    with db.get_cursor() as cur:
        student = _get_student_or_404(cur, student_id)
        passage, selection_reason = passage_selection.pick_next_passage(cur, student_id, student["grade"])
    challenge_word_index = passage_selection.pick_challenge_word_index(passage)
    return NextPassageResponse(**passage, selection_reason=selection_reason, challenge_word_index=challenge_word_index)


@app.get("/students/{student_id}/passages/{passage_id}", response_model=NextPassageResponse)
def get_passage(student_id: str, passage_id: str):
    """A real person explicitly picked this passage - the story map's
    tap-a-node flow, or the voice bot honoring an explicit choice passed
    through the live connection (see contracts/api_contract.md). Same
    response shape as next_passage, mode="chosen" instead of an
    auto-selection rule."""
    with db.get_cursor() as cur:
        _get_student_or_404(cur, student_id)
        result = passage_selection.get_chosen_passage(cur, student_id, passage_id)
        if result is None:
            raise HTTPException(status_code=404, detail="passage not found")
        passage, selection_reason = result
    challenge_word_index = passage_selection.pick_challenge_word_index(passage)
    return NextPassageResponse(**passage, selection_reason=selection_reason, challenge_word_index=challenge_word_index)


@app.get("/students/{student_id}/mastery", response_model=list[MasterySkillResponse])
def get_mastery(student_id: str):
    with db.get_cursor() as cur:
        _get_student_or_404(cur, student_id)
        cur.execute(
            """
            select s.id as skill_id, s.label, s.category,
                   coalesce(m.weight, 0.0) as weight
            from skills s
            left join student_skill_mastery m
                on m.skill_id = s.id and m.student_id = ?
            order by s.id
            """,
            (student_id,),
        )
        rows = cur.fetchall()
    return [
        MasterySkillResponse(skill_id=r["skill_id"], label=r["label"], category=r["category"], weight=r["weight"])
        for r in rows
    ]


_MAP_CATEGORY_ORDER = ("phonics", "vocabulary", "comprehension")


@app.get("/students/{student_id}/map", response_model=StoryMapResponse)
def get_story_map(student_id: str):
    """Story map, see docs/FEATURE_IDEAS.md's gameplay ideation and
    contracts/api_contract.md. Pure aggregation of data that already exists
    elsewhere (priority order, real mastery weights, the passage library,
    real session history) - no new data model, no new AI call, visualization
    only for now (see that scoping discussion for why a "choosable" map, one
    that actually starts a session with a tapped passage, is a separate,
    larger piece of work: POST /sessions/{id}/voice_token, the endpoint that
    would need to carry that choice through to the voice bot, was documented
    from the start but never actually built)."""
    with db.get_cursor() as cur:
        student = _get_student_or_404(cur, student_id)
        priority_order = mastery.topological_skill_order(cur)
        cur.execute("select id, label, category from skills")
        skill_rows = {r["id"]: r for r in cur.fetchall()}
        # Real bug found from a real screen recording (see docs/BUILD_LOG.md):
        # this used to call mastery.get_weight once per skill in a Python
        # loop, one real round trip to the remote Supabase database per
        # skill - 18 sequential network round trips for this one request,
        # around 1.9s end to end, easily enough to trip the frontend's own
        # fetch timeout and silently fall back to mock data. mastery.get_weights
        # fetches every skill's weight in one round trip instead of 18 (the
        # same fix, now shared - passage_selection.pick_next_passage had the
        # identical bug and now uses the same helper).
        weight_rows = mastery.get_weights(cur, student_id)
        weights = {sid: weight_rows.get(sid, 0.0) for sid in priority_order}
        cur.execute("select distinct passage_id from sessions where student_id = ?", (student_id,))
        attempted_ids = {r["passage_id"] for r in cur.fetchall()}

    # Real bug found from a real screenshot: this used to only include
    # passages at the student's own grade, "to avoid showing content well
    # above or below their level." In practice the 18-skill taxonomy's
    # passage library has exactly one primary passage per skill, spread
    # across grades 1 to 3 - so for any single-grade student, two thirds of
    # the map's skill nodes showed "No story yet" even though a real,
    # already-written story for that exact skill existed one grade away.
    # The map is a full journey overview, not a today's-reading picker (that
    # job is pick_next_passage/_passages_for_skill in passage_selection.py -
    # it had the exact same grade-restriction bug, independently found and
    # fixed the same way once it started always recommending an
    # already-completed story instead of the student's genuinely weakest
    # skill; see that file's own comment) - so every skill's one real
    # passage is included here regardless of grade, on the reasoning
    # that reviewing an earlier grade's story or previewing a later one is
    # a normal, honest part of a reading journey, not a mismatch to hide.
    passages_by_skill: dict[str, list[dict]] = {}
    for p in passage_selection.get_passages():
        skill_id = p.get("primary_skill")
        if skill_id:
            passages_by_skill.setdefault(skill_id, []).append(p)

    nodes_by_category: dict[str, list[MapSkillNode]] = {c: [] for c in _MAP_CATEGORY_ORDER}
    for skill_id in priority_order:
        row = skill_rows.get(skill_id)
        if row is None:
            continue
        node_passages = [
            MapPassageRef(id=p["id"], title=p["title"], grade=p["grade"], attempted=p["id"] in attempted_ids)
            for p in sorted(passages_by_skill.get(skill_id, []), key=lambda p: p["id"])
        ]
        node = MapSkillNode(
            skill_id=skill_id,
            label=row["label"],
            category=row["category"],
            weight=weights[skill_id],
            passages=node_passages,
        )
        nodes_by_category.setdefault(row["category"], []).append(node)

    return StoryMapResponse(
        categories=[
            MapCategory(category=c, skills=nodes_by_category[c])
            for c in _MAP_CATEGORY_ORDER
            if nodes_by_category.get(c)
        ]
    )


def _find_passage_title(passage_id: str) -> str:
    for p in passage_selection.get_passages():
        if p["id"] == passage_id:
            return p.get("title", passage_id)
    return passage_id


def _find_passage_skill_ids(passage_id: str) -> set[str]:
    for p in passage_selection.get_passages():
        if p["id"] == passage_id:
            return set(p.get("skills") or [])
    return set()


def _skill_labels(cur, skill_ids: set[str]) -> list[str]:
    if not skill_ids:
        return []
    placeholders = ", ".join("?" for _ in skill_ids)
    cur.execute(f"select label from skills where id in ({placeholders})", tuple(skill_ids))
    return [row["label"] for row in cur.fetchall()]


@app.get("/students/{student_id}/sessions", response_model=list[SessionHistoryItem])
def list_sessions(student_id: str):
    """Was documented in contracts/api_contract.md but never actually
    implemented during the first integration pass - the parent dashboard
    ran on mocked data for this endpoint until now. Implemented for real
    alongside the auto-generated recap feature, since that's the field
    this endpoint needed to start actually returning."""
    with db.get_cursor() as cur:
        _get_student_or_404(cur, student_id)
        cur.execute(
            """
            select id, passage_id, started_at, wcpm, accuracy, self_corrections, session_recap
            from sessions
            where student_id = ?
            order by started_at asc
            """,
            (student_id,),
        )
        rows = cur.fetchall()
    return [
        SessionHistoryItem(
            id=r["id"],
            passage_id=r["passage_id"],
            # started_at is a plain ISO string on SQLite but a native Postgres
            # timestamptz (psycopg2 hands back a real datetime) - normalize
            # both to a string, same reasoning as passage_selection._iso.
            started_at=r["started_at"].isoformat() if hasattr(r["started_at"], "isoformat") else r["started_at"],
            wcpm=r["wcpm"],
            accuracy=r["accuracy"],
            self_corrections=r["self_corrections"],
            session_recap=r["session_recap"],
        )
        for r in rows
    ]


@app.post("/sessions", response_model=IngestSessionResponse)
async def ingest_session(req: IngestSessionRequest):
    """Formalized in contracts/api_contract.md as POST /sessions (same shape as
    originally built here, just moved off the /internal prefix once the
    orchestrator confirmed this as the real integration point)."""
    session_id = str(uuid.uuid4())
    miscues = [m.model_dump() for m in req.miscues]
    comprehension = [c.model_dump() for c in req.comprehension]

    skill_ids = {m["skill_id"] for m in miscues if m.get("skill_id")}
    skill_ids |= {c["skill_id"] for c in comprehension if c.get("skill_id")}
    comprehension_correct = sum(1 for c in comprehension if c.get("correct"))

    with db.get_cursor() as cur:
        _get_student_or_404(cur, req.student_id)
        skill_labels = _skill_labels(cur, skill_ids)

    # Best-effort, outside any open db connection - this is an external API
    # call and shouldn't hold a connection idle while it's in flight, and a
    # failure here must never break session ingestion / the mastery update
    # that depends on it (see docs/FEATURE_IDEAS.md's recap idea: nice to
    # have, not load-bearing).
    session_recap = None
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            session_recap = await generate_session_recap(
                api_key=anthropic_key,
                passage_title=_find_passage_title(req.passage_id),
                wcpm=req.wcpm,
                accuracy=req.accuracy,
                self_corrections=req.self_corrections,
                skill_labels_practiced=skill_labels,
                comprehension_correct=comprehension_correct,
                comprehension_total=len(comprehension),
                hints_delayed_count=req.hints_delayed_count,
                hints_delayed_self_corrected_count=req.hints_delayed_self_corrected_count,
            )
        except Exception as e:
            logger.warning(f"session recap generation failed (non-fatal): {e}")
    else:
        logger.warning("ANTHROPIC_API_KEY not set - skipping session recap generation")

    with db.get_cursor() as cur:
        cur.execute(
            """
            insert into sessions
                (id, student_id, passage_id, started_at, ended_at, wcpm, accuracy,
                 self_corrections, miscues, comprehension, pipeline_latency_ms, session_recap,
                 hints_delayed_count, hints_delayed_self_corrected_count)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                req.student_id,
                req.passage_id,
                _now(),
                _now(),
                req.wcpm,
                req.accuracy,
                req.self_corrections,
                json.dumps(miscues),
                json.dumps(comprehension),
                json.dumps(req.pipeline_latency_ms) if req.pipeline_latency_ms else None,
                session_recap,
                req.hints_delayed_count,
                req.hints_delayed_self_corrected_count,
            ),
        )
        passage_skill_ids = _find_passage_skill_ids(req.passage_id)
        updates = mastery.apply_session_to_mastery(cur, req.student_id, miscues, comprehension, passage_skill_ids)

    return IngestSessionResponse(
        session_id=session_id,
        updates=[
            SkillUpdateResponse(
                skill_id=u.skill_id,
                session_score=u.session_score,
                old_weight=u.old_weight,
                new_weight=u.new_weight,
                direct=u.direct,
            )
            for u in updates
        ],
    )


@app.get("/admin/engineering_dashboard", response_model=EngineeringDashboardResponse)
async def engineering_dashboard():
    """Per contracts/api_contract.md. A real gap found while auditing this
    service for the same class of bug as the CORS fix (see docs/BUILD_LOG.md):
    this endpoint was never actually built, so the engineering screen has
    only ever shown mock data, CORS aside.

    The contract calls for aggregating pipeline latency "across recent
    sessions" from this service's own database. Real gap, found and fixed
    since (see docs/BUILD_LOG.md): no code anywhere in the voice pipeline
    used to record `pipeline_latency_ms` on a real session at all (only
    llm_ms, and only offline in the eval harness's own benchmark) - that
    column existed but had never once been populated, so this endpoint used
    to only ever proxy the eval service's own report for every stage.
    backend/voice/latency_observer.py now captures real stt/tts (from
    Pipecat's own TTFB metrics) and llm (wrapping the real Claude client)
    timing on every real session, so this now aggregates real P50/P95 per
    stage from this service's own database first, falling back to the eval
    service's proxy only for a stage that doesn't yet have enough real
    sessions reporting it (see `_real_latency_percentiles` / this file's own
    `_MIN_REAL_LATENCY_SAMPLES`) - an honest, gradual handoff from proxy to
    real numbers as real sessions accumulate, per stage, rather than an
    all-or-nothing switch.

    The eval report is still the only source for the eval section below
    (diagnostic accuracy / question groundedness), which has nothing to do
    with latency at all.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{EVAL_SERVICE_URL}/admin/eval_report")
            resp.raise_for_status()
            report = resp.json()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"eval service unreachable or has no report yet: {e}",
        )

    with db.get_cursor() as cur:
        real_latency = _real_latency_percentiles(cur)

    eval_latency = report.get("latency_percentiles", {})
    eval_p50 = eval_latency.get("p50_ms") or {}
    eval_p95 = eval_latency.get("p95_ms") or {}

    def merged(stage_key: str, real: dict, proxy: dict) -> float | None:
        value = real.get(stage_key)
        return value if value is not None else proxy.get(stage_key)

    p50_stages = {
        stage: merged(stage, real_latency["p50_ms"], eval_p50)
        for stage in ("stt_ms", "llm_ms", "tts_ms")
    }
    p95_stages = {
        stage: merged(stage, real_latency["p95_ms"], eval_p95)
        for stage in ("stt_ms", "llm_ms", "tts_ms")
    }

    detail = report.get("diagnostic_accuracy_detail", {})
    return EngineeringDashboardResponse(
        latency_p50_ms=LatencyStages(**p50_stages),
        latency_p95_ms=LatencyStages(**p95_stages),
        eval=EvalSummary(
            diagnostic_accuracy=report["diagnostic_accuracy"],
            question_groundedness=report["question_groundedness"],
            sample_size=detail.get("sample_size", 0),
        ),
    )
