"""End-to-end pipeline latency, measured by actually running the REAL
`backend/tutor/state_machine.TutorSession` (imported, not reimplemented)
through synthetic reading sessions with real Claude API calls, timing each
call.

Why this measures its own latency instead of reading `pipeline_latency_ms`
from the `sessions` table (as this agent's role brief originally describes):
checked first, per contracts/db_schema.sql - the real `sessions` table
(backend/mastery/mastery_dev.db) has exactly one row so far, from the one
manual integration test in docs/BUILD_LOG.md, and its `pipeline_latency_ms`
column is NULL (stt/tts timing was never wired into that single test). One
null data point can't produce a P50/P95. Flagged in the eval report rather
than silently working around it: this harness measures the one latency
number it CAN honestly produce with real API calls it owns - the LLM stage
(`llm_ms`), broken down per call kind (hint / question generation /
grading). `stt_ms` and `tts_ms` are voice-pipeline-engineer's Deepgram/
Cartesia stages, which this harness has no access to and does not fabricate;
they're reported as `null` with an explicit note rather than invented.

TimingLLMClient wraps a real `TutorLLMClient` and satisfies the exact same
duck-typed interface `TutorSession` requires (per state_machine.py's own
docstring: all four of generate_hint/generate_questions/grade_answer/
is_answer_complete), so `TutorSession` here is the real, unmodified pipeline
code end to end - this file only adds a stopwatch around it. This harness's
own scenario never calls hear_partial_answer (it drives submit_answer
directly, see _run_one_session below), so is_answer_complete is never
actually invoked here - forwarded anyway so this class keeps satisfying the
real interface it claims to, rather than silently falling one method short
of it (a real bug found and fixed in backend/voice/latency_observer.py's
identically-shaped wrapper, which WAS hit - see docs/BUILD_LOG.md).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

_TUTOR_DIR = Path(__file__).resolve().parents[1] / "tutor"
if str(_TUTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TUTOR_DIR))

from claude_client import TutorLLMClient  # noqa: E402
from state_machine import TutorSession  # noqa: E402

_PASSAGES_DIR = Path(__file__).resolve().parents[2] / "content" / "passages"

# Diverse cross-section by grade/skill/length, distinct from the
# groundedness sample so the two evals don't lean on identical passages.
LATENCY_PASSAGE_IDS = [
    "g1-blends-001",
    "g1-digraphs-001",
    "g1-silent-e-001",
    "g2-diphthongs-001",
    "g2-open-syllables-001",
    "g2-r-controlled-001",
    "g3-compound-words-001",
    "g3-multisyllabic-001",
    "g3-inferential-002",
    "g1-closed-syllables-001",
]

QUESTIONS_PER_SESSION = 2
_DECOY = "zorp"


def _load_passage(passage_id: str) -> dict:
    with open(_PASSAGES_DIR / f"{passage_id}.json", encoding="utf-8") as f:
        return json.load(f)


def _word_event(word: str, t: int) -> dict:
    return {"type": "word_recognized", "t": t, "word": word, "start_ms": t - 300, "end_ms": t, "confidence": 0.9}


class TimingLLMClient:
    """Wraps a real `TutorLLMClient`, delegating every call to it (no
    reimplementation, no mocked responses) while recording real wall-clock
    latency per call kind into `sink`.
    """

    def __init__(self, real_client: TutorLLMClient, sink: dict[str, list[float]]) -> None:
        self._real = real_client
        self._sink = sink

    async def generate_hint(self, **kwargs):
        t0 = time.perf_counter()
        result = await self._real.generate_hint(**kwargs)
        self._sink["hint_ms"].append((time.perf_counter() - t0) * 1000)
        return result

    async def generate_questions(self, **kwargs):
        t0 = time.perf_counter()
        result = await self._real.generate_questions(**kwargs)
        self._sink["question_generation_ms"].append((time.perf_counter() - t0) * 1000)
        return result

    async def grade_answer(self, **kwargs):
        t0 = time.perf_counter()
        result = await self._real.grade_answer(**kwargs)
        self._sink["grading_ms"].append((time.perf_counter() - t0) * 1000)
        return result

    async def is_answer_complete(self, **kwargs):
        t0 = time.perf_counter()
        result = await self._real.is_answer_complete(**kwargs)
        self._sink["completeness_ms"].append((time.perf_counter() - t0) * 1000)
        return result


async def _run_one_session(passage_id: str, sink: dict[str, list[float]]) -> dict:
    passage = _load_passage(passage_id)
    words = passage["words"]

    # Inject exactly one substitution, far enough from the end that
    # SETTLE_LOOKAHEAD lets it settle and fire a real hint call before
    # finish_passage() - a real substitution miscue exercising the fast-tier
    # LLM touchpoint, same as a real stumble would.
    target_index = max(2, min(len(words) // 2, len(words) - 4))
    spoken_words = list(words)
    spoken_words[target_index] = _DECOY

    timing_client = TimingLLMClient(TutorLLMClient(), sink)
    session = TutorSession(passage=passage, llm_client=timing_client)

    session_t0 = time.perf_counter()
    for i, word in enumerate(spoken_words):
        await session.feed_word_recognized(_word_event(word, (i + 1) * 400))
    session.finish_passage(now_t=(len(spoken_words) + 1) * 400)

    # Real bug found by actually running this and checking WHY
    # hint_generation came back n=0 across every session (see
    # docs/BUILD_LOG.md): every real session walks a review phase between
    # finish_passage and comprehension now (state_machine.py's own
    # start_review docstring - this replaced the old mid-read hint
    # mechanism), but this harness jumped straight from finish_passage to
    # start_comprehension, silently skipping the one real LLM touchpoint
    # (generate_hint) this exact stage exists to time. The single injected
    # substitution above always produces exactly one review-queue entry, so
    # this now genuinely exercises it - the specific reply text doesn't
    # matter for timing purposes (submit_review_reply advances regardless
    # of whether it's judged correct; only the comprehension retry path
    # cares about correctness).
    teach_event = await session.start_review()
    review_now_t = (len(spoken_words) + 2) * 400
    while teach_event is not None:
        _, teach_event = await session.submit_review_reply(_DECOY, now_t=review_now_t)
        review_now_t += 400

    await session.start_comprehension(num_questions=QUESTIONS_PER_SESSION)
    while session.current_question is not None:
        # Plausible but generic free-text answer - fine for timing the real
        # grading call; correctness of the grade isn't what this eval scores.
        _, next_q, _ = await session.submit_answer(
            "I think it happened because of what the story said.",
            now_t=int((time.perf_counter() - session_t0) * 1000),
        )
    session_total_ms = (time.perf_counter() - session_t0) * 1000

    return {
        "passage_id": passage_id,
        "num_reference_words": len(words),
        "session_total_llm_ms": round(session_total_ms, 1),
    }


async def run_latency_eval_async() -> dict:
    sink: dict[str, list[float]] = {
        "hint_ms": [],
        "question_generation_ms": [],
        "grading_ms": [],
        "completeness_ms": [],
    }
    per_session = []
    for passage_id in LATENCY_PASSAGE_IDS:
        per_session.append(await _run_one_session(passage_id, sink))

    return {
        "sessions_run": len(LATENCY_PASSAGE_IDS),
        "raw_samples_ms": sink,
        "per_session": per_session,
    }


def run_latency_eval() -> dict:
    return asyncio.run(run_latency_eval_async())


if __name__ == "__main__":
    import env_setup
    env_setup.load_real_api_keys()
    print(json.dumps(run_latency_eval(), indent=2))
