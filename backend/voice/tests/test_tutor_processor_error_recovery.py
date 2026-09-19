"""Regression coverage for the ErrorFrame/recovery-line fix in
tutor_processor.py (a prior audit finding: Pipecat's own FrameProcessor
already turns an unhandled exception into an ErrorFrame and pushes it
upstream, but nothing used to listen for it - a Claude hiccup mid-turn left
the child in silence with the state machine stuck, a hang rather than a
crash).

Two real scenarios, both driven straight through `process_frame` with
`push_frame`/`push_error` swapped for recording stand-ins - the pipeline's
own queue/task machinery isn't under test here, just this processor's own
decision to speak a recovery line and not let an exception vanish silently:

1. An exception raised out of this processor's own transcription handling
   (the actual "Claude API call fails mid-comprehension-turn" case).
2. An ErrorFrame arriving from a neighboring processor (e.g. Cartesia TTS
   failing outright), which used to just get forwarded upstream unheeded.
"""

import pytest

from pipecat.frames.frames import ErrorFrame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection

from tutor_processor import ERROR_RECOVERY_TEXT, TutorProcessor
from voice_events import SessionClock

PASSAGE = {
    "id": "g1-short-vowels-001",
    "grade": 1,
    "title": "Pat and the Big Hat",
    "text": "Pat has a big hat.",
    "words": ["Pat", "has", "a", "big", "hat"],
    "skills": ["short_vowels"],
    "primary_skill": "short_vowels",
    "comprehension_hint_topics": [],
}


class _FakeRTVI:
    async def send_server_message(self, event: dict) -> None:
        pass


def _make_processor():
    processor = TutorProcessor(
        SessionClock(),
        passage=PASSAGE,
        llm_api_key="unused-fake-key",
        student_id=None,
        rtvi=_FakeRTVI(),
        llm_client=object(),  # never called by anything exercised here
    )

    pushed_frames: list[tuple] = []
    pushed_errors: list[tuple] = []

    async def fake_push_frame(frame, direction=FrameDirection.DOWNSTREAM):
        pushed_frames.append((frame, direction))

    async def fake_push_error(msg, exception=None, **kwargs):
        pushed_errors.append((msg, exception))

    processor.push_frame = fake_push_frame
    processor.push_error = fake_push_error
    return processor, pushed_frames, pushed_errors


@pytest.mark.asyncio
async def test_exception_during_transcription_handling_speaks_recovery_line_instead_of_hanging():
    processor, pushed_frames, pushed_errors = _make_processor()

    async def boom(frame):
        raise RuntimeError("Claude API failure (simulated)")

    processor._handle_transcription = boom
    transcription = TranscriptionFrame(text="hi", user_id="u", timestamp="t")

    # Must not raise - this is exactly the bug: letting it escape used to
    # leave the child in silence with no further handling.
    await processor.process_frame(transcription, FrameDirection.DOWNSTREAM)

    assert len(pushed_frames) == 1
    frame, direction = pushed_frames[0]
    assert isinstance(frame, TTSSpeakFrame)
    assert frame.text == ERROR_RECOVERY_TEXT
    # The rest of the pipeline still gets told something broke.
    assert len(pushed_errors) == 1


@pytest.mark.asyncio
async def test_incoming_error_frame_from_a_neighbor_speaks_recovery_and_still_forwards_it():
    processor, pushed_frames, _ = _make_processor()
    incoming = ErrorFrame(error="Cartesia TTS failed: connection reset")

    await processor.process_frame(incoming, FrameDirection.UPSTREAM)

    assert len(pushed_frames) == 2
    (first_frame, _), (second_frame, second_direction) = pushed_frames
    assert isinstance(first_frame, TTSSpeakFrame)
    assert first_frame.text == ERROR_RECOVERY_TEXT
    # Still forwarded upstream unchanged - this only adds a spoken response,
    # it doesn't swallow pipeline-level error handling (ProcessorUnusablePolicy,
    # observers) further up the chain.
    assert second_frame is incoming
    assert second_direction == FrameDirection.UPSTREAM


@pytest.mark.asyncio
async def test_a_clean_transcription_frame_does_not_trigger_any_recovery_line():
    """Sanity check that this fix doesn't fire on the happy path."""
    processor, pushed_frames, pushed_errors = _make_processor()

    async def no_op(frame):
        return None

    processor._handle_transcription = no_op
    transcription = TranscriptionFrame(text="hi", user_id="u", timestamp="t")

    await processor.process_frame(transcription, FrameDirection.DOWNSTREAM)

    assert pushed_frames == []
    assert pushed_errors == []
