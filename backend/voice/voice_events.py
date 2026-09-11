"""Event schema for the ReadCoach voice pipeline.

This module is the code-level companion to `contracts/voice_events.md` (read
that file first - it is the authoritative contract; `tutor-logic-engineer`
and `frontend-engineer` build against it, so field names/types must not
drift). It exists to make sure the one event type `backend/voice` actually
emits in this Stage 0 pass - `word_recognized` - is constructed the same way
every time, and to give a single, documented forwarding path for events other
modules produce later (miscue_detected, hint_spoken, passage_complete,
comprehension_turn, session_ended all travel over the same Daily data channel,
they just aren't built by this module).

Only `word_recognized` is implemented here. Alignment/miscue classification
belongs to `tutor-logic-engineer`, and mastery scoring/session persistence to
`mastery-engineer` - this module does not decide skill categories, score
reads, or manage session/passage identity, per the voice-pipeline-engineer
role brief.
"""

from __future__ import annotations

import time
from typing import Any


class SessionClock:
    """Monotonic clock shared by every event emitted in one bot session.

    `contracts/voice_events.md` defines each event's `t` field as
    "ms since session start, monotonic". `start()` should be called once,
    as close as possible to the moment the child actually joins (this bot
    calls it from the Daily `on_client_connected` handler). Reading `now_ms()`
    before `start()` has been called auto-starts the clock instead of
    raising, so a stray early frame can't crash the pipeline - it just makes
    that one event's `t` slightly off from true session start.
    """

    def __init__(self) -> None:
        self._t0: float | None = None

    @property
    def started(self) -> bool:
        return self._t0 is not None

    def start(self) -> None:
        self._t0 = time.monotonic()

    def now_ms(self) -> int:
        if self._t0 is None:
            self.start()
        return int((time.monotonic() - self._t0) * 1000)  # type: ignore[operator]


def word_recognized(
    clock: SessionClock,
    *,
    word: str,
    start_ms: int,
    end_ms: int,
    confidence: float,
) -> dict[str, Any]:
    """Build a `word_recognized` event (contracts/voice_events.md).

    Emitted the moment Deepgram finalizes a word - never for interim/partial
    results, only finalized ones drive alignment and highlighting downstream.
    `start_ms`/`end_ms` should come straight from Deepgram's own per-word
    timing (relative to when the STT connection opened), not be re-derived,
    since Deepgram already computed it more accurately than we could.
    """
    return {
        "type": "word_recognized",
        "t": clock.now_ms(),
        "word": word,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "confidence": confidence,
    }


# Known event `type` discriminators from contracts/voice_events.md, for
# validation/logging only - NOT a claim that this module produces all of
# these. `miscue_detected`, `hint_spoken`, `passage_complete`,
# `comprehension_turn`, and `session_ended` are built by other modules and
# handed to this same data-channel forwarding path once those modules exist.
KNOWN_EVENT_TYPES = frozenset(
    {
        "word_recognized",
        "miscue_detected",
        "hint_spoken",
        "passage_complete",
        "comprehension_turn",
        "session_ended",
    }
)
