"""Event builders for the event types `tutor-logic-engineer` owns
(`contracts/voice_events.md`): `miscue_detected`, `hint_spoken`,
`review_word_result`, `passage_complete`, `comprehension_turn`.

Mirrors the style of `backend/voice/events.py` (plain dict builders, `t` in
ms since session start), but does not import from `backend/voice` - that
module is owned by `voice-pipeline-engineer` and this one must stay usable
standalone (e.g. in unit tests, or the eval harness) without pulling in the
Daily/Deepgram/pipecat stack. `miscue_detected` itself is built by
`Miscue.to_event()` in `alignment.py`, since it needs the `Miscue` dataclass
right there; the builders below cover the rest.

`hint_pending` used to live here too, for a mid-read mastery-aware hint
delay that no longer exists (see state_machine.py's module docstring) - the
builder was removed with the feature it existed for, not left as dead code.
"""

from __future__ import annotations

from typing import Any


def hint_spoken(*, t: int, skill_id: str, text: str) -> dict[str, Any]:
    return {"type": "hint_spoken", "t": t, "skill_id": skill_id, "text": text}


def review_word_result(
    *, t: int, reference_index: int, reference_word: str | None, correct: bool
) -> dict[str, Any]:
    # Emitted once per word during the end-of-passage review (see
    # state_machine.py's REVIEW state), right after the child says a
    # previously-missed word again. The frontend doesn't render this yet -
    # miscue_detected/hint_spoken already cover what it shows today - but
    # this is real, useful signal (which specific re-attempts the child got
    # right) worth keeping in the contract for a future re-color-the-word or
    # per-word confirmation UI, rather than only living in a TTS line nobody
    # can see after the fact.
    return {
        "type": "review_word_result",
        "t": t,
        "reference_index": reference_index,
        "reference_word": reference_word,
        "correct": correct,
    }


def passage_complete(
    *, t: int, wcpm: float, accuracy: float, self_corrections: int
) -> dict[str, Any]:
    return {
        "type": "passage_complete",
        "t": t,
        "wcpm": wcpm,
        "accuracy": accuracy,
        "self_corrections": self_corrections,
    }


def comprehension_turn(
    *,
    t: int,
    question: str,
    answer_given: str,
    correct: bool,
    skill_id: str,
    feedback_text: str | None = None,
) -> dict[str, Any]:
    # feedback_text carries the warm spoken response TutorLLMClient.grade_answer
    # already produces alongside its correct/incorrect judgment, so the voice
    # pipeline has something to speak back without a second LLM call. Optional
    # and additive to contracts/voice_events.md - added during integration
    # after the orchestrator noticed submit_answer was computing this text and
    # then discarding it.
    event: dict[str, Any] = {
        "type": "comprehension_turn",
        "t": t,
        "question": question,
        "answer_given": answer_given,
        "correct": correct,
        "skill_id": skill_id,
    }
    if feedback_text is not None:
        event["feedback_text"] = feedback_text
    return event
