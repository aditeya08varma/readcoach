"""Unit tests for `PushToTalkTurnGate` (push_to_talk_bot.py) - the actual
turn-taking mechanism behind the push-to-talk fallback mode (see that
module's docstring). Exercises the gate in isolation, with `push_frame`
swapped for a recording stand-in, since none of this depends on a real
Deepgram/Cartesia/Daily pipeline: buffer every TranscriptionFrame, release
them all downstream, in order, the moment a turn ends - either an explicit
`ptt_turn_done` client message or the silence-based auto-flush.

The auto-flush timer uses plain `asyncio.create_task` (see the class's own
comment on why, not this base class's `create_task`/`cancel_task` helpers,
which need a full pipeline's `setup()` call first) - so a bare
`PushToTalkTurnGate()` works standalone here with no pipeline at all.
"""

import asyncio

import pytest

from pipecat.frames.frames import CancelFrame, EndFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.frameworks.rtvi import RTVIClientMessageFrame

import push_to_talk_bot
from push_to_talk_bot import PTT_TURN_DONE_MESSAGE_TYPE, PushToTalkTurnGate


def _transcription(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="u", timestamp="t")


async def _make_gate():
    gate = PushToTalkTurnGate()

    pushed: list[tuple] = []

    async def fake_push_frame(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append((frame, direction))

    gate.push_frame = fake_push_frame
    return gate, pushed


@pytest.mark.asyncio
async def test_transcription_frames_are_held_back_until_turn_done():
    gate, pushed = await _make_gate()

    await gate.process_frame(_transcription("one"), FrameDirection.DOWNSTREAM)
    await gate.process_frame(_transcription("two"), FrameDirection.DOWNSTREAM)

    assert pushed == []  # nothing released yet - still mid-turn


@pytest.mark.asyncio
async def test_explicit_turn_done_signal_releases_buffered_frames_in_order():
    gate, pushed = await _make_gate()
    first, second = _transcription("one"), _transcription("two")

    await gate.process_frame(first, FrameDirection.DOWNSTREAM)
    await gate.process_frame(second, FrameDirection.DOWNSTREAM)
    turn_done = RTVIClientMessageFrame(msg_id="1", type=PTT_TURN_DONE_MESSAGE_TYPE, data=None)
    await gate.process_frame(turn_done, FrameDirection.DOWNSTREAM)

    assert pushed == [(first, FrameDirection.DOWNSTREAM), (second, FrameDirection.DOWNSTREAM)]


@pytest.mark.asyncio
async def test_turn_done_message_itself_is_consumed_not_forwarded():
    gate, pushed = await _make_gate()
    await gate.process_frame(_transcription("one"), FrameDirection.DOWNSTREAM)

    turn_done = RTVIClientMessageFrame(msg_id="1", type=PTT_TURN_DONE_MESSAGE_TYPE, data=None)
    await gate.process_frame(turn_done, FrameDirection.DOWNSTREAM)

    assert turn_done not in [frame for frame, _ in pushed]


@pytest.mark.asyncio
async def test_unrelated_client_messages_pass_through_untouched():
    """Only the ptt_turn_done message type is this gate's concern - any other
    RTVI client message (a future feature, not this one) must not be
    silently swallowed."""
    gate, pushed = await _make_gate()
    other = RTVIClientMessageFrame(msg_id="1", type="some_other_message", data={"x": 1})

    await gate.process_frame(other, FrameDirection.DOWNSTREAM)

    assert pushed == [(other, FrameDirection.DOWNSTREAM)]


@pytest.mark.asyncio
async def test_end_frame_flushes_any_pending_turn_before_forwarding_itself():
    """A session ending mid-turn must not silently drop whatever was already
    recognized (see the class docstring)."""
    gate, pushed = await _make_gate()
    pending = _transcription("half a turn")
    await gate.process_frame(pending, FrameDirection.DOWNSTREAM)

    end_frame = EndFrame()
    await gate.process_frame(end_frame, FrameDirection.DOWNSTREAM)

    assert pushed == [
        (pending, FrameDirection.DOWNSTREAM),
        (end_frame, FrameDirection.DOWNSTREAM),
    ]


@pytest.mark.asyncio
async def test_cancel_frame_also_flushes_before_forwarding():
    gate, pushed = await _make_gate()
    pending = _transcription("half a turn")
    await gate.process_frame(pending, FrameDirection.DOWNSTREAM)

    cancel_frame = CancelFrame()
    await gate.process_frame(cancel_frame, FrameDirection.DOWNSTREAM)

    assert pushed == [
        (pending, FrameDirection.DOWNSTREAM),
        (cancel_frame, FrameDirection.DOWNSTREAM),
    ]


@pytest.mark.asyncio
async def test_silence_auto_flush_releases_a_turn_with_no_explicit_signal(monkeypatch):
    """Fallback-of-the-fallback: if ptt_turn_done never arrives (e.g. the
    data channel itself drops it), the turn must not be stranded forever."""
    monkeypatch.setattr(push_to_talk_bot, "_SILENCE_AUTO_FLUSH_SECONDS", 0.05)
    gate, pushed = await _make_gate()
    frame = _transcription("stranded turn")

    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)
    assert pushed == []  # not yet - still within the silence window

    await asyncio.sleep(0.15)

    assert pushed == [(frame, FrameDirection.DOWNSTREAM)]


@pytest.mark.asyncio
async def test_new_transcription_frame_reschedules_the_auto_flush_timer(monkeypatch):
    """Real word-by-word speech shouldn't auto-flush mid-turn just because
    the silence window since the *first* word elapsed - each new recognized
    word should push the deadline back."""
    monkeypatch.setattr(push_to_talk_bot, "_SILENCE_AUTO_FLUSH_SECONDS", 0.1)
    gate, pushed = await _make_gate()
    first = _transcription("still")
    second = _transcription("talking")

    await gate.process_frame(first, FrameDirection.DOWNSTREAM)
    await asyncio.sleep(0.06)  # more than half the window, but keeps talking
    await gate.process_frame(second, FrameDirection.DOWNSTREAM)
    await asyncio.sleep(0.06)  # would have fired if the timer hadn't reset

    assert pushed == []

    await asyncio.sleep(0.1)

    assert pushed == [
        (first, FrameDirection.DOWNSTREAM),
        (second, FrameDirection.DOWNSTREAM),
    ]
