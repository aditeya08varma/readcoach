"""The tutor state machine: watches the live miscue stream during reading
for visual tracking only, runs an end-of-passage review of every real
stumble, then runs the comprehension question/grade turn.

Owned by `tutor-logic-engineer`. Deliberately a plain Python class with
explicit states and `if`/control-flow branching, not an agent framework -
per this agent's role brief, latency and debuggability matter more here
than framework sophistication, and every decision (which word to teach
next, which question next) needs to be traceable in a debugger during the
hackathon demo without stepping through a planner.

States
------
READING        - words are streaming in via `feed_word_recognized`.
PASSAGE_DONE   - `finish_passage()` called; wcpm/accuracy finalized.
REVIEW         - teaching each real stumble one at a time, see start_review.
COMPREHENSION  - questions generated, working through them one at a time.
DONE           - all comprehension turns graded.

This module owns *when* to call the LLM and *what* to persist; it does not
own mic capture, STT, or TTS playback (voice-pipeline-engineer), and does
not compute mastery weights or pick the next passage (mastery-engineer) -
it only produces the raw miscue/comprehension signal and the event types
`contracts/voice_events.md` assigns to this agent.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import events as tutor_events
from alignment import AlignmentResult, Miscue, MiscueType, _closely_matches, align, compute_wcpm_and_accuracy
from claude_client import ComprehensionQuestion, TutorLLMClient
from skills import load_taxonomy

# Real feedback from a real reading session, not a guess: spoken hints
# firing mid-read (immediately, or after a short mastery-aware delay) read
# as constant interruption rather than help - a stumble on "boat" or
# "paddled" got talked over before the child had even finished the
# sentence. The mastery-aware pacing constants that used to live here
# (HINT_COOLDOWN_WORDS, HINT_MASTERY_THRESHOLD, HINT_DELAY_WORDS_STRONG_SKILL)
# are gone, not tuned - the whole live-hint mechanism they paced is gone too.
# See REVIEW below: every real stumble is now taught in one pass after the
# whole passage is read, with the child asked to say the word again to
# confirm, before comprehension questions start. mastery_weights is kept on
# TutorSession below only because tutor_processor.py already threads it
# through from a real mastery lookup - not used for pacing decisions anymore.

# How many words of lookahead past a candidate miscue's reference_index to
# wait for before treating it as "settled" (see feed_word_recognized). Must
# be at least 1 to give false-start self-correction folding a chance.
SETTLE_LOOKAHEAD = 2

# Real bug found from a real recording, reproduced directly against a real
# passage (see docs/BUILD_LOG.md): feed_word_recognized used to re-align the
# words spoken *so far* against the *entire* rest of the passage, every
# time. alignment.py's own docstring already flags that a huge unread tail
# can make the DP's cheapest path a tie between matching a word to the
# nearby, intuitive occurrence versus a much later repeated one - and
# calling it "rare" turned out to be wrong for exactly the content this
# runs on: a children's story that opens "Dean and his team..." and later
# reuses "Dean and his team..." verbatim gives the DP a tie on "Dean",
# "and", AND "his" simultaneously, at the very first word of the passage,
# on a perfectly correct read. Bounding how far into the reference the
# incremental aligner is even allowed to look removes that huge tail
# entirely, rather than trying to out-guess the DP's tie-breaking. Only
# used for the live/incremental path below - finish_passage still aligns
# against the true full reference for the final, authoritative score.
INCREMENTAL_REFERENCE_WINDOW = SETTLE_LOOKAHEAD + 5

# Real, explicit request (see docs/BUILD_LOG.md): a fixed silence timeout
# can't distinguish "the child finished their answer" from "the child
# paused to think," and this age group pauses to think a lot. Deepgram
# already finalizes one transcript per natural pause on its own, so a real
# spoken answer with a thinking-pause in the middle arrives here as several
# separate TranscriptionFrames, not one. hear_partial_answer accumulates
# those fragments and asks the LLM (claude_client.TutorLLMClient.
# is_answer_complete) whether the accumulated text is actually finished
# before committing to grade it - this cap is the safety net in case that
# judgment somehow never returns "complete" (a genuinely rambling answer,
# or a run of parse failures), so a session can't hang forever waiting.
MAX_ANSWER_FRAGMENTS_BEFORE_FORCE_SUBMIT = 4

_SKILL_LABELS = {entry["id"]: entry["label"] for entry in load_taxonomy()}


class TutorState(str, Enum):
    READING = "reading"
    PASSAGE_DONE = "passage_done"
    REVIEW = "review"
    COMPREHENSION = "comprehension"
    DONE = "done"


@dataclass
class GradedTurn:
    question: str
    answer_given: str
    correct: bool
    skill_id: str


@dataclass
class TutorSession:
    """One child's pass through one passage.

    `passage` is a dict matching `contracts/passage_schema.json`.
    `llm_client` must implement `TutorLLMClient`'s four async methods
    (generate_hint, generate_questions, grade_answer, is_answer_complete) -
    tests pass a fake to exercise every branch with zero API calls. Any
    wrapper around a real TutorLLMClient (e.g. backend/voice/
    latency_observer.py's TimingLLMClient) must forward all four - a
    wrapper missing one fails at the exact moment that method is first
    needed, not at construction time (a real bug found and fixed this way:
    see docs/BUILD_LOG.md).
    """

    passage: dict
    llm_client: TutorLLMClient
    # Optional: {skill_id: weight (0..1)}, the student's current mastery
    # vector at session start (see backend/voice/mastery_client.py's
    # fetch_mastery_vector). No longer used for hint pacing (see the module
    # docstring above REVIEW's constants) - kept on the signature only
    # because tutor_processor.py already threads a real lookup through here.
    mastery_weights: dict[str, float] | None = None
    state: TutorState = field(default=TutorState.READING, init=False)

    _recognized_events: list[dict] = field(default_factory=list, init=False)
    # reference_index -> the Miscue last emitted for that index, so we only
    # re-emit when realignment changes its classification (e.g. a plain
    # substitution later folds into a self_correction once the retry comes in).
    # Purely for live visual tracking now (the frontend's word-by-word
    # highlight) - no hint ever fires off of this anymore, see REVIEW below.
    _settled_miscues: dict[int, Miscue] = field(default_factory=dict, init=False)
    # Reference indices needing end-of-passage review (real, uncorrected
    # substitutions/omissions - never self-corrections, which already show
    # the child caught it themselves), built once in finish_passage, walked
    # one at a time by start_review/submit_review_reply.
    _review_queue: list[int] = field(default_factory=list, init=False)
    _review_cursor: int = field(default=0, init=False)
    # Repurposed from the old mastery-pacing feature these numbers used to
    # track (same to_session_columns()/contract fields, no schema change
    # needed): now "how many words got queued for the end-of-passage review"
    # and "how many the child got right when asked to say it again."
    _hints_delayed_count: int = field(default=0, init=False)
    _hints_delayed_self_corrected_count: int = field(default=0, init=False)

    _final_result: AlignmentResult | None = field(default=None, init=False)
    _questions: list[ComprehensionQuestion] = field(default_factory=list, init=False)
    # True once the CURRENT question has already been given one retry - a
    # second wrong answer moves on regardless, so this never grants more
    # than one extra chance per question. Reset whenever the cursor
    # actually advances to a new question.
    _question_retry_used: bool = field(default=False, init=False)
    # Raw transcript fragments for the answer currently being spoken, one
    # per Deepgram-finalized chunk (see hear_partial_answer) - joined and
    # re-judged for completeness after every new fragment, cleared the
    # moment an accumulated answer is actually committed via submit_answer.
    _pending_answer_fragments: list[str] = field(default_factory=list, init=False)
    _question_cursor: int = field(default=0, init=False)
    _graded_turns: list[GradedTurn] = field(default_factory=list, init=False)

    @property
    def reference_words(self) -> list[str]:
        return self.passage["words"]

    # ---------------------------------------------------------------- reading

    async def feed_word_recognized(self, event: dict) -> list[dict]:
        """Ingest one `word_recognized` event (contracts/voice_events.md).

        Re-runs the deterministic alignment engine over every word seen so
        far and figures out which reference-indexed miscues are now
        "settled" (confidently won't change classification as more words
        arrive), emitting `miscue_detected` for any that are new. Purely
        visual/live-tracking now - see the module docstring above REVIEW's
        constants for why no hint is ever spoken from in here anymore.
        Every real stumble is taught in one pass after the whole passage is
        read (see finish_passage/start_review below), not interrupted
        mid-sentence.

        Why "settled" needs a lookahead window at all: re-aligning the
        *entire* reference array against only the words spoken *so far*
        would otherwise report every not-yet-read reference word as an
        omission (the DP has no way to know "hasn't happened yet" from
        "was skipped" - both look identical until more words arrive). A
        miscue at `reference_index` is only trusted once at least
        `SETTLE_LOOKAHEAD` more words have been recognized past it, which
        also happens to be exactly the lookahead `_fold_self_corrections`
        needs to catch a false-start-then-retry.

        Returns the list of events to forward over the voice data channel
        (possibly empty).
        """
        if self.state is not TutorState.READING:
            raise RuntimeError(f"feed_word_recognized called in state {self.state}")

        self._recognized_events.append(event)
        window_end = len(self._recognized_events) + INCREMENTAL_REFERENCE_WINDOW
        # This re-runs on every single recognized word, and the DP itself is
        # a plain synchronous function - called in-line it would block this
        # process's one event loop for its duration, stalling every other
        # concurrent session's audio pipeline while it runs (see
        # docs/BUILD_LOG.md). Passage lengths here keep any one call tiny in
        # isolation, but "tiny, every word, on the loop every other session
        # also depends on" is still a real cost worth not paying - a thread
        # pool call costs one thread hop instead.
        result = await asyncio.to_thread(
            _align_current, self.reference_words[:window_end], self._recognized_events
        )
        settle_cutoff = len(self._recognized_events) - SETTLE_LOOKAHEAD

        out_events: list[dict] = []
        for miscue in result.miscues:
            if miscue.reference_index is None:
                continue  # bare insertions carry no reference index to key off of
            if miscue.reference_index >= settle_cutoff:
                continue  # too close to the reading frontier, could still change
            prior = self._settled_miscues.get(miscue.reference_index)
            if prior is not None and prior.miscue_type == miscue.miscue_type and prior.spoken_word == miscue.spoken_word:
                continue  # unchanged since last time, don't re-emit
            miscue.t = event["t"]
            self._settled_miscues[miscue.reference_index] = miscue
            out_events.append(miscue.to_event())

        return out_events

    async def _teach_word(self, miscue: Miscue, *, now_t: int) -> dict:
        """Fast-tier call: explain one missed word. Used only during REVIEW
        now (see start_review/submit_review_reply) - reuses the same
        `hint_spoken` event shape the old mid-read hint used, so the
        frontend's existing coach-bubble UI needs no changes to show it."""
        skill_id = miscue.skill_id or "short_vowels"
        text = await self.llm_client.generate_hint(
            reference_word=miscue.reference_word,
            spoken_word=miscue.spoken_word or "",
            skill_id=skill_id,
            skill_label=_SKILL_LABELS.get(skill_id, skill_id),
        )
        return tutor_events.hint_spoken(t=now_t, skill_id=skill_id, text=text)

    def finish_passage(self, *, now_t: int) -> dict:
        """Child finished reading (silence timeout or explicit "done" turn
        signal, per contracts/voice_events.md). Finalizes the alignment -
        with the full stream in hand there's no more lookahead ambiguity, so
        this re-settles anything still pending - and returns `passage_complete`.
        """
        if self.state is not TutorState.READING:
            raise RuntimeError(f"finish_passage called in state {self.state}")

        result = _align_current(self.reference_words, self._recognized_events)
        if self._recognized_events:
            elapsed_ms = (
                self._recognized_events[-1]["end_ms"] - self._recognized_events[0]["start_ms"]
            )
        else:
            elapsed_ms = 0
        compute_wcpm_and_accuracy(result, elapsed_ms)

        # Backfill `t` from whatever was already live-settled (see
        # feed_word_recognized) so persisted miscues keep their real
        # timestamp; anything that only settled here (the tail words the
        # lookahead window held back) gets this final moment's timestamp as
        # a reasonable best-effort stand-in.
        for miscue in result.miscues:
            if miscue.reference_index is not None:
                prior = self._settled_miscues.get(miscue.reference_index)
                miscue.t = prior.t if prior is not None else now_t
        self._final_result = result
        self.state = TutorState.PASSAGE_DONE

        # Real, uncorrected stumbles to teach in the review pass below - not
        # self-corrections (the child already caught those themselves) and
        # not bare insertions (no reference word to teach). Reference order,
        # so the review walks the passage the same direction it was read.
        self._review_queue = sorted(
            m.reference_index
            for m in result.miscues
            if m.reference_index is not None and m.miscue_type in (MiscueType.SUBSTITUTION, MiscueType.OMISSION)
        )
        self._hints_delayed_count = len(self._review_queue)

        return tutor_events.passage_complete(
            t=now_t,
            wcpm=result.wcpm or 0.0,
            accuracy=result.accuracy or 0.0,
            self_corrections=result.self_correction_count,
        )

    # ------------------------------------------------------------------ review

    async def start_review(self) -> dict | None:
        """Begin the end-of-passage review: teach the first missed word and
        ask the child to say it again to confirm. Called once, right after
        finish_passage - real feedback from a real reading session, not a
        guess: spoken corrections firing mid-read (even the old mastery-
        delayed ones) read as constant interruption, so every real stumble
        is now taught here, in one pass, after the whole passage is read,
        before comprehension questions start.

        Returns None (and leaves state at PASSAGE_DONE, ready for
        start_comprehension exactly as before this feature existed) if there
        was nothing worth reviewing - a clean read shouldn't get a review
        phase bolted on for its own sake.
        """
        if self.state is not TutorState.PASSAGE_DONE:
            raise RuntimeError(f"start_review called in state {self.state}")
        if not self._review_queue:
            return None
        self.state = TutorState.REVIEW
        self._review_cursor = 0
        return await self._teach_word(self._miscue_for_review_cursor(), now_t=self._final_result_t())

    async def submit_review_reply(self, spoken_word: str, *, now_t: int) -> tuple[dict, dict | None]:
        """Child attempted the current review word again. Returns
        (a review-result event, the next teaching event or None). None
        means review is complete - state returns to PASSAGE_DONE, ready for
        start_comprehension, exactly as if there had been nothing to
        review."""
        if self.state is not TutorState.REVIEW:
            raise RuntimeError(f"submit_review_reply called in state {self.state}")

        miscue = self._miscue_for_review_cursor()
        correct = _closely_matches(spoken_word, miscue.reference_word or "")
        if correct:
            self._hints_delayed_self_corrected_count += 1
        result_event = tutor_events.review_word_result(
            t=now_t, reference_index=miscue.reference_index, reference_word=miscue.reference_word, correct=correct
        )

        self._review_cursor += 1
        if self._review_cursor >= len(self._review_queue):
            self.state = TutorState.PASSAGE_DONE
            return result_event, None

        next_event = await self._teach_word(self._miscue_for_review_cursor(), now_t=now_t)
        return result_event, next_event

    def _miscue_for_review_cursor(self) -> Miscue:
        idx = self._review_queue[self._review_cursor]
        # finish_passage() always populates _final_result before _review_queue
        # can be non-empty, and every entry in the queue came from that same
        # result's miscues, so this lookup can't miss.
        return next(m for m in self._final_result.miscues if m.reference_index == idx)

    def _final_result_t(self) -> int:
        # start_review has no now_t of its own (tutor_processor.py calls it
        # right after finish_passage, whose now_t already flowed into
        # passage_complete) - reuse the last settled timestamp as a
        # reasonable stand-in for "right now."
        return max((m.t for m in self._final_result.miscues if m.t is not None), default=0)

    # ----------------------------------------------------------- comprehension

    async def start_comprehension(self, *, num_questions: int = 3) -> str:
        """Strong-tier call: generate 2-3 questions grounded in the passage
        text, transition to COMPREHENSION, and return the first question.
        """
        if self.state is not TutorState.PASSAGE_DONE:
            raise RuntimeError(f"start_comprehension called in state {self.state}")

        self._questions = await self.llm_client.generate_questions(
            passage_text=self.passage["text"],
            hint_topics=self.passage.get("comprehension_hint_topics", []),
            num_questions=num_questions,
        )
        if not self._questions:
            raise RuntimeError("generate_questions returned no questions")

        self.state = TutorState.COMPREHENSION
        self._question_cursor = 0
        return self._questions[0].question

    @property
    def current_question(self) -> ComprehensionQuestion | None:
        if self.state is not TutorState.COMPREHENSION:
            return None
        if self._question_cursor >= len(self._questions):
            return None
        return self._questions[self._question_cursor]

    async def hear_partial_answer(
        self, fragment: str, *, now_t: int
    ) -> tuple[dict, str | None, bool] | None:
        """Called once per Deepgram-finalized transcript fragment while an
        answer is being spoken (see this module's MAX_ANSWER_FRAGMENTS_
        BEFORE_FORCE_SUBMIT comment for the real problem this solves).
        Accumulates fragments for the current question and asks the LLM
        whether the accumulated text is actually a finished answer yet.

        Returns None while still judged incomplete - the caller (tutor_
        processor.py) should say nothing and keep listening. Once judged
        complete (or the fragment cap is hit as a safety net), delegates to
        submit_answer with the full accumulated text and returns exactly
        what it returns.
        """
        if self.state is not TutorState.COMPREHENSION:
            raise RuntimeError(f"hear_partial_answer called in state {self.state}")
        fragment = fragment.strip()
        if not fragment:
            return None
        q = self.current_question
        if q is None:
            raise RuntimeError("hear_partial_answer called with no current question")

        self._pending_answer_fragments.append(fragment)
        accumulated = " ".join(self._pending_answer_fragments)

        forced = len(self._pending_answer_fragments) >= MAX_ANSWER_FRAGMENTS_BEFORE_FORCE_SUBMIT
        complete = forced or await self.llm_client.is_answer_complete(
            question=q.question, partial_answer=accumulated
        )
        if not complete:
            return None

        self._pending_answer_fragments = []
        return await self.submit_answer(accumulated, now_t=now_t)

    async def submit_answer(self, answer_given: str, *, now_t: int) -> tuple[dict, str | None, bool]:
        """Grade the current question's answer (strong-tier call).

        Real, explicit request: a wrong first attempt no longer ends the
        session (or jumps straight to the next question) on the spot - it
        gets exactly one retry, the SAME question repeated, before moving
        on. A correct answer, or a second wrong attempt on that same
        question, finalizes it (recording exactly one graded turn per
        question, never one per attempt) and advances to the next question
        or DONE.

        Returns `(comprehension_turn event, next_prompt_text_or_None,
        is_retry)`. `next_prompt_text` is the same question's text again
        when `is_retry` is True - tutor_processor.py frames that
        differently out loud (see REVIEW_TRY_AGAIN's precedent for the
        phonics-review flow) so it doesn't sound like the child's answer
        was never heard.
        """
        if self.state is not TutorState.COMPREHENSION:
            raise RuntimeError(f"submit_answer called in state {self.state}")
        q = self.current_question
        if q is None:
            raise RuntimeError("submit_answer called with no current question")

        correct, response_text = await self.llm_client.grade_answer(
            passage_text=self.passage["text"],
            question=q.question,
            expected_answer_gist=q.expected_answer_gist,
            answer_given=answer_given,
        )
        event = tutor_events.comprehension_turn(
            t=now_t,
            question=q.question,
            answer_given=answer_given,
            correct=correct,
            skill_id=q.skill_id,
            feedback_text=response_text or None,
        )

        if not correct and not self._question_retry_used:
            self._question_retry_used = True
            return event, q.question, True

        self._graded_turns.append(
            GradedTurn(
                question=q.question,
                answer_given=answer_given,
                correct=correct,
                skill_id=q.skill_id,
            )
        )
        self._question_retry_used = False
        self._question_cursor += 1
        if self._question_cursor >= len(self._questions):
            self.state = TutorState.DONE
            return event, None, False
        return event, self._questions[self._question_cursor].question, False

    # ------------------------------------------------------------- persistence

    def to_session_columns(self) -> dict[str, Any]:
        """The `sessions` row fields this agent is responsible for
        populating (contracts/db_schema.sql): `wcpm`, `accuracy`,
        `self_corrections`, `miscues` jsonb, `comprehension` jsonb,
        `hints_delayed_count`, `hints_delayed_self_corrected_count`.
        Actual DB write is out of this module's scope.
        """
        result = self._final_result
        miscues_json = [
            {
                "word": m.reference_word,
                "index": m.reference_index,
                "type": m.miscue_type.value,
                "skill_id": m.skill_id,
                "timestamp_ms": m.t,
            }
            for m in (result.miscues if result else [])
        ]
        comprehension_json = [
            {
                "question": t.question,
                "answer_given": t.answer_given,
                "correct": t.correct,
                "skill_id": t.skill_id,
            }
            for t in self._graded_turns
        ]
        return {
            "wcpm": result.wcpm if result else None,
            "accuracy": result.accuracy if result else None,
            "self_corrections": result.self_correction_count if result else 0,
            "miscues": miscues_json,
            "comprehension": comprehension_json,
            "hints_delayed_count": self._hints_delayed_count,
            "hints_delayed_self_corrected_count": self._hints_delayed_self_corrected_count,
        }


def _align_current(reference_words: list[str], recognized_events: list[dict]) -> AlignmentResult:
    spoken_words = [e["word"] for e in recognized_events]
    return align(reference_words, spoken_words)
