"""Unit tests for the tutor state machine (state_machine.py) using a fake
LLM client - zero real API calls. These exercise the control flow (live
miscue tracking, the end-of-passage review pass, state transitions,
comprehension turn sequencing) that the alignment tests don't cover, since
that logic lives above the deterministic engine.
"""

import pytest

from claude_client import ComprehensionQuestion
from state_machine import TutorSession, TutorState


class FakeLLMClient:
    """Records every call it receives instead of hitting the network, so
    tests can assert both the state machine's decisions (did it call at
    all, with what args) and its handling of the (canned) response.
    """

    def __init__(self, questions=None, grade_results=None, completeness_results=None):
        self.hint_calls = []
        self.question_calls = []
        self.grade_calls = []
        self.completeness_calls = []
        self._questions = questions or [
            ComprehensionQuestion("Why did the frog jump?", "cause_and_effect", "Brad clapped"),
            ComprehensionQuestion("What did Brad do at the end?", "literal_comprehension", "ran home"),
        ]
        self._grade_results = grade_results or []
        # Defaults to always-complete so existing tests that never call
        # hear_partial_answer (they call submit_answer directly) are
        # unaffected - only tests that actually exercise the fragment
        # accumulation need to pass real canned results here.
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


PASSAGE = {
    "id": "test-passage",
    "grade": 1,
    "title": "Test",
    "text": "Brad likes the frog. The frog jumps. Brad claps.",
    "words": ["Brad", "likes", "the", "frog", "The", "frog", "jumps", "Brad", "claps"],
    "skills": ["consonant_blends"],
    "primary_skill": "consonant_blends",
    "comprehension_hint_topics": ["what the frog did"],
}


def _word_event(word: str, t: int) -> dict:
    return {"type": "word_recognized", "t": t, "word": word, "start_ms": t - 100, "end_ms": t, "confidence": 0.9}


@pytest.mark.asyncio
async def test_perfect_read_produces_no_events():
    llm = FakeLLMClient()
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    all_events = []
    for i, word in enumerate(PASSAGE["words"]):
        all_events.extend(await session.feed_word_recognized(_word_event(word, (i + 1) * 500)))
    assert all_events == []
    assert llm.hint_calls == []


@pytest.mark.asyncio
async def test_substitution_produces_a_live_miscue_but_no_live_hint():
    # A stumble still highlights live (the frontend's word-by-word tracking
    # depends on this) - it's only the spoken hint that moved to the
    # end-of-passage review, see test_review_teaches_each_missed_word_after_
    # the_full_passage above for that half of the behavior.
    llm = FakeLLMClient()
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    words = ["Brad", "likes", "the", "fog"]  # "frog" (idx 3) misread as "fog"
    events = []
    for i, word in enumerate(words):
        events.extend(await session.feed_word_recognized(_word_event(word, (i + 1) * 500)))
        # the next real word confirms "fog" wasn't a false start (no self-correction)
        events.extend(await session.feed_word_recognized(_word_event("The", 5000)))

    types = [e["type"] for e in events]
    assert "miscue_detected" in types
    assert "hint_spoken" not in types
    assert llm.hint_calls == []

    frog_miscue = next(e for e in events if e["type"] == "miscue_detected" and e["reference_index"] == 3)
    assert frog_miscue["miscue_type"] != "self_correction"  # a real, unaddressed miscue
    assert frog_miscue["reference_word"] == "frog"


@pytest.mark.asyncio
async def test_self_correction_does_not_trigger_a_hint():
    llm = FakeLLMClient()
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    # child says "fog", catches themselves, says "frog", then reads the rest
    # of the passage correctly - should fold into self_correction and never
    # call the hint LLM at all. (Reads to the end rather than stopping right
    # after the correction so the alignment isn't left holding a big
    # trailing "unread tail" against a passage that repeats "frog"/"The" -
    # edit-distance alignment can otherwise find an equal-cost but
    # unintuitive match against the *other* occurrence when most of a
    # short, repetitive passage is still unspoken; see alignment.py's
    # module docstring on repeated-word ambiguity.)
    words = ["Brad", "likes", "the", "fog", "frog", "The", "frog", "jumps", "Brad", "claps"]
    events = []
    for i, word in enumerate(words):
        events.extend(await session.feed_word_recognized(_word_event(word, (i + 1) * 500)))

    assert llm.hint_calls == []
    miscue_events = [e for e in events if e["type"] == "miscue_detected"]
    assert any(e["miscue_type"] == "self_correction" for e in miscue_events)
    assert not any(e["miscue_type"] == "substitution" for e in miscue_events)


@pytest.mark.asyncio
async def test_review_teaches_each_missed_word_after_the_full_passage():
    # Real feedback from a real reading session: the old behavior interjected
    # a hint mid-read; now nothing is spoken until the whole passage is done,
    # then every real, uncorrected stumble is taught one at a time. Two real
    # mistakes here, one self-correction (which shouldn't need review - the
    # child already caught it themselves).
    llm = FakeLLMClient()
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    # idx3 "frog"->"fog" (real miss), idx6 "jumps"->"hops" (real miss, no
    # cooldown concept anymore - both must be taught), idx7 "Brad" said as
    # "Brod" then corrected to "Brad" (self-correction, no review needed).
    words = ["Brad", "likes", "the", "fog", "The", "frog", "hops", "Brod", "Brad", "claps"]
    for i, word in enumerate(words):
        events = await session.feed_word_recognized(_word_event(word, (i + 1) * 500))
        assert all(e["type"] != "hint_spoken" for e in events), "no hint may fire during reading"
        assert llm.hint_calls == [], "no LLM call may happen during reading"

    session.finish_passage(now_t=6000)
    assert session._review_queue == [3, 6]  # reference order, self-correction excluded

    first_teach = await session.start_review()
    assert session.state is TutorState.REVIEW
    assert first_teach["type"] == "hint_spoken"
    assert llm.hint_calls[0]["reference_word"] == "frog"

    result1, second_teach = await session.submit_review_reply("frog", now_t=6100)
    assert result1["type"] == "review_word_result"
    assert result1["reference_index"] == 3
    assert result1["correct"] is True
    assert second_teach is not None
    assert llm.hint_calls[1]["reference_word"] == "jumps"
    assert session.state is TutorState.REVIEW  # still one more to go

    result2, third_teach = await session.submit_review_reply("hops", now_t=6200)
    assert result2["reference_index"] == 6
    assert result2["correct"] is False  # "hops" still isn't "jumps"
    assert third_teach is None  # review is over
    assert session.state is TutorState.PASSAGE_DONE  # ready for start_comprehension, same as a clean read

    columns = session.to_session_columns()
    assert columns["hints_delayed_count"] == 2  # two words queued for review
    assert columns["hints_delayed_self_corrected_count"] == 1  # only the first was said correctly on retry


@pytest.mark.asyncio
async def test_review_is_skipped_entirely_on_a_clean_read():
    llm = FakeLLMClient()
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    for i, word in enumerate(PASSAGE["words"]):
        await session.feed_word_recognized(_word_event(word, (i + 1) * 500))
    session.finish_passage(now_t=5000)

    teach = await session.start_review()
    assert teach is None
    assert llm.hint_calls == []
    assert session.state is TutorState.PASSAGE_DONE  # never entered REVIEW at all
    columns = session.to_session_columns()
    assert columns["hints_delayed_count"] == 0


@pytest.mark.asyncio
async def test_finish_passage_computes_wcpm_and_transitions_state():
    llm = FakeLLMClient()
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    for i, word in enumerate(PASSAGE["words"]):
        await session.feed_word_recognized(
            {
                "type": "word_recognized",
                "t": (i + 1) * 500,
                "word": word,
                "start_ms": i * 500,
                "end_ms": (i + 1) * 500,
                "confidence": 0.9,
            }
        )
    event = session.finish_passage(now_t=5000)
    assert event["type"] == "passage_complete"
    assert event["accuracy"] == 1.0
    assert event["wcpm"] > 0
    assert session.state is TutorState.PASSAGE_DONE

    with pytest.raises(RuntimeError):
        await session.feed_word_recognized(_word_event("extra", 6000))


@pytest.mark.asyncio
async def test_comprehension_flow_asks_questions_grounded_in_passage_and_grades_answers():
    # Real, explicit request: a wrong answer gets exactly one retry (the
    # SAME question repeated) before moving on - see submit_answer's
    # docstring. This scenario's last question is wrong on the first try,
    # then correct on the retry, so it should finalize as correct and end
    # the session with exactly 2 graded turns (one per QUESTION, never one
    # per attempt), not 3.
    llm = FakeLLMClient(
        grade_results=[(True, "Nice!"), (False, "Check the text again."), (True, "Great job!")]
    )
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    for i, word in enumerate(PASSAGE["words"]):
        await session.feed_word_recognized(_word_event(word, (i + 1) * 500))
    session.finish_passage(now_t=5000)

    first_question = await session.start_comprehension()
    assert session.state is TutorState.COMPREHENSION
    assert llm.question_calls[0]["passage_text"] == PASSAGE["text"]
    assert first_question == "Why did the frog jump?"

    event1, next_q, is_retry1 = await session.submit_answer("because Brad clapped", now_t=6000)
    assert event1["type"] == "comprehension_turn"
    assert event1["correct"] is True
    assert next_q == "What did Brad do at the end?"
    assert is_retry1 is False
    assert session.state is TutorState.COMPREHENSION

    event2, next_q2, is_retry2 = await session.submit_answer("I don't know", now_t=7000)
    assert event2["correct"] is False
    assert is_retry2 is True
    assert next_q2 == "What did Brad do at the end?", "a wrong first attempt repeats the SAME question"
    assert session.state is TutorState.COMPREHENSION, "one retry - not finished yet"

    event3, next_q3, is_retry3 = await session.submit_answer("he ran home", now_t=7500)
    assert event3["correct"] is True
    assert is_retry3 is False
    assert next_q3 is None
    assert session.state is TutorState.DONE

    columns = session.to_session_columns()
    assert len(columns["comprehension"]) == 2, "one graded turn per QUESTION, not per attempt"
    assert columns["comprehension"][0]["correct"] is True
    assert columns["comprehension"][1]["correct"] is True, "finalized using the retry's outcome"
    assert columns["comprehension"][1]["answer_given"] == "he ran home", "the retry's answer, not the first"
    assert columns["wcpm"] is not None
    assert columns["accuracy"] == 1.0


@pytest.mark.asyncio
async def test_comprehension_second_wrong_attempt_moves_on_instead_of_retrying_again():
    # The one-retry rule is exactly one retry: still wrong after the retry
    # moves on (or ends the session) anyway, rather than looping forever.
    llm = FakeLLMClient(
        grade_results=[(True, "Nice!"), (False, "Check the text again."), (False, "Still not quite.")]
    )
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    for i, word in enumerate(PASSAGE["words"]):
        await session.feed_word_recognized(_word_event(word, (i + 1) * 500))
    session.finish_passage(now_t=5000)
    await session.start_comprehension()

    await session.submit_answer("because Brad clapped", now_t=6000)
    event2, next_q2, is_retry2 = await session.submit_answer("I don't know", now_t=7000)
    assert is_retry2 is True

    event3, next_q3, is_retry3 = await session.submit_answer("still don't know", now_t=7500)
    assert event3["correct"] is False
    assert is_retry3 is False
    assert next_q3 is None, "second wrong attempt on the last question ends the session anyway"
    assert session.state is TutorState.DONE

    columns = session.to_session_columns()
    assert len(columns["comprehension"]) == 2
    assert columns["comprehension"][1]["correct"] is False
    assert columns["comprehension"][1]["answer_given"] == "still don't know"


@pytest.mark.asyncio
async def test_hear_partial_answer_waits_through_a_thinking_pause_before_grading():
    # Real, explicit request: a fixed silence timeout can't tell "the child
    # is done" from "the child paused to think" - this age group pauses to
    # think a lot. Deepgram finalizes one fragment per pause, so a real
    # paused-then-continued answer arrives as two separate fragments here.
    # The first fragment alone ("because") should NOT be graded yet.
    llm = FakeLLMClient(
        grade_results=[(True, "Nice!")],
        completeness_results=[False, True],  # "because" -> incomplete, full answer -> complete
    )
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    for i, word in enumerate(PASSAGE["words"]):
        await session.feed_word_recognized(_word_event(word, (i + 1) * 500))
    session.finish_passage(now_t=5000)
    await session.start_comprehension()

    result1 = await session.hear_partial_answer("because", now_t=6000)
    assert result1 is None, "a fragment judged incomplete must not be graded yet"
    assert len(llm.grade_calls) == 0, "no grading call should happen while still judged incomplete"
    assert session.state is TutorState.COMPREHENSION, "still waiting, not finished"

    result2 = await session.hear_partial_answer("Brad clapped", now_t=6800)
    assert result2 is not None
    event, next_q, is_retry = result2
    assert event["correct"] is True
    assert event["answer_given"] == "because Brad clapped", "fragments joined into one full answer"
    assert next_q == "What did Brad do at the end?"

    # Exactly one graded turn was recorded - the accumulated answer, not
    # two separate half-answers.
    columns = session.to_session_columns()
    assert len(columns["comprehension"]) == 1
    assert columns["comprehension"][0]["answer_given"] == "because Brad clapped"


@pytest.mark.asyncio
async def test_hear_partial_answer_force_submits_after_the_fragment_cap_even_if_never_judged_complete():
    # Safety net: if is_answer_complete somehow never returns True (a
    # genuinely rambling answer, or a run of parse failures upstream), the
    # session must not hang forever waiting for a verdict that never comes.
    llm = FakeLLMClient(
        grade_results=[(True, "Nice!")],
        completeness_results=[False, False, False, False],  # never says complete on its own
    )
    session = TutorSession(passage=PASSAGE, llm_client=llm)
    for i, word in enumerate(PASSAGE["words"]):
        await session.feed_word_recognized(_word_event(word, (i + 1) * 500))
    session.finish_passage(now_t=5000)
    await session.start_comprehension()

    result = None
    for i in range(4):
        result = await session.hear_partial_answer(f"word{i}", now_t=6000 + i * 500)
        if i < 3:
            assert result is None, f"fragment {i + 1} should still be waiting, cap not yet hit"

    assert result is not None, "the fragment cap should force a decision on the 4th fragment"
    assert len(llm.completeness_calls) == 3, (
        "the 4th fragment force-submits without ever calling is_answer_complete again"
    )
    event, _next_q, _is_retry = result
    assert event["answer_given"] == "word0 word1 word2 word3"
