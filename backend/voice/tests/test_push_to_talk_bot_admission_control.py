"""Coverage for push_to_talk_bot.py's admission control (`run_bot`'s
capacity cap) - the same pattern as bot.py's identical mechanism (see
test_bot_admission_and_choice.py), tested separately here because this
module keeps its own independent `_active_sessions` counter/lock (a
separate process from bot.py, per this file's own module comment).

push_to_talk_bot.py has no `/choose_passage` / `/choose_student` routes
(module docstring point 2 - not implemented here yet), so there is no
selection logic to test for this module beyond the admission control cap
itself.
"""

from __future__ import annotations

import pytest

import push_to_talk_bot as ptt_bot_module


class _FakeTransport:
    def __init__(self):
        self.cleanup_called = False

    async def cleanup(self):
        self.cleanup_called = True


@pytest.fixture(autouse=True)
def _reset_active_sessions():
    ptt_bot_module._active_sessions = 0
    yield
    ptt_bot_module._active_sessions = 0


@pytest.mark.asyncio
async def test_run_bot_rejects_a_new_session_when_already_at_capacity(monkeypatch):
    monkeypatch.setattr(ptt_bot_module, "MAX_CONCURRENT_SESSIONS", 2)
    ptt_bot_module._active_sessions = 2

    session_calls = []

    async def fake_run_bot_session(transport, runner_args):
        session_calls.append((transport, runner_args))

    monkeypatch.setattr(ptt_bot_module, "_run_bot_session", fake_run_bot_session)

    transport = _FakeTransport()
    await ptt_bot_module.run_bot(transport, runner_args=object())

    assert transport.cleanup_called is True
    assert session_calls == []
    assert ptt_bot_module._active_sessions == 2


@pytest.mark.asyncio
async def test_run_bot_admits_a_session_under_capacity_and_decrements_when_done(monkeypatch):
    monkeypatch.setattr(ptt_bot_module, "MAX_CONCURRENT_SESSIONS", 2)
    ptt_bot_module._active_sessions = 0

    active_count_during_session = []

    async def fake_run_bot_session(transport, runner_args):
        active_count_during_session.append(ptt_bot_module._active_sessions)

    monkeypatch.setattr(ptt_bot_module, "_run_bot_session", fake_run_bot_session)

    transport = _FakeTransport()
    await ptt_bot_module.run_bot(transport, runner_args=object())

    assert active_count_during_session == [1]
    assert transport.cleanup_called is False
    assert ptt_bot_module._active_sessions == 0


@pytest.mark.asyncio
async def test_run_bot_decrements_the_counter_even_if_the_session_raises(monkeypatch):
    monkeypatch.setattr(ptt_bot_module, "MAX_CONCURRENT_SESSIONS", 2)
    ptt_bot_module._active_sessions = 0

    async def fake_run_bot_session(transport, runner_args):
        raise RuntimeError("simulated session crash")

    monkeypatch.setattr(ptt_bot_module, "_run_bot_session", fake_run_bot_session)

    transport = _FakeTransport()
    with pytest.raises(RuntimeError):
        await ptt_bot_module.run_bot(transport, runner_args=object())

    assert ptt_bot_module._active_sessions == 0
