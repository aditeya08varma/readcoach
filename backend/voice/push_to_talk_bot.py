"""Push-to-talk fallback pipeline - now a real, working turn-based bot.

`contracts/voice_events.md` describes a turn-based fallback mode for if the
full-duplex streaming pipeline in `bot.py` proves unreliable (bad turn-taking,
dropped words, VAD flakiness):

    "the bot runs in push-to-talk mode instead: the same event types are
    still emitted, just in batches after each recorded turn completes rather
    than incrementally word-by-word. Consumers should not assume
    word_recognized events arrive strictly one at a time in real time -
    treat gaps as normal in fallback mode."

STATUS UPDATE: bot.py's live round-trip latency checkpoint passed cleanly and
the full streaming pipeline has been wired end-to-end to real tutoring logic
(see docs/BUILD_LOG.md) - this fallback still hasn't been needed against a
live Daily room. It is no longer a bare `NotImplementedError` stub, though:
a prior audit flagged that leaving the *documented* fallback path completely
unimplemented was a real gap (the whole point of a fallback is that it works
the day the primary path doesn't), so this is now a genuine, if intentionally
narrower-scoped, turn loop rather than a placeholder.

WHAT'S REAL HERE:
  - `PushToTalkTurnGate` (below) is the actual turn-taking mechanism: an
    explicit "my turn is done" signal from the child, NOT VAD, decides when a
    turn ends - exactly what this mode exists for when VAD itself is what's
    unreliable. It sits between `stt` and `tutor` in the pipeline, buffers
    every `TranscriptionFrame` Deepgram finalizes, and releases the whole
    buffer downstream in one burst the moment a turn ends. TutorProcessor
    receives that burst exactly the way it receives bot.py's continuous
    stream - one TranscriptionFrame at a time, in order - it has no idea
    it's running in fallback mode at all, per this file's job of only
    changing capture/turn-taking, never tutoring logic.
  - The "turn is done" signal is an RTVI client message
    (`{"type": "ptt_turn_done"}`) sent over the same data channel this bot
    already uses for the word_recognized/etc event stream - the mechanism
    the original TODO list predicted ("a press-and-hold button in the
    frontend sending a Daily data-channel message is the most likely
    choice"), using Pipecat's own `RTVIClientMessageFrame` rather than a new
    transport-specific message type. Release the button -> frontend sends
    this -> `PushToTalkTurnGate` flushes.
  - A silence-based auto-flush (`_SILENCE_AUTO_FLUSH_SECONDS`) is the
    "fallback-of-the-fallback" the original TODO list called for in case the
    data channel signal itself is what's unreliable: if no `ptt_turn_done`
    arrives within that many seconds of the last recognized word, the turn
    flushes anyway rather than stranding the child forever.
  - Passage loading, mastery lookup, admission control, and the actual
    STT -> tutor -> TTS wiring below are copied from bot.py's proven,
    already-live version of each rather than re-derived from scratch.

WHAT'S STILL SIMPLIFIED, ON PURPOSE, AND WHY (flagged rather than hidden,
matching tutor_processor.py's own precedent for documenting simplifications
instead of silently shipping them):
  1. Audio still streams continuously into Deepgram's streaming connection,
     the same way bot.py's does - it is only Deepgram's *output*
     (TranscriptionFrames) that gets held back and released per-turn, not
     the raw mic audio itself. The original TODO list's alternative -
     client-side-buffered audio sent once per turn via
     `AudioBufferProcessor` plus either a one-shot read of the streaming
     connection or Deepgram's separate prerecorded/batch REST endpoint -
     would mean standing up and validating a second, never-yet-exercised
     Deepgram integration path purely to reduce STT cost/connection
     lifetime, without changing the turn-taking behavior a real child
     experiences at all (which is what this fallback mode is actually for).
     Gating the transcription output is the smaller, lower-risk change that
     delivers the same explicit-signal turn-taking; revisit only if the
     streaming connection itself (not VAD) turns out to be the unreliable
     part.
  2. No `/choose_passage` / `/choose_student` HTTP routes here (bot.py's
     story-map / login integration) - this always auto-selects a passage
     and resolves the shared demo student, same as bot.py did before either
     feature existed. Both routes register on the same shared
     `pipecat.runner.run.app` FastAPI instance bot.py already uses; only one
     of these two files is ever run as the process entrypoint at a time, so
     duplicating ~40 lines of route + module-global dict bookkeeping here
     for a fallback path with no live frontend integration yet would be
     unexercised code, not a real fix. Add it here the same way bot.py has
     it, without touching bot.py's own routes, if/when this path is
     actually put in front of the story map.
  3. Not exercised against a live Daily room or a real frontend push-to-talk
     button (frontend-engineer owns that UI, which doesn't exist yet either)
     - `PushToTalkTurnGate` itself is plain frame-processor logic with no
     Daily/Deepgram-specific state, so it's straightforward to unit-test in
     isolation (feed it TranscriptionFrames, then an RTVIClientMessageFrame,
     assert the buffered frames come out downstream in order), but that
     real-world round-trip check that bot.py's Stage 0 checkpoint already
     did for the streaming path has not happened for this one.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from loguru import logger

from pipecat.frames.frames import CancelFrame, EndFrame, Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIClientMessageFrame, RTVIProcessor
from pipecat.runner.run import app as runner_app
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams
from pipecat.workers.runner import WorkerRunner

from voice_events import SessionClock
from mastery_client import fetch_mastery_vector, fetch_next_passage
from tutor_processor import ERROR_RECOVERY_TEXT, TutorProcessor
from latency_observer import LatencyObserver, TimingLLMClient

# Same mechanism, same reason as bot.py's identical comment: backend/tutor is
# put on sys.path as a side effect of tutor_processor's own top-level import
# (the line just above), which must happen before backend/tutor/claude_client
# is imported here - see tutor_processor.py's module docstring for the name-
# collision this ordering avoids.
from claude_client import TutorLLMClient  # noqa: E402

load_dotenv(override=False)

# "My turn is done" signal (see module docstring) - an RTVI client message
# with this `type`, sent over the same data channel already carrying the
# word_recognized/etc event stream. No frontend button sends this yet; this
# is the server-side half of that contract.
PTT_TURN_DONE_MESSAGE_TYPE = "ptt_turn_done"

# Fallback-of-the-fallback (see module docstring): auto-flush a pending turn
# if this many seconds pass with no new recognized word AND no explicit
# ptt_turn_done, so a lost/never-sent data-channel message can't strand a
# turn in the same "hung, not crashed" way the ErrorFrame gap in
# tutor_processor.py used to (see that file's own fix). Generous on purpose -
# this age group pauses to think, and a false auto-flush mid-turn would cut
# off a word_recognized batch same as a real bug would.
_SILENCE_AUTO_FLUSH_SECONDS = 6.0

# Same reasoning, same tunable, as bot.py's identical constant - a separate
# process, so its own independent counter.
MAX_CONCURRENT_SESSIONS = int(os.getenv("MAX_CONCURRENT_SESSIONS", "6"))
_active_sessions = 0
_active_sessions_lock = asyncio.Lock()

DEFAULT_CARTESIA_VOICE_ID = "86e30c1d-714b-4074-a1f2-1cb6b552fb49"

transport_params = {
    "daily": lambda: DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        transcription_enabled=False,
    ),
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}


class PushToTalkTurnGate(FrameProcessor):
    """The actual turn-taking mechanism for this fallback mode (see module
    docstring). Sits between `stt` and `tutor` in the pipeline: buffers every
    `TranscriptionFrame` it sees instead of forwarding it immediately, and
    releases the whole buffer downstream in recognition order the moment a
    turn ends - either an explicit `ptt_turn_done` RTVI client message, or
    (fallback-of-the-fallback) `_SILENCE_AUTO_FLUSH_SECONDS` of inactivity.

    Deliberately has zero knowledge of tutoring state (reading vs. review vs.
    comprehension) - it only knows "hold these, then release them together",
    which is exactly the batching contracts/voice_events.md's fallback-mode
    section describes. TutorProcessor downstream can't tell the difference
    between a burst released from here and bot.py's own continuous stream.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buffer: list[TranscriptionFrame] = []
        self._auto_flush_task: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (EndFrame, CancelFrame)):
            # Session ending mid-turn: flush rather than silently drop
            # whatever was already recognized, then let the End/CancelFrame
            # itself continue downstream as normal.
            await self._flush("session ending")
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame):
            self._buffer.append(frame)
            await self._reschedule_auto_flush()
            return  # held here until the turn ends - see class docstring

        if isinstance(frame, RTVIClientMessageFrame) and frame.type == PTT_TURN_DONE_MESSAGE_TYPE:
            await self._flush("explicit ptt_turn_done signal")
            return  # consumed - this message is for this gate, not downstream

        await self.push_frame(frame, direction)

    async def _reschedule_auto_flush(self) -> None:
        # Plain `asyncio.create_task`/`.cancel()` rather than this base
        # class's own `create_task`/`cancel_task` helpers: those route
        # through `self.task_manager`, which only exists once a real
        # pipeline has called `setup()` on this processor - fine in
        # production, but it would mean this one small, entirely private
        # timer (nothing else ever touches `_auto_flush_task`) couldn't be
        # unit-tested without standing up a full PipelineWorker. A stray
        # already-finished task's `.cancel()` is a documented no-op, so no
        # extra guard is needed here.
        if self._auto_flush_task is not None:
            self._auto_flush_task.cancel()
        self._auto_flush_task = asyncio.create_task(self._auto_flush_after_silence())

    async def _auto_flush_after_silence(self) -> None:
        try:
            await asyncio.sleep(_SILENCE_AUTO_FLUSH_SECONDS)
        except asyncio.CancelledError:
            return
        await self._flush(f"{_SILENCE_AUTO_FLUSH_SECONDS}s silence, no ptt_turn_done seen")

    async def _flush(self, reason: str) -> None:
        if self._auto_flush_task is not None:
            self._auto_flush_task.cancel()
            self._auto_flush_task = None
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        logger.info(
            f"PushToTalkTurnGate: releasing {len(batch)} buffered transcription "
            f"frame(s) downstream - {reason}"
        )
        for buffered_frame in batch:
            await self.push_frame(buffered_frame, FrameDirection.DOWNSTREAM)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    """Admission control, then the real session - same split as bot.py's
    `run_bot`/`_run_bot_session`, same reason (see that file's comment)."""
    global _active_sessions
    async with _active_sessions_lock:
        if _active_sessions >= MAX_CONCURRENT_SESSIONS:
            logger.warning(
                f"Rejecting new push-to-talk session: {_active_sessions} already "
                f"active (MAX_CONCURRENT_SESSIONS={MAX_CONCURRENT_SESSIONS})."
            )
            await transport.cleanup()
            return
        _active_sessions += 1
    try:
        await _run_bot_session(transport, runner_args)
    finally:
        async with _active_sessions_lock:
            _active_sessions -= 1


async def _run_bot_session(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info("Starting ReadCoach push-to-talk (turn-based) voice pipeline")

    clock = SessionClock()

    # No /choose_passage or /choose_student here yet - see module docstring
    # point 2. Always auto-selects, same as bot.py did before either feature
    # existed.
    passage, student_id = await fetch_next_passage(None, None)
    mastery_weights = await fetch_mastery_vector(student_id)
    logger.info(
        f"Loaded passage '{passage.get('title')}' ({passage.get('id')}), auto-selected, "
        f"student_id={student_id or 'none (mastery service unreachable)'}, "
        f"mastery_weights={'loaded (' + str(len(mastery_weights)) + ' skills)' if mastery_weights else 'none - hints fire immediately'}"
    )

    rtvi = RTVIProcessor()

    stt = DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        settings=DeepgramSTTService.Settings(
            model="nova-3-general",
            smart_format=True,
            punctuate=True,
        ),
    )

    turn_gate = PushToTalkTurnGate()

    latency_observer = LatencyObserver()
    timed_llm_client = TimingLLMClient(TutorLLMClient(api_key=os.environ["ANTHROPIC_API_KEY"]))

    tutor = TutorProcessor(
        clock,
        passage=passage,
        llm_api_key=os.environ["ANTHROPIC_API_KEY"],
        student_id=student_id,
        rtvi=rtvi,
        mastery_weights=mastery_weights,
        llm_client=timed_llm_client,
        latency_observer=latency_observer,
    )

    tts = CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(voice=DEFAULT_CARTESIA_VOICE_ID),
    )

    pipeline = Pipeline(
        [
            transport.input(),  # mic audio in, streamed continuously (see
            # module docstring point 1 for why this differs from the
            # original TODO's client-buffered-audio plan)
            rtvi,  # RTVI protocol layer - also how ptt_turn_done arrives
            stt,  # Deepgram streaming STT, same config as bot.py
            turn_gate,  # NEW: holds TranscriptionFrames until turn end
            tutor,  # unchanged TutorProcessor/TutorSession - identical to bot.py
            tts,  # Cartesia TTS
            transport.output(),
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[latency_observer],
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Child connected (push-to-talk mode) - starting session clock")
        clock.start()
        await rtvi.set_bot_ready()
        # Same gap, same fix as bot.py's identical handler (see its comment
        # for the full reasoning): nothing here caught an exception from
        # announce_passage()/greet(), unlike the mid-session path's real
        # ErrorFrame recovery. Reuses the same ERROR_RECOVERY_TEXT line,
        # queued via worker.queue_frames for the same reason bot.py's does.
        try:
            await tutor.announce_passage()
            await worker.queue_frames([await tutor.greet()])
        except Exception as e:
            logger.error(f"push_to_talk_bot.py: on_client_connected bootstrap failed, recovering with a spoken line: {e!r}")
            await worker.queue_frames([TTSSpeakFrame(text=ERROR_RECOVERY_TEXT, append_to_context=False)])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Child disconnected")
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Entry point matching bot.py's shape, for pipecat's runner CLI/dev
    server. Run this instead of bot.py to use push-to-talk mode."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
