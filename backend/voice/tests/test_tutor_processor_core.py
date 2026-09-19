"""Direct coverage for tutor_processor.py's actual core logic - previously
untested (test_tutor_processor_error_recovery.py only exercises the
exception-wrapping around `_handle_transcription`, never the reading/review/
comprehension/finish-session logic underneath it).

Exercises `_handle_reading_turn`, `_finish_reading`, `_handle_review_turn`,
`_handle_comprehension_turn`, and `_finish_session` directly: word-count/
insertion-count progress tracking, state transitions between READING/REVIEW/
COMPREHENSION/DONE, and the exact shape of every emitted event - especially
`session_ended`, since asserting its shape here is exactly what would have
caught the real contract-violation bug (missing session_id/passage_id/
pipeline_latency_ms) this same audit found and fixed in tutor_processor.py's
_finish_session.

Fakes `TutorSession`'s LLM dependency and RTVI the same way
test_tutor_processor_error_recovery.py and backend/tutor/tests/
test_state_machine.py already do - a real `TutorSession` (unmodified) drives
every test here, with only its `llm_client` faked out, so these tests
exercise the real state machine wiring, not a reimplementation of it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipecat.frames.frames import TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection

import tutor_processor
from tutor_processor import (
    COMPREHENSION_RETRY_PREFIX,
    REVIEW_CORRECT,
    REVIEW_INTRO,
    REVIEW_TRY_AGAIN,
    SESSION_CLOSING_TEMPLATE,
    TRANSITION_TO_COMPREHENSION,
    TutorProcessor,
)
from voice_events import SessionClock

# claude_client/state_machine are only importable once tutor_processor's own
# top-level import has put backend/tutor on sys.path (see that module's
# docstring on the name-collision this ordering avoids) - importing them
# after `tutor_processor` above, same as tutor_processor.py itself does.
from claude_client import ComprehensionQuestion  # noqa: E402
from state_machine import TutorState  # noqa: E402

# Small, clean 5-word passage - enough to drive a full reading pass in one
# or two TranscriptionFrames without needing a long transcript.
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

# Larger passage with exactly the insertion sequence already proven correct
# in backend/tutor/tests/test_state_machine.py's
# test_insertion_count_tracks_extra_words_not_in_the_passage - reused here
# rather than invented fresh, so the insertion-vs-real-progress numbers this
# test asserts on are known-good, not hand-guessed.
INSERTION_PASSAGE = {
    "id": "test-passage",
    "grade": 1,
    "title": "Test",
    "text": "Brad likes the frog. The frog jumps. Brad claps.",
    "words": ["Brad", "likes", "the", "frog", "The", "frog", "jumps", "Brad", "claps"],
    "skills": ["consonant_blends"],
    "primary_skill": "consonant_blends",
    "comprehension_hint_topics": ["what the frog did"],
}


class FakeLLMClient:
    """Records every call instead of hitting the network - matches the same
    fake shape backend/tutor/tests/test_state_machine.py uses for
    TutorSession's four required async methods."""

    def __init__(self, questions=None, grade_results=None, completeness_results=None):
        self.hint_calls = []
        self.question_calls = []
        self.grade_calls = []
        self.completeness_calls = []
        self._questions = questions or [
            ComprehensionQuestion("Why did Pat wear the hat?", "literal_comprehension", "it was sunny"),
            ComprehensionQuestion("What did Pat do?", "literal_comprehension", "wore a big hat"),
        ]
        self._grade_results = grade_results or []
        self._completeness_results = completeness_results or []

    async def generate_hint(self, **kwargs):
        self.hint_calls.append(kwargs)
        return f"Sound it out: {kwargs['reference_word']}."

    async def generate_questions(self, **kwargs):
        self.question_calls.append(kwargs)
        return self._questions

    async def grade_answer(self, **kwargs):
        self.grade_calls.append(kwargs)
        idx = len(self.grade_calls) - 1
        if idx < len(self._grade_results):
            return self._grade_results[idx]
        return True, "Great job!"

    async def is_answer_complete(self, **kwargs):
        self.completeness_calls.append(kwargs)
        idx = len(self.completeness_calls) - 1
        if idx < len(self._completeness_results):
            return self._completeness_results[idx]
        return True


class _RecordingRTVI:
    def __init__(self):
        self.events: list[dict] = []

    async def send_server_message(self, event: dict) -> None:
        self.events.append(event)


def _make_processor(passage=None, student_id=None, llm_client=None):
    rtvi = _RecordingRTVI()
    processor = TutorProcessor(
        SessionClock(),
        passage=passage or PASSAGE,
        llm_api_key="unused-fake-key",
        student_id=student_id,
        rtvi=rtvi,
        llm_client=llm_client or FakeLLMClient(),
    )

    pushed_frames: list[tuple] = []

    async def fake_push_frame(frame, direction=FrameDirection.DOWNSTREAM):
        pushed_frames.append((frame, direction))

    processor.push_frame = fake_push_frame
    return processor, rtvi, pushed_frames


def _spoken_texts(pushed_frames) -> list[str]:
    return [frame.text for frame, _ in pushed_frames if isinstance(frame, TTSSpeakFrame)]


def _fake_word(word: str, start: float, end: float, confidence: float = 0.95):
    return SimpleNamespace(word=word, punctuated_word=None, start=start, end=end, confidence=confidence)


def _reading_frame(words: list[tuple[str, float, float]]) -> TranscriptionFrame:
    """Builds a fake Deepgram-shaped TranscriptionFrame.result carrying one
    finalized batch of words, matching what `_words_of` expects
    (`result.channel.alternatives[0].words`, each with `.word`/
    `.punctuated_word`/`.start`/`.end`/`.confidence`)."""
    fake_words = [_fake_word(w, s, e) for w, s, e in words]
    result = SimpleNamespace(channel=SimpleNamespace(alternatives=[SimpleNamespace(words=fake_words)]))
    text = " ".join(w for w, _, _ in words)
    return TranscriptionFrame(text=text, user_id="child", timestamp="t", result=result)


def _reply_frame(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="child", timestamp="t", result=None)


# ---------------------------------------------------------------------------
# _handle_reading_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_reading_turn_emits_word_recognized_and_tracks_progress():
    processor, rtvi, pushed = _make_processor()

    await processor._handle_reading_turn(_reading_frame([("Pat", 0.0, 0.3), ("has", 0.3, 0.6)]))

    word_events = [e for e in rtvi.events if e["type"] == "word_recognized"]
    assert [e["word"] for e in word_events] == ["Pat", "has"]
    for e in word_events:
        assert set(e) == {"type", "t", "word", "start_ms", "end_ms", "confidence"}
    assert word_events[0]["start_ms"] == 0
    assert word_events[0]["end_ms"] == 300

    assert processor._recognized_count == 2
    assert processor._session.state is TutorState.READING, "not finished yet - only 2 of 5 words read"
    assert not any(e["type"] == "passage_complete" for e in rtvi.events)
    assert pushed == [], "no TTS should fire mid-read"


@pytest.mark.asyncio
async def test_handle_reading_turn_finishes_and_moves_straight_to_comprehension_on_a_clean_read():
    processor, rtvi, pushed = _make_processor()

    await processor._handle_reading_turn(
        _reading_frame([("Pat", 0.0, 0.3), ("has", 0.3, 0.6), ("a", 0.6, 0.7), ("big", 0.7, 1.0), ("hat", 1.0, 1.3)])
    )

    complete_events = [e for e in rtvi.events if e["type"] == "passage_complete"]
    assert len(complete_events) == 1
    assert complete_events[0]["accuracy"] == 1.0

    # A clean read has nothing to review - start_review() returns None, so
    # this should go straight to the comprehension transition, never
    # REVIEW_INTRO/hint_spoken.
    assert not any(e["type"] == "hint_spoken" for e in rtvi.events)
    spoken = _spoken_texts(pushed)
    assert REVIEW_INTRO not in spoken
    assert TRANSITION_TO_COMPREHENSION in spoken
    assert processor._session.state is TutorState.COMPREHENSION


@pytest.mark.asyncio
async def test_handle_reading_turn_finishing_read_with_a_real_miss_starts_review_instead():
    processor, rtvi, pushed = _make_processor()

    # "hat" (index 4) misread as "cat" - a real, uncorrected substitution.
    await processor._handle_reading_turn(
        _reading_frame([("Pat", 0.0, 0.3), ("has", 0.3, 0.6), ("a", 0.6, 0.7), ("big", 0.7, 1.0), ("cat", 1.0, 1.3)])
    )

    assert any(e["type"] == "passage_complete" for e in rtvi.events)
    hint_events = [e for e in rtvi.events if e["type"] == "hint_spoken"]
    assert len(hint_events) == 1, "the one real miss should be queued and taught"

    spoken = _spoken_texts(pushed)
    assert spoken[0] == REVIEW_INTRO
    assert spoken[1] == hint_events[0]["text"]
    assert TRANSITION_TO_COMPREHENSION not in spoken, "comprehension hasn't started yet - review comes first"
    assert processor._session.state is TutorState.REVIEW


@pytest.mark.asyncio
async def test_handle_reading_turn_uses_insertion_adjusted_progress_not_raw_word_count():
    """Real bug this fix addresses (docs/BUILD_LOG.md): comparing raw
    recognized-word count against the passage's word count treats a genuine
    insertion (extra word not in the passage) as real progress, ending the
    reading turn early. Reuses the exact word sequence already proven in
    backend/tutor/tests/test_state_machine.py's
    test_insertion_count_tracks_extra_words_not_in_the_passage, driven
    through the processor this time instead of the bare TutorSession, so
    this asserts tutor_processor.py's own `effective_progress` gating
    specifically."""
    processor, rtvi, _ = _make_processor(passage=INSERTION_PASSAGE)

    # 9 real words in INSERTION_PASSAGE; two genuine "um" insertions bring
    # the raw recognized count to 11. Fed as individual batches (one
    # TranscriptionFrame per word) since that's what a real Deepgram stream
    # looks like and _handle_reading_turn accumulates across calls via
    # self._recognized_count.
    spoken = ["Brad", "likes", "um", "the", "frog", "The", "um", "frog", "jumps", "Brad", "claps"]
    t = 0.0
    finished_after_words = None
    for i, word in enumerate(spoken):
        await processor._handle_reading_turn(_reading_frame([(word, t, t + 0.3)]))
        t += 0.3
        if processor._recognized_count == len(INSERTION_PASSAGE["words"]) and finished_after_words is None:
            # This is exactly the point the OLD (buggy) raw-count comparison
            # would have ended the reading turn - two real words ("Brad",
            # "claps") plus the passage's final "jumps" haven't been spoken
            # yet, so the turn must NOT be finished here.
            finished_after_words = i + 1
            assert processor._session.state is TutorState.READING, (
                "raw recognized count reached the passage length, but real "
                "(insertion-adjusted) progress has not - must still be reading"
            )
            assert not any(e["type"] == "passage_complete" for e in rtvi.events)

    assert finished_after_words is not None, "sanity: the raw-count trigger point must actually occur mid-loop"
    # Only once every real word (plus both insertions) has actually been
    # spoken does the turn finish.
    assert processor._session.state is not TutorState.READING
    assert any(e["type"] == "passage_complete" for e in rtvi.events)


# ---------------------------------------------------------------------------
# _finish_reading (also exercised indirectly above; these check the two
# branches - review vs. no review - explicitly and in isolation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finish_reading_skips_review_and_starts_comprehension_on_a_clean_read():
    processor, rtvi, pushed = _make_processor()
    for w, s, e in [("Pat", 0.0, 0.3), ("has", 0.3, 0.6), ("a", 0.6, 0.7), ("big", 0.7, 1.0), ("hat", 1.0, 1.3)]:
        await processor._session.feed_word_recognized(
            tutor_processor.word_recognized(processor._clock, word=w, start_ms=int(s * 1000), end_ms=int(e * 1000), confidence=0.95)
        )
    processor._recognized_count = 5

    await processor._finish_reading()

    assert processor._session.state is TutorState.COMPREHENSION
    spoken = _spoken_texts(pushed)
    assert spoken == [TRANSITION_TO_COMPREHENSION, processor._session._questions[0].question]


@pytest.mark.asyncio
async def test_finish_reading_with_a_real_miss_enters_review_and_speaks_the_intro_then_the_hint():
    processor, rtvi, pushed = _make_processor()
    for w, s, e in [("Pat", 0.0, 0.3), ("has", 0.3, 0.6), ("a", 0.6, 0.7), ("big", 0.7, 1.0), ("cat", 1.0, 1.3)]:
        await processor._session.feed_word_recognized(
            tutor_processor.word_recognized(processor._clock, word=w, start_ms=int(s * 1000), end_ms=int(e * 1000), confidence=0.95)
        )
    processor._recognized_count = 5

    await processor._finish_reading()

    assert processor._session.state is TutorState.REVIEW
    teach_events = [e for e in rtvi.events if e["type"] == "hint_spoken"]
    assert len(teach_events) == 1
    assert _spoken_texts(pushed) == [REVIEW_INTRO, teach_events[0]["text"]]


# ---------------------------------------------------------------------------
# _handle_review_turn
# ---------------------------------------------------------------------------


async def _drive_to_review_with_two_misses():
    """Shared setup: read INSERTION_PASSAGE (9 reference words) with two
    real, uncorrected substitutions (idx3 frog->fog, idx6 jumps->hops) and
    nothing else - a clean 1-for-1 word count against the reference, so
    tutor_processor's own automatic "finished reading" trigger (raw
    recognized count, insertion-adjusted) fires at exactly the right point
    with no false-start/self-correction complications to also account for
    (that interaction is exercised separately at the TutorSession level in
    backend/tutor/tests/test_state_machine.py)."""
    processor, rtvi, pushed = _make_processor(passage=INSERTION_PASSAGE)
    words = ["Brad", "likes", "the", "fog", "The", "frog", "hops", "Brad", "claps"]
    t = 0.0
    for word in words:
        await processor._handle_reading_turn(_reading_frame([(word, t, t + 0.3)]))
        t += 0.3
    assert processor._session.state is TutorState.REVIEW
    assert processor._session._review_queue == [3, 6]
    return processor, rtvi, pushed


@pytest.mark.asyncio
async def test_handle_review_turn_correct_reply_advances_to_the_next_review_word():
    processor, rtvi, pushed = await _drive_to_review_with_two_misses()
    pushed.clear()
    rtvi.events.clear()

    await processor._handle_review_turn(_reply_frame("frog"))

    result_events = [e for e in rtvi.events if e["type"] == "review_word_result"]
    assert len(result_events) == 1
    assert result_events[0]["reference_index"] == 3
    assert result_events[0]["reference_word"] == "frog"
    assert result_events[0]["correct"] is True

    hint_events = [e for e in rtvi.events if e["type"] == "hint_spoken"]
    assert len(hint_events) == 1, "one more review word (idx6) still queued"
    assert _spoken_texts(pushed) == [REVIEW_CORRECT, hint_events[0]["text"]]
    assert processor._session.state is TutorState.REVIEW


@pytest.mark.asyncio
async def test_handle_review_turn_incorrect_reply_says_try_again_but_still_advances():
    processor, rtvi, pushed = await _drive_to_review_with_two_misses()
    pushed.clear()
    rtvi.events.clear()

    await processor._handle_review_turn(_reply_frame("not frog"))

    result_events = [e for e in rtvi.events if e["type"] == "review_word_result"]
    assert result_events[0]["correct"] is False
    assert _spoken_texts(pushed)[0] == REVIEW_TRY_AGAIN
    assert processor._session.state is TutorState.REVIEW


@pytest.mark.asyncio
async def test_handle_review_turn_last_word_transitions_to_comprehension():
    processor, rtvi, pushed = await _drive_to_review_with_two_misses()
    await processor._handle_review_turn(_reply_frame("frog"))  # first of two, still REVIEW
    pushed.clear()
    rtvi.events.clear()

    await processor._handle_review_turn(_reply_frame("hops"))  # second/last -> review complete

    assert not any(e["type"] == "hint_spoken" for e in rtvi.events), "no more words to teach"
    spoken = _spoken_texts(pushed)
    assert spoken[0] == REVIEW_TRY_AGAIN  # "hops" != "jumps"
    assert TRANSITION_TO_COMPREHENSION in spoken
    assert processor._session.state is TutorState.COMPREHENSION


@pytest.mark.asyncio
async def test_handle_review_turn_ignores_an_empty_reply():
    processor, rtvi, pushed = await _drive_to_review_with_two_misses()
    pushed.clear()
    rtvi.events.clear()

    await processor._handle_review_turn(_reply_frame("   "))

    assert rtvi.events == []
    assert pushed == []
    assert processor._session.state is TutorState.REVIEW, "still waiting on a real reply"


# ---------------------------------------------------------------------------
# _handle_comprehension_turn
# ---------------------------------------------------------------------------


async def _drive_to_comprehension(llm_client=None):
    processor, rtvi, pushed = _make_processor(llm_client=llm_client)
    for w, s, e in [("Pat", 0.0, 0.3), ("has", 0.3, 0.6), ("a", 0.6, 0.7), ("big", 0.7, 1.0), ("hat", 1.0, 1.3)]:
        await processor._handle_reading_turn(_reading_frame([(w, s, e)]))
    assert processor._session.state is TutorState.COMPREHENSION
    return processor, rtvi, pushed


@pytest.mark.asyncio
async def test_handle_comprehension_turn_pause_mid_answer_says_and_emits_nothing():
    llm = FakeLLMClient(completeness_results=[False])
    processor, rtvi, pushed = await _drive_to_comprehension(llm_client=llm)
    rtvi.events.clear()
    pushed.clear()

    await processor._handle_comprehension_turn(_reply_frame("because"))

    assert rtvi.events == [], "a pause mid-answer must not be graded or emitted yet"
    assert pushed == []
    assert processor._session.state is TutorState.COMPREHENSION


@pytest.mark.asyncio
async def test_handle_comprehension_turn_correct_answer_advances_to_next_question():
    llm = FakeLLMClient(grade_results=[(True, "Nice job!")])
    processor, rtvi, pushed = await _drive_to_comprehension(llm_client=llm)
    rtvi.events.clear()
    pushed.clear()

    await processor._handle_comprehension_turn(_reply_frame("it was sunny"))

    turn_events = [e for e in rtvi.events if e["type"] == "comprehension_turn"]
    assert len(turn_events) == 1
    event = turn_events[0]
    assert event["question"] == "Why did Pat wear the hat?"
    assert event["answer_given"] == "it was sunny"
    assert event["correct"] is True
    assert event["feedback_text"] == "Nice job!"

    spoken = _spoken_texts(pushed)
    assert spoken == ["Nice job!", "What did Pat do?"]
    assert processor._session.state is TutorState.COMPREHENSION


@pytest.mark.asyncio
async def test_handle_comprehension_turn_wrong_first_answer_retries_same_question():
    llm = FakeLLMClient(grade_results=[(False, "Check again.")])
    processor, rtvi, pushed = await _drive_to_comprehension(llm_client=llm)
    rtvi.events.clear()
    pushed.clear()

    await processor._handle_comprehension_turn(_reply_frame("I don't know"))

    event = next(e for e in rtvi.events if e["type"] == "comprehension_turn")
    assert event["correct"] is False
    spoken = _spoken_texts(pushed)
    assert spoken[0] == "Check again."
    assert spoken[1] == COMPREHENSION_RETRY_PREFIX + "Why did Pat wear the hat?"
    assert processor._session.state is TutorState.COMPREHENSION


@pytest.mark.asyncio
async def test_handle_comprehension_turn_last_question_finishes_the_session():
    llm = FakeLLMClient(
        questions=[ComprehensionQuestion("Only question?", "literal_comprehension", "yes")],
        grade_results=[(True, "Great!")],
    )
    processor, rtvi, pushed = await _drive_to_comprehension(llm_client=llm)
    rtvi.events.clear()
    pushed.clear()

    await processor._handle_comprehension_turn(_reply_frame("yes"))

    assert processor._session.state is TutorState.DONE
    spoken = _spoken_texts(pushed)
    assert spoken[0] == "Great!"
    closing_text = SESSION_CLOSING_TEMPLATE.format(title=PASSAGE["title"])
    assert closing_text in spoken, "_finish_session must have been reached"
    ended_events = [e for e in rtvi.events if e["type"] == "session_ended"]
    assert len(ended_events) == 1


@pytest.mark.asyncio
async def test_handle_comprehension_turn_ignores_an_empty_fragment():
    processor, rtvi, pushed = await _drive_to_comprehension()
    rtvi.events.clear()
    pushed.clear()

    await processor._handle_comprehension_turn(_reply_frame(""))

    assert rtvi.events == []
    assert pushed == []


# ---------------------------------------------------------------------------
# _finish_session - the exact bug this audit found: session_ended's shape.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finish_session_emits_session_ended_after_posting_with_real_id_and_full_shape(monkeypatch):
    processor, rtvi, pushed = _make_processor(student_id="student-42")
    processor._session.llm_client.llm_ms = lambda: 250.0
    processor._stt_delay_samples_ms = [40.0, 60.0]  # median 50.0

    call_order = []
    captured_call = {}

    async def fake_post_completed_session(*, student_id, passage_id, session_columns):
        call_order.append("post_completed_session")
        captured_call["student_id"] = student_id
        captured_call["passage_id"] = passage_id
        captured_call["session_columns"] = session_columns
        return "real-session-id-999"

    monkeypatch.setattr(tutor_processor, "post_completed_session", fake_post_completed_session)

    original_send = rtvi.send_server_message

    async def recording_send(event):
        if event["type"] == "session_ended":
            call_order.append("session_ended_emitted")
        await original_send(event)

    rtvi.send_server_message = recording_send

    await processor._finish_session()

    # session_ended must be emitted AFTER post_completed_session returns -
    # this ordering is the actual fix: session_id doesn't exist until the
    # POST succeeds.
    assert call_order == ["post_completed_session", "session_ended_emitted"]

    assert captured_call["student_id"] == "student-42"
    assert captured_call["passage_id"] == "g1-short-vowels-001"
    assert captured_call["session_columns"]["pipeline_latency_ms"]["llm_ms"] == 250.0

    ended = next(e for e in rtvi.events if e["type"] == "session_ended")
    assert ended["session_id"] == "real-session-id-999"
    assert ended["passage_id"] == "g1-short-vowels-001"
    assert ended["pipeline_latency_ms"]["stt_ms"] == 50.0
    assert ended["pipeline_latency_ms"]["llm_ms"] == 250.0
    assert set(ended) == {"type", "t", "session_id", "passage_id", "pipeline_latency_ms"}

    # The closing line was still spoken - the mastery POST doesn't block
    # what the child actually hears.
    closing_text = SESSION_CLOSING_TEMPLATE.format(title=PASSAGE["title"])
    assert _spoken_texts(pushed)[0] == closing_text


@pytest.mark.asyncio
async def test_finish_session_without_a_student_id_never_calls_mastery_and_sends_no_session_id(monkeypatch):
    processor, rtvi, pushed = _make_processor(student_id=None)

    async def fail_if_called(**kwargs):
        raise AssertionError("post_completed_session must not be called without a student_id")

    monkeypatch.setattr(tutor_processor, "post_completed_session", fail_if_called)

    await processor._finish_session()

    ended = next(e for e in rtvi.events if e["type"] == "session_ended")
    assert ended["session_id"] is None
    assert ended["passage_id"] == "g1-short-vowels-001"


@pytest.mark.asyncio
async def test_finish_session_when_mastery_post_fails_sends_null_session_id_without_crashing(monkeypatch):
    """mastery_client.post_completed_session is itself best-effort and
    returns None on any failure (timeout, connection error, non-2xx) rather
    than raising - _finish_session must pass that through as session_id:
    None rather than blocking indefinitely or crashing the pipeline over a
    bookkeeping call after the child's session is already over."""
    processor, rtvi, pushed = _make_processor(student_id="student-42")

    async def fake_post_completed_session_failure(*, student_id, passage_id, session_columns):
        return None  # mastery_client's own documented failure return

    monkeypatch.setattr(tutor_processor, "post_completed_session", fake_post_completed_session_failure)

    await processor._finish_session()  # must not raise

    ended = next(e for e in rtvi.events if e["type"] == "session_ended")
    assert ended["session_id"] is None
    assert ended["passage_id"] == "g1-short-vowels-001"
