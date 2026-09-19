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
from pipecat.frames.frames import ErrorFrame, Frame, StartFrame, TranscriptionFrame, TTSSpeakFrame
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
# Real gap from a prior audit: Pipecat's own FrameProcessor already catches
# an unhandled exception raised out of process_frame() and turns it into an
# ErrorFrame automatically (see pipecat.processors.frame_processor's
# __process_frame) - but that frame only travels UPSTREAM, away from
# Cartesia TTS, and nothing downstream of the exception's own processor ever
# spoke a word about it. A Claude API call failing mid-comprehension-turn
# (see claude_client.py's own timeout/retry fix, the other half of this same
# audit finding) used to leave the child sitting in total silence forever:
# no exception ever crashed the process, no TTSSpeakFrame ever told them
# anything went wrong - a hang, not a crash. This line is deliberately
# generic (not "let's try that question again") since by the time this
# fires we only know *something* broke, not which step of the state machine
# it broke in.
ERROR_RECOVERY_TEXT = "Sorry, I got a little mixed up - let's keep going!"


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
        # Real per-batch STT delay, computed from timestamps this pipeline
        # already has on hand - see _handle_reading_turn and
        # _record_stt_delay. Pipecat's own STT TTFB metric (what
        # LatencyObserver watches for) needs a real VADUserStoppedSpeakingFrame
        # to ever start its timer, which this pipeline deliberately doesn't
        # emit (see this module's own docstring on turn-taking) - it always
        # comes back as an untrue 0.0, a real gap found and root-caused, not
        # a bug in the observer itself (see docs/BUILD_LOG.md). One sample
        # per Deepgram-finalized batch: `t` (this pipeline's own clock, the
        # instant we found out about the batch) minus the batch's last
        # word's `end_ms` (Deepgram's own timestamp, relative to the same
        # STT-connection-open zero point, for when that word's audio
        # actually ended) is a real, honest "how long after the child
        # finished speaking did we find out" delay, with no VAD involved at
        # all. Sampling every word in the batch against the same arrival
        # instant, not just the last one, was a real bug found live (see
        # docs/BUILD_LOG.md) - it measured position-in-batch, not latency.
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

        if isinstance(frame, ErrorFrame):
            # An ErrorFrame arriving HERE (as opposed to one raised out of
            # this processor's own code below, which never comes back to
            # this method - see push_error's own upstream-only routing) came
            # from a neighboring processor's exception, e.g. Cartesia TTS or
            # Deepgram STT failing outright. Speak the same recovery line and
            # keep forwarding it upstream unchanged - this only adds a
            # spoken response, it doesn't intercept whatever pipeline-level
            # handling (ProcessorUnusablePolicy, observers) the frame was
            # already on its way to.
            await self._speak_recovery_line(frame.error)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame):
            try:
                await self._handle_transcription(frame)
            except Exception as e:
                # The actual "Claude hiccup mid-comprehension-turn" case this
                # fixes: letting this propagate would hit pipecat's own
                # generic exception handling in FrameProcessor.__process_frame,
                # which converts it to an ErrorFrame and pushes it UPSTREAM
                # (see this class's own ErrorFrame branch above) - away from
                # TTS, so the child would never hear anything and the state
                # machine's own turn would just sit wherever it broke,
                # unresponsive to further speech. Catching it here instead
                # means we can both speak immediately AND still tell the rest
                # of the pipeline something went wrong.
                await self._speak_recovery_line(f"error handling transcription: {e!r}")
                await self.push_error(str(e), exception=e)
            return  # consumed here; nothing downstream needs the raw transcript

        await self.push_frame(frame, direction)

    async def _speak_recovery_line(self, error_text: str) -> None:
        logger.error(f"TutorProcessor: pipeline error, recovering with a spoken line: {error_text}")
        await self.push_frame(TTSSpeakFrame(text=ERROR_RECOVERY_TEXT, append_to_context=False))

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
        # Real bug found live (see docs/BUILD_LOG.md): one Deepgram
        # TranscriptionFrame finalizes a whole utterance at once, often
        # several words together, not one word per network round trip. The
        # old code sampled a "delay" for every word in that batch against
        # the same arrival instant - only the batch's own last word (whose
        # audio just barely finished) reflects real STT latency; every
        # earlier word in the same batch reads out an artificially small or
        # exactly-zero delay purely because it's earlier in the batch, not
        # because STT was actually fast for it. With most real speech
        # batching multiple words per finalization, those structural
        # near-zero samples outnumbered the real ones and dragged the
        # session's own median down to 0 - real per-session numbers, not a
        # display bug, confirmed against this project's own database.
        # Sampling once per batch, from its last word, is what "how long
        # after the audio actually finished did we get this batch" means.
        if words:
            self._record_stt_delay(
                {"t": self._clock.now_ms(), "end_ms": words[-1]["end_ms"]}
            )
        for w in words:
            event = word_recognized(
                self._clock,
                word=w["word"],
                start_ms=w["start_ms"],
                end_ms=w["end_ms"],
                confidence=w["confidence"],
            )
            await self._emit(event)
            # Purely visual now (live word-by-word highlighting) - no hint is
            # ever spoken from here anymore, see state_machine.py's REVIEW.
            for e in await self._session.feed_word_recognized(event):
                await self._emit(e)
        self._recognized_count += len(words)

        # Real bug found live (see docs/BUILD_LOG.md and state_machine.py's
        # own comment on TutorSession.insertion_count): comparing raw
        # Deepgram word count against the passage's own word count treats a
        # genuine insertion (an extra word the child said that isn't in the
        # passage at all - a real, already-modeled miscue type, not an edge
        # case) as real progress through the passage. A child who repeated
        # a phrase, said a filler word, or had a stray word misrecognized
        # could reach the passage's real word count - and trigger
        # _finish_reading, ending the reading turn - well before actually
        # finishing it, silently cutting off all further live highlighting
        # for the rest of the read. Subtracting genuine insertions gives
        # real progress through the reference passage instead of raw
        # recognized-word volume.
        effective_progress = self._recognized_count - self._session.insertion_count
        if effective_progress >= len(self._passage["words"]):
            await self._finish_reading()

    def _record_stt_delay(self, batch_event: dict) -> None:
        """Real per-batch STT delay from data this pipeline already has, no
        VAD required - see __init__'s comment on why this exists instead of
        relying on Pipecat's own (permanently-zero, here) STT TTFB metric.
        One sample per Deepgram-finalized batch (see _handle_reading_turn's
        own comment on why it's the batch's last word, not every word in
        it, that gets timed).

        `t` and `end_ms` are both relative to the same STT-connection-open
        zero point (see voice_events.word_recognized's own docstring), so
        their difference is a real elapsed delay, not two incomparable
        clocks - a negative value would mean that assumption broke for this
        one batch (clock skew, an out-of-order frame), so it's discarded
        rather than recorded as a nonsensical negative "delay".
        """
        delay_ms = batch_event["t"] - batch_event["end_ms"]
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

        # Real contract violation found by an audit, fixed here:
        # `session_ended` (contracts/voice_events.md) must carry `session_id`,
        # `passage_id`, and `pipeline_latency_ms` - this used to emit only
        # {type, t}. `passage_id` was always trivially available
        # (self._passage["id"]); `session_id` is the hard part, because it
        # doesn't exist anywhere until mastery-engineer's `/sessions` POST
        # mints it server-side (backend/mastery/main.py's ingest_session) -
        # which used to happen entirely AFTER this event had already gone
        # out. Awaiting post_completed_session BEFORE building/emitting the
        # event, instead of firing-and-forgetting it afterward, is the fix:
        # by the time session_ended is built below, the real id (or the real
        # "it didn't persist" answer) is already known.
        #
        # This does NOT block the child's actual experience on the mastery
        # service: the closing TTSSpeakFrame above is already pushed, so
        # they're already hearing "you've finished..." while this awaits.
        # Only the session_ended *event* (consumed by the frontend/other
        # backend services, never spoken) waits on it, and that wait is
        # bounded by post_completed_session's own 3s httpx timeout - not an
        # unbounded hang.
        #
        # mastery_client.post_completed_session is itself best-effort: on a
        # timeout, connection error, or non-2xx it logs a warning and
        # returns None rather than raising (see its own docstring). Sending
        # session_id: None in that case - rather than retrying, blocking
        # longer, or crashing the pipeline - is the deliberate choice: a
        # slow/down mastery service after the child's reading session is
        # already over must not turn into a worse experience than "this one
        # session's bookkeeping event has no id."
        latency = self._collect_pipeline_latency_ms()
        session_id = None
        if self._student_id is not None:
            columns = self._session.to_session_columns()
            if latency:
                columns["pipeline_latency_ms"] = latency
            session_id = await post_completed_session(
                student_id=self._student_id,
                passage_id=self._passage["id"],
                session_columns=columns,
            )
        else:
            logger.info("No demo student id (mastery service unreachable) - session not persisted")

        event = {
            "type": "session_ended",
            "t": self._clock.now_ms(),
            "session_id": session_id,
            "passage_id": self._passage["id"],
        }
        if latency:
            event["pipeline_latency_ms"] = latency
        await self._emit(event)

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
        # Real per-batch timestamp deltas (see _record_stt_delay) take
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
