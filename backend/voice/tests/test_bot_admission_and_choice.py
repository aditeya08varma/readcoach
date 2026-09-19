"""Coverage for bot.py's admission control (`run_bot`'s capacity cap) and
its `/choose_passage` / `/choose_student` selection mechanism, previously
untested. None of this needs a live Daily/Deepgram connection - the cap is
plain counter/lock logic, and the passage/student selection is a plain dict
keyed by session_id, consumed once by `_run_bot_session` via `.pop(...)`.

`_run_bot_session`'s own body constructs real Deepgram/Cartesia/Anthropic
services and a full Pipecat pipeline, none of which should run in a unit
test - the selection tests below exercise the REAL `_run_bot_session`
function up to (and including) its `fetch_next_passage(...)` call, then
deliberately abort it there via a stub `fetch_next_passage` that raises a
sentinel exception, so the pop-and-consume logic that happens before that
call is exercised for real without needing to fake the rest of the pipeline.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import bot as bot_module


class _FakeTransport:
    def __init__(self):
        self.cleanup_called = False

    async def cleanup(self):
        self.cleanup_called = True


@pytest.fixture(autouse=True)
def _reset_bot_module_state():
    """`_active_sessions`/`_pending_passage_choice`/`_pending_student_id` are
    module-level mutable state shared across every test in this file (and,
    in the real process, across every concurrent session) - reset before
    each test so none of them leak between tests."""
    bot_module._active_sessions = 0
    bot_module._pending_passage_choice.clear()
    bot_module._pending_student_id.clear()
    yield
    bot_module._active_sessions = 0
    bot_module._pending_passage_choice.clear()
    bot_module._pending_student_id.clear()


# ---------------------------------------------------------------------------
# run_bot: admission control cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_bot_rejects_a_new_session_when_already_at_capacity(monkeypatch):
    monkeypatch.setattr(bot_module, "MAX_CONCURRENT_SESSIONS", 2)
    bot_module._active_sessions = 2

    session_calls = []

    async def fake_run_bot_session(transport, runner_args):
        session_calls.append((transport, runner_args))

    monkeypatch.setattr(bot_module, "_run_bot_session", fake_run_bot_session)

    transport = _FakeTransport()
    await bot_module.run_bot(transport, runner_args=object())

    assert transport.cleanup_called is True, "a rejected connection must still be cleaned up"
    assert session_calls == [], "the real session must never start once at capacity"
    assert bot_module._active_sessions == 2, "a rejected session must not touch the counter"


@pytest.mark.asyncio
async def test_run_bot_admits_a_session_under_capacity_and_decrements_when_done(monkeypatch):
    monkeypatch.setattr(bot_module, "MAX_CONCURRENT_SESSIONS", 2)
    bot_module._active_sessions = 0

    active_count_during_session = []

    async def fake_run_bot_session(transport, runner_args):
        # The counter must already reflect this session while it's running -
        # that's the whole point of incrementing before the session starts.
        active_count_during_session.append(bot_module._active_sessions)

    monkeypatch.setattr(bot_module, "_run_bot_session", fake_run_bot_session)

    transport = _FakeTransport()
    await bot_module.run_bot(transport, runner_args=object())

    assert active_count_during_session == [1]
    assert transport.cleanup_called is False, "an admitted session must not be cleaned up by the cap logic"
    assert bot_module._active_sessions == 0, "decremented back down once the session finishes"


@pytest.mark.asyncio
async def test_run_bot_decrements_the_counter_even_if_the_session_raises(monkeypatch):
    monkeypatch.setattr(bot_module, "MAX_CONCURRENT_SESSIONS", 2)
    bot_module._active_sessions = 0

    async def fake_run_bot_session(transport, runner_args):
        raise RuntimeError("simulated session crash")

    monkeypatch.setattr(bot_module, "_run_bot_session", fake_run_bot_session)

    transport = _FakeTransport()
    with pytest.raises(RuntimeError):
        await bot_module.run_bot(transport, runner_args=object())

    assert bot_module._active_sessions == 0, "the finally block must still release the slot"


@pytest.mark.asyncio
async def test_run_bot_admits_exactly_up_to_the_cap_and_rejects_the_next_one(monkeypatch):
    monkeypatch.setattr(bot_module, "MAX_CONCURRENT_SESSIONS", 1)
    bot_module._active_sessions = 0

    # A session that "stays open" until we let it finish, so a second
    # concurrent call to run_bot sees the counter still at 1.
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_bot_session(transport, runner_args):
        started.set()
        await release.wait()

    monkeypatch.setattr(bot_module, "_run_bot_session", fake_run_bot_session)

    first_transport = _FakeTransport()
    first_task = asyncio.create_task(bot_module.run_bot(first_transport, runner_args=object()))
    await started.wait()
    assert bot_module._active_sessions == 1

    second_transport = _FakeTransport()
    await bot_module.run_bot(second_transport, runner_args=object())
    assert second_transport.cleanup_called is True, "rejected while the first session is still active"

    release.set()
    await first_task
    assert bot_module._active_sessions == 0


# ---------------------------------------------------------------------------
# /choose_passage, /choose_student
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_choose_passage_stores_the_pending_choice_keyed_by_session_id():
    result = await bot_module.choose_passage({"session_id": "sess-1", "passage_id": "g2-blends-003"})

    assert result == {"ok": True, "passage_id": "g2-blends-003"}
    assert bot_module._pending_passage_choice == {"sess-1": "g2-blends-003"}


@pytest.mark.asyncio
async def test_choose_passage_without_a_session_id_stores_nothing():
    result = await bot_module.choose_passage({"passage_id": "g2-blends-003"})

    assert result == {"ok": True, "passage_id": "g2-blends-003"}
    assert bot_module._pending_passage_choice == {}


@pytest.mark.asyncio
async def test_choose_passage_without_a_passage_id_stores_nothing():
    result = await bot_module.choose_passage({"session_id": "sess-1"})

    assert result["ok"] is True
    assert bot_module._pending_passage_choice == {}


@pytest.mark.asyncio
async def test_choose_student_stores_the_pending_choice_keyed_by_session_id():
    result = await bot_module.choose_student({"session_id": "sess-1", "student_id": "real-student-42"})

    assert result == {"ok": True, "student_id": "real-student-42"}
    assert bot_module._pending_student_id == {"sess-1": "real-student-42"}


@pytest.mark.asyncio
async def test_choose_student_without_a_student_id_stores_nothing():
    result = await bot_module.choose_student({"session_id": "sess-1"})

    assert result["ok"] is True
    assert bot_module._pending_student_id == {}


# ---------------------------------------------------------------------------
# _run_bot_session: consuming (and popping) the pending choice
# ---------------------------------------------------------------------------


class _StopEarly(Exception):
    """Raised by a stubbed fetch_next_passage to abort _run_bot_session
    right after it resolves passage/student selection, before it goes on to
    build a real Deepgram/Cartesia/Pipecat pipeline this test has no
    business constructing."""


@pytest.mark.asyncio
async def test_run_bot_session_consumes_and_pops_an_explicit_passage_and_student_choice(monkeypatch):
    session_id = "sess-abc"
    bot_module._pending_passage_choice[session_id] = "g2-blends-003"
    bot_module._pending_student_id[session_id] = "real-student-1"

    captured = {}

    async def fake_fetch_next_passage(passage_id, student_id_override):
        captured["passage_id"] = passage_id
        captured["student_id_override"] = student_id_override
        raise _StopEarly()

    monkeypatch.setattr(bot_module, "fetch_next_passage", fake_fetch_next_passage)

    runner_args = SimpleNamespace(session_id=session_id)
    with pytest.raises(_StopEarly):
        await bot_module._run_bot_session(_FakeTransport(), runner_args)

    assert captured["passage_id"] == "g2-blends-003"
    assert captured["student_id_override"] == "real-student-1"
    # Popped, not just read - a second connection reusing this session_id
    # (shouldn't normally happen, but this is the real race the mechanism
    # exists to prevent, see bot.py's own module comment) must not replay
    # this one's choice.
    assert session_id not in bot_module._pending_passage_choice
    assert session_id not in bot_module._pending_student_id


@pytest.mark.asyncio
async def test_run_bot_session_falls_back_to_auto_select_with_no_pending_choice(monkeypatch):
    session_id = "sess-no-choice"

    captured = {}

    async def fake_fetch_next_passage(passage_id, student_id_override):
        captured["passage_id"] = passage_id
        captured["student_id_override"] = student_id_override
        raise _StopEarly()

    monkeypatch.setattr(bot_module, "fetch_next_passage", fake_fetch_next_passage)

    runner_args = SimpleNamespace(session_id=session_id)
    with pytest.raises(_StopEarly):
        await bot_module._run_bot_session(_FakeTransport(), runner_args)

    assert captured["passage_id"] is None
    assert captured["student_id_override"] is None


@pytest.mark.asyncio
async def test_run_bot_session_with_no_session_id_skips_lookup_entirely(monkeypatch):
    """A missing runner_args.session_id (only possible driven by something
    other than this project's own frontend, per bot.py's own comment) must
    fall back to "no explicit choice" the same as any other cache miss,
    without raising trying to look one up."""
    captured = {}

    async def fake_fetch_next_passage(passage_id, student_id_override):
        captured["passage_id"] = passage_id
        captured["student_id_override"] = student_id_override
        raise _StopEarly()

    monkeypatch.setattr(bot_module, "fetch_next_passage", fake_fetch_next_passage)

    runner_args = SimpleNamespace(session_id=None)
    with pytest.raises(_StopEarly):
        await bot_module._run_bot_session(_FakeTransport(), runner_args)

    assert captured["passage_id"] is None
    assert captured["student_id_override"] is None
