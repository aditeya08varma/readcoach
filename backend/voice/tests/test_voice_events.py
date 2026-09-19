"""Unit tests for the voice pipeline's event shapes against
`contracts/voice_events.md` - the two events actually built in
`backend/voice` (as opposed to `miscue_detected`/`hint_spoken`/etc, built by
`tutor-logic-engineer` and only forwarded here).

`word_recognized` is a pure function in voice_events.py, tested directly.
`passage_loaded` has no equivalent builder function - it's constructed
inline in tutor_processor.py's `announce_passage()` - so that method is
exercised directly instead, with a fake RTVI processor standing in for the
real one (announce_passage only ever calls `rtvi.send_server_message`, it
doesn't touch STT/TTS/tutoring at all, so no real Pipecat pipeline is
needed to test it).
"""

import pytest

from voice_events import KNOWN_EVENT_TYPES, SessionClock, word_recognized


def test_word_recognized_event_shape():
    """Exact contract shape per contracts/voice_events.md's `word_recognized`
    entry: type, t, word, start_ms, end_ms, confidence - no more, no fewer
    fields, and `t` comes from the shared clock, not re-derived."""
    clock = SessionClock()
    clock.start()

    event = word_recognized(clock, word="fox", start_ms=1180, end_ms=1234, confidence=0.93)

    assert event["type"] == "word_recognized"
    assert isinstance(event["t"], int)
    assert event["word"] == "fox"
    assert event["start_ms"] == 1180
    assert event["end_ms"] == 1234
    assert event["confidence"] == 0.93
    assert set(event.keys()) == {"type", "t", "word", "start_ms", "end_ms", "confidence"}


def test_word_recognized_uses_the_shared_clock_for_t():
    """`t` must be "ms since session start" per the contract, not a fixed or
    caller-supplied value - two events built moments apart should reflect
    that on the same clock."""
    clock = SessionClock()
    clock.start()

    first = word_recognized(clock, word="a", start_ms=0, end_ms=10, confidence=1.0)
    second = word_recognized(clock, word="b", start_ms=10, end_ms=20, confidence=1.0)

    assert second["t"] >= first["t"]


def test_session_clock_auto_starts_instead_of_raising():
    """Documented behavior (SessionClock's own docstring): reading now_ms()
    before start() has been called auto-starts the clock rather than
    crashing a stray early frame."""
    clock = SessionClock()
    assert not clock.started

    t = clock.now_ms()

    assert clock.started
    assert isinstance(t, int)
    assert t >= 0


def test_word_recognized_type_is_a_known_event_type():
    assert "word_recognized" in KNOWN_EVENT_TYPES


PASSAGE = {
    "id": "g1-short-vowels-001",
    "grade": 1,
    "title": "Pat and the Big Hat",
    "text": "Pat has a big hat.",
    "words": ["Pat", "has", "a", "big", "hat"],
    "skills": ["short_vowels"],
    "primary_skill": "short_vowels",
    "comprehension_hint_topics": ["what Pat did"],
}


class _FakeRTVI:
    """Stands in for RTVIProcessor - only `send_server_message` is ever
    called by the code paths under test, so that's all this needs to
    implement, recording every call for assertions."""

    def __init__(self):
        self.sent_messages: list[dict] = []

    async def send_server_message(self, event: dict) -> None:
        self.sent_messages.append(event)


def _make_tutor_processor(rtvi, passage=PASSAGE):
    from voice_events import SessionClock as _Clock
    from tutor_processor import TutorProcessor

    return TutorProcessor(
        _Clock(),
        passage=passage,
        llm_api_key="unused-fake-key",
        student_id=None,
        rtvi=rtvi,
        # A truthy stand-in is enough: `llm_client or TutorLLMClient(...)`
        # short-circuits on it, so the real Anthropic SDK client is never
        # constructed and no API key is ever needed for this test - neither
        # announce_passage() nor greet() touch the LLM at all.
        llm_client=object(),
    )


@pytest.mark.asyncio
async def test_passage_loaded_event_shape():
    """Exact contract shape per contracts/voice_events.md's `passage_loaded`
    entry: `{"type": "passage_loaded", "t": ..., "passage": <the full
    Passage object>}`, emitted via announce_passage() before the greeting."""
    rtvi = _FakeRTVI()
    processor = _make_tutor_processor(rtvi)

    await processor.announce_passage()

    assert len(rtvi.sent_messages) == 1
    event = rtvi.sent_messages[0]
    assert event["type"] == "passage_loaded"
    assert isinstance(event["t"], int)
    assert event["passage"] == PASSAGE
    assert set(event.keys()) == {"type", "t", "passage"}


@pytest.mark.asyncio
async def test_passage_loaded_carries_the_exact_passage_the_bot_picked():
    """Real bug this event exists to fix (see the contract entry's own
    comment): the frontend must be able to trust this is THE passage the
    bot is grading against, not a copy/subset of it."""
    rtvi = _FakeRTVI()
    other_passage = {**PASSAGE, "id": "g2-blends-003", "title": "A Different Story"}
    processor = _make_tutor_processor(rtvi, passage=other_passage)

    await processor.announce_passage()

    assert rtvi.sent_messages[0]["passage"] is other_passage
