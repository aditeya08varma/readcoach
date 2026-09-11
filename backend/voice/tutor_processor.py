"""Bridges the live Deepgram transcription stream to `tutor-logic-engineer`'s
`TutorSession` state machine (backend/tutor/state_machine.py), and speaks its
decisions (hints, questions, feedback) via Cartesia TTS.

Written during integration. `backend/voice` and `backend/tutor` were built
independently and verified independently; this is the connective tissue
between them, which is why it lives here rather than in either module's
directory. Everything it calls on the tutor side (`TutorSession`,
`TutorLLMClient`) is unmodified from what `tutor-logic-engineer` shipped,
except for the additive `feedback_text` field on `comprehension_turn`
(contracts/voice_events.md), which the integration pass added because
`submit_answer` was already computing a warm spoken response and discarding
it - see the build log for that fix.

Turn-taking simplification made here, flagged rather than hidden: this does
not use full VAD-based turn management (Stage 0's hello-world used
`SileroVADAnalyzer` via `LLMContextAggregatorPair`, which this module
replaces). Reading completion is detected by word count reaching the
passage length - still true, and still a reasonable fit for that phase,
which doesn't need turn-taking at all (it's continuous word tracking, not
back-and-forth).

Comprehension answers no longer take the shortcut of treating "whatever
Deepgram finalizes next" as the whole answer (a real, documented gap: a
child who pauses mid-sentence to think - which this age group does
constantly - had their partial utterance graded as final, before they were
done talking). Rather than adopting Pipecat's own generic turn-controller
subsystem (`UserTurnProcessor`/`UserTurnController`), which is built around
a native LLM-in-the-pipeline conversational loop this project's hand-rolled
`TutorSession` state machine deliberately doesn't use, `TutorSession.
hear_partial_answer` accumulates each Deepgram-finalized fragment and asks
the LLM directly (the same `TutorLLMClient` this module already calls
everywhere else) whether the accumulated text is actually a finished
answer, using the same fast-tier call already used for in-the-moment hints.
Purpose-built for this project's own architecture rather than a generic
framework retrofit - see state_machine.py's hear_partial_answer.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from statistics import median

from voice_events import SessionClock, word_recognized  # local to backend/voice, imported
# before the sys.path insert below so its bare module name "events" (used
# internally by backend/tutor's own events.py, see the name-collision note
# further down) never gets bound to this file instead.
from mastery_client import post_completed_session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tutor"))

# NAME COLLISION, fixed during integration: backend/tutor/events.py and this
# module's own events.py (now renamed voice_events.py) both used the bare
# module name "events". Python caches imports by that bare name, so whichever
# loaded first would silently win for both call sites - state_machine.py's
# own `import events as tutor_events` would then resolve to the WRONG
# events.py, missing hint_spoken/passage_complete/comprehension_turn, and
# fail with an AttributeError the first time a hint or passage-complete event
# was actually built (not caught by a plain `import bot` smoke test - only by
# actually exercising the code path). Renaming backend/voice's file to
# voice_events.py and importing it before backend/tutor is ever added to
# sys.path (above) resolves this permanently rather than relying on import
# order being right by luck. See ../../docs/BUILD_LOG.md for the full story.
from claude_client import TutorLLMClient  # noqa: E402
from state_machine import TutorSession, TutorState  # noqa: E402

from loguru import logger
from pipecat.frames.frames import Frame, StartFrame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frameworks.rtvi import RTVIProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

GREETING_TEMPLATE = (
    "Hi! Today we're reading {title}. Go ahead and start reading out loud "
    "whenever you're ready."
)
TRANSITION_TO_COMPREHENSION = "Great reading! Now let's talk about the story."
# Real feedback from a real session: a wrong answer on the last question
# ended the whole session immediately, and even a wrong answer mid-story
# just moved straight on to the next question with no real chance to
# reconsider - both read as the bot abruptly giving up, not tutoring. This
# spoken framing pairs with state_machine.py's one-retry-per-question rule
# (submit_answer's `is_retry`) - said before repeating the SAME question,
# so a second try reads as encouragement, not as the bot not having heard
# the first answer.
COMPREHENSION_RETRY_PREFIX = "Let's think about that one again. "
# Real, explicit request: this needs to clearly say the story itself is
# done (not just "good job today" in the abstract) and that another story
# is next, since the abrupt-feeling ending was as much about WHAT was said
# as about the wrong-answer handling above.
SESSION_CLOSING_TEMPLATE = (
    "You've finished {title}! Great job today - you're becoming a great "
    "reader. Whenever you're ready, tap Next Story to keep going."
)
# Real feedback from a real reading session: interjecting a hint mid-word
# ("boat", "paddled") read as talking over the child, not helping. These
# frame the same corrections as one short practice round right after the
# whole passage is read, before moving on to the story questions - see
# state_machine.py's REVIEW state for the actual pacing change.
REVIEW_INTRO = "Nice reading! Let's practice a couple of words before we talk about the story."
REVIEW_CORRECT = "That's it! Nice work."
REVIEW_TRY_AGAIN = "Good try - let's keep going."


class TutorProcessor(FrameProcessor):
    """Sits where the LLM step used to sit in the Stage 0 pipeline: after STT,
    before TTS. Consumes `TranscriptionFrame`s, drives `TutorSession`, and
    pushes `TTSSpeakFrame`s for anything that should be spoken.
    """

    def __init__(
        self,
        clock: SessionClock,
        passage: dict,
        llm_api_key: str,
        student_id: str | None,
        rtvi: RTVIProcessor,
        mastery_weights: dict[str, float] | None = None,
        # Real per-stage latency, previously never captured on a real
        # session at all (see latency_observer.py's module docstring).
        # `llm_client`, when given, replaces the plain TutorLLMClient this
        # would otherwise construct itself - bot.py passes a
        # latency_observer.TimingLLMClient wrapping the real thing, so
        # `_finish_session` can read its `llm_ms()` back out afterward.
        # `latency_observer` is the LatencyObserver registered on the
        # pipeline's own worker, read the same way for stt_ms/tts_ms.
        llm_client: TutorLLMClient | None = None,
        latency_observer=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._clock = clock
        self._passage = passage
        self._student_id = student_id
        self._rtvi = rtvi
        self._latency_observer = latency_observer
        # Real per-word STT delay, computed from timestamps this pipeline
        # already has on hand - see _handle_reading_turn. Pipecat's own STT
        # TTFB metric (what LatencyObserver watches for) needs a real
        # VADUserStoppedSpeakingFrame to ever start its timer, which this
        # pipeline deliberately doesn't emit (see this module's own
        # docstring on turn-taking) - it always comes back as an untrue
        # 0.0, a real gap found and root-caused, not a bug in the observer
        # itself (see docs/BUILD_LOG.md). Every word_recognized event
        # already carries both `t` (this pipeline's own clock, the instant
        # we found out about the word) and `end_ms` (Deepgram's own
        # timestamp, relative to the same STT-connection-open zero point,
        # for when that word's audio actually ended) - their difference is
        # a real, honest "how long after the child finished this word did
        # we find out" delay, with no VAD involved at all.
        self._stt_delay_samples_ms: list[float] = []
        self._session = TutorSession(
            passage=passage,
            llm_client=llm_client or TutorLLMClient(api_key=llm_api_key),
            mastery_weights=mastery_weights,
        )
        self._recognized_count = 0
        self._greeted = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame) and not self._clock.started:
            self._clock.start()

        if isinstance(frame, TranscriptionFrame):
            await self._handle_transcription(frame)
            return  # consumed here; nothing downstream needs the raw transcript

        await self.push_frame(frame, direction)

    async def announce_passage(self) -> None:
        """Emit `passage_loaded` (contracts/voice_events.md) with the exact
        passage this bot picked, before anything else. Real bug this fixes:
        the frontend used to fetch its own passage independently and had no
        way to know what the bot actually chose - see the contract entry for
        the full story of how that was found."""
        await self._emit({
            "type": "passage_loaded",
            "t": self._clock.now_ms() if self._clock.started else 0,
            "passage": self._passage,
        })

    async def greet(self) -> TTSSpeakFrame:
        self._greeted = True
        text = GREETING_TEMPLATE.format(title=self._passage.get("title", "this story"))
        return TTSSpeakFrame(text=text, append_to_context=False)

    async def _handle_transcription(self, frame: TranscriptionFrame) -> None:
        if self._session.state is TutorState.READING:
            await self._handle_reading_turn(frame)
        elif self._session.state is TutorState.REVIEW:
            await self._handle_review_turn(frame)
        elif self._session.state is TutorState.COMPREHENSION:
            await self._handle_comprehension_turn(frame)
        # DONE / PASSAGE_DONE: nothing left to do with more speech input.

    async def _handle_reading_turn(self, frame: TranscriptionFrame) -> None:
        words = self._words_of(frame)
        for w in words:
            event = word_recognized(
                self._clock,
                word=w["word"],
                start_ms=w["start_ms"],
                end_ms=w["end_ms"],
                confidence=w["confidence"],
            )
            self._record_stt_delay(event)
            await self._emit(event)
            # Purely visual now (live word-by-word highlighting) - no hint is
            # ever spoken from here anymore, see state_machine.py's REVIEW.
            for e in await self._session.feed_word_recognized(event):
                await self._emit(e)
        self._recognized_count += len(words)

        if self._recognized_count >= len(self._passage["words"]):
            await self._finish_reading()

    def _record_stt_delay(self, word_event: dict) -> None:
        """Real per-word STT delay from data this pipeline already has, no
        VAD required - see __init__'s comment on why this exists instead of
        relying on Pipecat's own (permanently-zero, here) STT TTFB metric.

        `t` and `end_ms` are both relative to the same STT-connection-open
        zero point (see voice_events.word_recognized's own docstring), so
        their difference is a real elapsed delay, not two incomparable
        clocks - a negative value would mean that assumption broke for this
        one word (clock skew, an out-of-order frame), so it's discarded
        rather than recorded as a nonsensical negative "delay".
        """
        delay_ms = word_event["t"] - word_event["end_ms"]
        if delay_ms >= 0:
            self._stt_delay_samples_ms.append(delay_ms)

    async def _finish_reading(self) -> None:
        # finish_passage runs the same synchronous alignment DP as every
        # incremental feed_word_recognized call, but unbounded over the
        # whole passage rather than a small window - staying a plain sync
        # method (tests and backend/eval/latency_eval.py both call it
        # directly, unawaited, and there's no reason to make either await
        # something that fast) means this one live call site is the only
        # place that needs to keep it off this process's shared event loop.
        event = await asyncio.to_thread(self._session.finish_passage, now_t=self._clock.now_ms())
        await self._emit(event)
        teach_event = await self._session.start_review()
        if teach_event is None:
            await self._start_comprehension_phase()
            return
        await self._emit(teach_event)
        await self.push_frame(TTSSpeakFrame(text=REVIEW_INTRO, append_to_context=False))
        await self.push_frame(TTSSpeakFrame(text=teach_event["text"], append_to_context=False))

    async def _handle_review_turn(self, frame: TranscriptionFrame) -> None:
        spoken_word = frame.text.strip()
        if not spoken_word:
            return
        result_event, next_teach_event = await self._session.submit_review_reply(
            spoken_word, now_t=self._clock.now_ms()
        )
        await self._emit(result_event)
        await self.push_frame(
            TTSSpeakFrame(
                text=REVIEW_CORRECT if result_event["correct"] else REVIEW_TRY_AGAIN,
                append_to_context=False,
            )
        )
        if next_teach_event is None:
            await self._start_comprehension_phase()
            return
        await self._emit(next_teach_event)
        await self.push_frame(TTSSpeakFrame(text=next_teach_event["text"], append_to_context=False))

    async def _start_comprehension_phase(self) -> None:
        await self.push_frame(TTSSpeakFrame(text=TRANSITION_TO_COMPREHENSION, append_to_context=False))
        first_question = await self._session.start_comprehension()
        await self.push_frame(TTSSpeakFrame(text=first_question, append_to_context=False))

    async def _handle_comprehension_turn(self, frame: TranscriptionFrame) -> None:
        fragment = frame.text.strip()
        if not fragment:
            return
        result = await self._session.hear_partial_answer(fragment, now_t=self._clock.now_ms())
        if result is None:
            # Real, explicit request: a pause mid-answer must not be treated
            # as "done" (see state_machine.py's hear_partial_answer). Say
            # nothing and keep listening for the rest of the answer.
            return
        event, next_prompt, is_retry = result
        await self._emit(event)
        feedback = event.get("feedback_text")
        if feedback:
            await self.push_frame(TTSSpeakFrame(text=feedback, append_to_context=False))
        if is_retry:
            await self.push_frame(
                TTSSpeakFrame(text=COMPREHENSION_RETRY_PREFIX + next_prompt, append_to_context=False)
            )
        elif next_prompt:
            await self.push_frame(TTSSpeakFrame(text=next_prompt, append_to_context=False))
        else:
            await self._finish_session()

    async def _finish_session(self) -> None:
        closing_text = SESSION_CLOSING_TEMPLATE.format(title=self._passage.get("title", "this story"))
        await self.push_frame(TTSSpeakFrame(text=closing_text, append_to_context=False))
        session_id_event = {"type": "session_ended", "t": self._clock.now_ms()}
        await self._emit(session_id_event)

        if self._student_id is not None:
            columns = self._session.to_session_columns()
            latency = self._collect_pipeline_latency_ms()
            if latency:
                columns["pipeline_latency_ms"] = latency
            await post_completed_session(
                student_id=self._student_id,
                passage_id=self._passage["id"],
                session_columns=columns,
            )
        else:
            logger.info("No demo student id (mastery service unreachable) - session not persisted")

    def _collect_pipeline_latency_ms(self) -> dict[str, float] | None:
        """Real per-stage latency for this one session (see
        latency_observer.py). Any stage with zero real samples (e.g. a
        session with no comprehension questions asked, so no LLM grading
        calls) is left out entirely rather than reported as 0 - an honest
        gap, not a fabricated number, matching this project's established
        rule (see backend/mastery/main.py's engineering_dashboard)."""
        result: dict[str, float] = {}
        llm_ms = getattr(self._session.llm_client, "llm_ms", None)
        if callable(llm_ms) and (value := llm_ms()) is not None:
            result["llm_ms"] = value
        # Real per-word timestamp deltas (see _record_stt_delay) take
        # priority - they're real data here, unlike LatencyObserver's own
        # STT figure, which needs VAD this pipeline doesn't run and so is
        # always empty. Falling back to it anyway costs nothing if this
        # pipeline ever does gain a VAD analyzer later.
        if self._stt_delay_samples_ms:
            result["stt_ms"] = round(median(self._stt_delay_samples_ms), 1)
        elif self._latency_observer is not None and (value := self._latency_observer.stt_ms()) is not None:
            result["stt_ms"] = value
        if self._latency_observer is not None and (value := self._latency_observer.tts_ms()) is not None:
            result["tts_ms"] = value
        return result or None

    async def _emit(self, event: dict) -> None:
        # Real bug found while wiring the frontend to the real bot for the
        # first time (see ../../docs/BUILD_LOG.md): this used to build a
        # Daily-specific frame directly, which only the Daily transport's
        # output stage knows how to serialize. Every real test of this bot
        # so far ran on the plain WebRTC transport (`-t webrtc`), where that
        # frame type was silently never delivered to any client - audio
        # worked, but not one word/miscue/hint event ever actually reached
        # a browser. RTVIProcessor.send_server_message is the transport-
        # agnostic, officially supported way to reach a connected
        # @pipecat-ai/client-js client regardless of which transport is
        # actually running underneath.
        await self._rtvi.send_server_message(event)

    @staticmethod
    def _words_of(frame: TranscriptionFrame) -> list[dict]:
        result = frame.result
        if result is None:
            return []
        try:
            words = result.channel.alternatives[0].words
        except (AttributeError, IndexError):
            logger.warning("TutorProcessor: Deepgram result had no word-level timing, skipping")
            return []
        return [
            {
                "word": w.punctuated_word or w.word,
                "start_ms": round(w.start * 1000),
                "end_ms": round(w.end * 1000),
                "confidence": w.confidence,
            }
            for w in words
        ]
