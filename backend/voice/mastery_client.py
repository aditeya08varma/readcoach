"""Thin client for the mastery-engineer service (backend/mastery), used to
prove the voice-pipeline <-> mastery-service seam end to end.

Written during integration (not by voice-pipeline-engineer or
mastery-engineer individually) since it is the connective code between two
already-independently-verified modules. Best-effort throughout: if the
mastery service isn't running, callers fall back to a local default passage
so a demo/test run of the voice bot never hard-fails just because a second
process isn't up. This mirrors the same "try live, fall back to a local
default" pattern frontend-engineer used for the dashboards.

The demo student is the single, shared, well-known row GET /students/demo
get-or-creates on the mastery service - not a student this file creates on
its own. A real gap found from a real screen recording: this used to create
its own separate demo student, cached in a local file, while the frontend
independently pointed at a different hardcoded placeholder id - two demo
students that never lined up, so the dashboards could never show a real
voice session's results. Asking the server for the one shared row instead
fixes that for both sides at once (see docs/BUILD_LOG.md).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from loguru import logger

MASTERY_SERVICE_URL = os.environ.get("MASTERY_SERVICE_URL", "http://localhost:8000")
_DEFAULT_PASSAGE_ID = "g1-short-vowels-001"
_CONTENT_PASSAGES_DIR = Path(__file__).resolve().parents[2] / "content" / "passages"


def _load_local_passage(passage_id: str = _DEFAULT_PASSAGE_ID) -> dict:
    path = _CONTENT_PASSAGES_DIR / f"{passage_id}.json"
    if not path.exists():
        # A chosen passage_id that doesn't exist as a local file either
        # (shouldn't happen - content/ is the same directory the mastery
        # service reads from - but this is the local-fallback path, so it
        # has to degrade gracefully rather than crash a live session).
        logger.warning(f"local passage file not found for {passage_id!r}, using default instead")
        path = _CONTENT_PASSAGES_DIR / f"{_DEFAULT_PASSAGE_ID}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def _get_or_create_demo_student() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{MASTERY_SERVICE_URL}/students/demo")
            resp.raise_for_status()
            student_id = resp.json()["id"]
            logger.info(f"Using shared demo student {student_id} from mastery service")
            return student_id
    except Exception as e:
        logger.warning(f"mastery service unreachable, no demo student available: {e}")
        return None


async def fetch_next_passage(
    passage_id: str | None = None,
    student_id_override: str | None = None,
) -> tuple[dict, str | None]:
    """Returns (passage_dict, student_id_or_None). student_id is None when the
    mastery service wasn't reachable, in which case the caller is running
    against a local default passage with no mastery tracking for this run.

    `passage_id`, when given, is a real person's explicit choice (the story
    map's tap-a-node flow, threaded through from the browser's WebRTC
    connection request into `runner_args.body` - see bot.py and
    contracts/api_contract.md's GET /students/{id}/passages/{passage_id})
    rather than the mastery engine auto-selecting one. Falls back to
    auto-select if the mastery service can't be reached even for a chosen
    passage, same as the existing fallback behavior below - a demo student
    can't look up mastery-enriched data (selection_reason, challenge word)
    from a service that isn't running either way.

    `student_id_override`, when given, is a real logged-in parent's own real
    student (see frontend/auth.ts, threaded through the same /choose_student
    + _pending_student_id mechanism bot.py already uses for passage choice -
    docs/BUILD_LOG.md has the full writeup). Takes priority over the shared
    demo student so a real session updates that real student's real mastery.
    Absent (no login, or local dev without the frontend's auth layer at all),
    this falls back to the shared demo student exactly as it always did
    before login existed.
    """
    student_id = student_id_override or await _get_or_create_demo_student()
    if student_id is None:
        return _load_local_passage(passage_id or _DEFAULT_PASSAGE_ID), None

    path = f"/students/{student_id}/passages/{passage_id}" if passage_id else f"/students/{student_id}/next_passage"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{MASTERY_SERVICE_URL}{path}")
            resp.raise_for_status()
            return resp.json(), student_id
    except Exception as e:
        logger.warning(f"mastery service passage call ({path}) failed, using local default: {e}")
        return _load_local_passage(passage_id or _DEFAULT_PASSAGE_ID), student_id


async def fetch_mastery_vector(student_id: str | None) -> dict[str, float] | None:
    """GET /students/{id}/mastery per contracts/api_contract.md, reshaped
    into {skill_id: weight} - exactly the shape state_machine.TutorSession's
    mastery-aware hint pacing expects (see docs/FEATURE_IDEAS.md). Same
    best-effort pattern as the rest of this module: None (no data, no
    pacing adjustment - state_machine.py already treats that as "hint
    immediately", today's original behavior) covers both "no demo student
    yet" and "mastery service unreachable" so a live session never stalls
    on this call.
    """
    if student_id is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{MASTERY_SERVICE_URL}/students/{student_id}/mastery")
            resp.raise_for_status()
            return {row["skill_id"]: row["weight"] for row in resp.json()}
    except Exception as e:
        logger.warning(f"mastery service mastery-vector call failed, hints will fire immediately: {e}")
        return None


async def post_completed_session(
    *, student_id: str, passage_id: str, session_columns: dict
) -> str | None:
    """POST /sessions per contracts/api_contract.md. Best-effort: logs and
    swallows failures rather than crashing the voice pipeline over a
    bookkeeping call after the child's session already finished.

    Returns the real, server-minted `session_id` from main.py's
    `IngestSessionResponse` (the `/sessions` response body always includes
    it, confirmed live) on success - real contract violation found by an
    audit and fixed here: tutor_processor.py's `session_ended` event
    (contracts/voice_events.md) is required to carry this id, and this was
    the one place it could come from, since `session_id` doesn't exist
    anywhere until this POST succeeds. Returns None on any failure (timeout,
    connection error, non-2xx) - same best-effort behavior as before, just
    now the caller can tell "not persisted" from "persisted" instead of
    always getting nothing back.
    """
    payload = {
        "student_id": student_id,
        "passage_id": passage_id,
        "wcpm": session_columns.get("wcpm"),
        "accuracy": session_columns.get("accuracy"),
        "self_corrections": session_columns.get("self_corrections", 0),
        "miscues": session_columns.get("miscues", []),
        "comprehension": session_columns.get("comprehension", []),
        "hints_delayed_count": session_columns.get("hints_delayed_count", 0),
        "hints_delayed_self_corrected_count": session_columns.get("hints_delayed_self_corrected_count", 0),
        # Real per-stage latency (see backend/voice/latency_observer.py) -
        # previously never populated at all; None when a session produced
        # no real samples for any stage (see tutor_processor.py's
        # _collect_pipeline_latency_ms), same as before this existed.
        "pipeline_latency_ms": session_columns.get("pipeline_latency_ms"),
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(f"{MASTERY_SERVICE_URL}/sessions", json=payload)
            resp.raise_for_status()
            body = resp.json()
            logger.info(f"Posted session to mastery service: {body}")
            return body.get("session_id")
    except Exception as e:
        logger.warning(f"Failed to post session to mastery service (non-fatal): {e}")
        return None
