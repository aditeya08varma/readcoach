"""ReadCoach voice pipeline - now wired to the real tutoring logic.

Daily (mic in) -> Deepgram streaming STT (nova-3) -> TutorProcessor (backend
/tutor's TutorSession, via tutor_processor.py) -> Cartesia TTS -> Daily
(audio out).

Stage 0 proved this loop's raw latency with a hello-world LLM step that just
made small talk. That step has been replaced, during integration, with the
real tutoring state machine `tutor-logic-engineer` built independently in
backend/tutor: live miscue detection and phonics hints while the child
reads, then grounded comprehension questions and grading once the passage
is done. Passage selection and session persistence go through
`mastery-engineer`'s service (backend/mastery) via mastery_client.py, with a
local fallback passage if that service isn't running. See
tutor_processor.py's module docstring for the turn-taking simplification
made during this integration pass, and the build log
(../../docs/BUILD_LOG.md) for the full writeup.

Setup and how to run this: see README.md in this directory.
"""

import asyncio
import os

from dotenv import load_dotenv
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.frameworks.rtvi import RTVIProcessor
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
from tutor_processor import TutorProcessor
from latency_observer import LatencyObserver, TimingLLMClient

# backend/tutor is already on sys.path by the time this line runs -
# tutor_processor.py's own top-level import does that insertion as a side
# effect of the import just above (see its module docstring's name-
# collision note for why that insert has to happen where it does).
from claude_client import TutorLLMClient  # noqa: E402

# Same real incident as backend/mastery/db.py (see docs/BUILD_LOG.md and
# that file's own comment): override=True made .env always win over the
# shell's own environment, so a shell-level override (e.g. a test run
# pointing MASTERY_SERVICE_URL somewhere disposable) would have silently
# been ignored in favor of whatever .env says. override=False (the
# library's own default, made explicit here) is the safe precedence.
load_dotenv(override=False)

# Story map "choose a story" flow (docs/FEATURE_IDEAS.md's gameplay
# ideation): a real person's explicit story pick, set by the frontend
# calling POST /choose_passage on this same server just before it opens the
# WebRTC connection, and consumed by that same connection's run_bot() call.
# This exists because Pipecat's own documented way to pass custom data
# through a connection request (the client SDK's `requestData` option) was
# tested for real and confirmed to never arrive as `runner_args.body` in
# this version combination - see run_bot()'s comment for the full story.
#
# Keyed by the client-generated session_id the frontend now mints before
# either of these two POSTs and threads through to /api/offer?session_id=...
# (voiceEventStream.ts's start()) - Pipecat's own runner already accepts and
# forwards that id as runner_args.session_id (pipecat/runner/run.py's
# /api/offer handler). A single shared global here used to mean two
# real browser tabs opening a session close together could genuinely steal
# each other's chosen passage/student, confirmed as a real, concrete race
# (not a hypothetical): tab A sets its choice, tab B's own choose_passage
# call overwrites it before tab A's connection has actually consumed it, and
# A's run_bot() then reads B's choice while B's own later run_bot() finds
# nothing left and silently falls back to auto-selection. Keying by session
# id removes that race entirely - one dict entry per in-flight connection,
# popped the moment that connection's own run_bot() consumes it.
_pending_passage_choice: dict[str, str] = {}

# Same mechanism, same reason, for "which real student is this" instead of
# "which story": the frontend's real login layer (frontend/auth.ts,
# docs/BUILD_LOG.md) knows the real logged-in parent's real student the
# moment they open the reading screen, and passes it here immediately before
# connecting - not through the same empirically-broken requestData
# passthrough _pending_passage_choice already works around. Missing for a
# given session_id (the ordinary case - no login, or local dev without the
# frontend's auth layer) means keep resolving the shared demo student
# exactly as before login existed (see mastery_client.fetch_next_passage's
# student_id_override).
_pending_student_id: dict[str, str] = {}


@runner_app.post("/choose_passage")
async def choose_passage(payload: dict):
    """Frontend calls this immediately before connecting, when a child (or a
    demo) explicitly picks a story from the story map, instead of letting
    the bot auto-select. See contracts/api_contract.md."""
    session_id = payload.get("session_id")
    passage_id = payload.get("passage_id")
    if session_id and passage_id:
        _pending_passage_choice[session_id] = passage_id
    logger.info(f"Story explicitly chosen for session {session_id!r}: {passage_id!r}")
    return {"ok": True, "passage_id": passage_id}


@runner_app.post("/choose_student")
async def choose_student(payload: dict):
    """Frontend calls this immediately before connecting, once a real logged-
    in parent's session names a real student, instead of the shared demo
    student /students/demo would otherwise resolve to. Mirrors
    /choose_passage above exactly, for the same reason."""
    session_id = payload.get("session_id")
    student_id = payload.get("student_id")
    if session_id and student_id:
        _pending_student_id[session_id] = student_id
    logger.info(f"Student explicitly chosen for session {session_id!r}: {student_id!r}")
    return {"ok": True, "student_id": student_id}

# This one process's own real ceiling: every concurrent session shares one
# event loop and, more pressingly, one set of Deepgram/Anthropic/Cartesia
# API keys - piling sessions on without bound just means every session,
# including the ones already mid-read, degrades together once a provider's
# own rate limit gets hit. Rather than let that happen silently, a new
# connection past this cap is turned away up front, before it costs
# anything (no STT/LLM/TTS services constructed, no pipeline built) - a
# real, if blunt, admission control rather than no limit at all. Tunable via
# env for a real deploy with more headroom than this hackathon default
# assumes; the count itself is protected by _active_sessions_lock since
# run_bot() calls genuinely execute as concurrent asyncio tasks (see
# docs/BUILD_LOG.md), not one at a time.
MAX_CONCURRENT_SESSIONS = int(os.getenv("MAX_CONCURRENT_SESSIONS", "6"))
_active_sessions = 0
_active_sessions_lock = asyncio.Lock()

# A generic public Cartesia demo voice. Swap for a kid-friendly voice once
# one is chosen - this is only here so the pipeline has something to speak.
DEFAULT_CARTESIA_VOICE_ID = "86e30c1d-714b-4074-a1f2-1cb6b552fb49"

# We use lambdas (matching pipecat's own examples) so transport-specific
# params are only built once a transport type is actually selected at
# runtime by the `-t` CLI flag.
transport_params = {
    "daily": lambda: DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        # Deepgram is our STT service; Daily's own built-in transcription
        # would just be redundant cost sitting unused in the pipeline.
        transcription_enabled=False,
    ),
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    """Admission control, then the real session - split out from
    _run_bot_session() below so the capacity check (and the counter it
    guards) wraps the whole session's lifetime, not just its setup, without
    re-indenting that entire function's body into a single try block."""
    global _active_sessions
    async with _active_sessions_lock:
        if _active_sessions >= MAX_CONCURRENT_SESSIONS:
            logger.warning(
                f"Rejecting new session: {_active_sessions} already active "
                f"(MAX_CONCURRENT_SESSIONS={MAX_CONCURRENT_SESSIONS} - see "
                "that constant's own comment above for why this exists)."
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
    logger.info("Starting ReadCoach voice pipeline")

    clock = SessionClock()
    # A real person's explicit story choice (the story map's tap-a-node
    # flow) arrives here, not through a new endpoint of this bot's own, but
    # riding along on the WebRTC connection request itself - the frontend
    # passes it as requestData when connecting (see contracts/
    # api_contract.md's GET /students/{id}/passages/{passage_id} entry for
    # the full path). Missing (the ordinary case) means keep auto-selecting
    # exactly as before.
    # Real bug found empirically, not assumed: Pipecat's documented way to
    # pass custom data through a WebRTC connection request (the client
    # SDK's `requestData` option, meant to arrive here as `runner_args.body`)
    # simply never arrived - logged and confirmed `runner_args.body is None`
    # on every real connection attempt, camelCase/snake_case mismatch
    # between this client/server version pair or not. Rather than keep
    # relying on an framework passthrough that's empirically broken, this
    # uses `/choose_passage` instead (see below) - a tiny custom route added
    # directly to this same server, both ends fully owned by this project.
    #
    # Looked up (and popped) by this exact connection's own session_id, not
    # a shared global - Pipecat's runner mints/forwards this id from
    # /api/offer?session_id=... (voiceEventStream.ts sends it, see the
    # _pending_passage_choice module comment above for the real race this
    # replaced). A missing session_id (only possible if this bot is driven
    # by something other than this project's own frontend) falls back to
    # "no explicit choice", the same as any other cache miss here.
    session_id = runner_args.session_id
    chosen_passage_id = _pending_passage_choice.pop(session_id, None) if session_id else None
    chosen_student_id = _pending_student_id.pop(session_id, None) if session_id else None

    passage, student_id = await fetch_next_passage(chosen_passage_id, chosen_student_id)
    mastery_weights = await fetch_mastery_vector(student_id)
    logger.info(
        f"Loaded passage '{passage.get('title')}' ({passage.get('id')}), "
        f"{'explicitly chosen' if chosen_passage_id else 'auto-selected'}, "
        f"student_id={student_id or 'none (mastery service unreachable)'}, "
        f"mastery_weights={'loaded (' + str(len(mastery_weights)) + ' skills)' if mastery_weights else 'none - hints fire immediately'}"
    )

    # Transport-agnostic protocol layer that lets a real browser client
    # (@pipecat-ai/client-js) receive the word_recognized/miscue_detected/
    # hint_spoken/etc event stream over the data channel, regardless of
    # which transport (webrtc or daily) is actually running underneath.
    # See tutor_processor.py's _emit for the bug this replaced: it used to
    # build a Daily-specific frame directly, which the webrtc transport
    # (the only one ever actually tested with a real client so far) simply
    # had no way to deliver.
    rtvi = RTVIProcessor()

    stt = DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        settings=DeepgramSTTService.Settings(
            model="nova-3-general",
            smart_format=True,
            punctuate=True,
        ),
    )

    # Real per-stage latency (see latency_observer.py's module docstring for
    # why this needs both a pipeline-wide observer, for stt/tts, and a
    # wrapped LLM client, for llm - TutorProcessor has no direct visibility
    # into either service's own timing from where it sits in the pipeline).
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
            transport.input(),  # mic audio in (webrtc or Daily, per -t flag)
            rtvi,  # RTVI protocol layer - client-ready/bot-ready handshake,
            # and the channel tutor.send_server_message uses for every event
            stt,  # Deepgram streaming STT
            tutor,  # backend/tutor's TutorSession: miscue detection, hints,
            # comprehension questions/grading (see tutor_processor.py)
            tts,  # Cartesia TTS
            transport.output(),  # audio (+ data channel) out
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
        logger.info("Child connected - starting session clock")
        clock.start()
        await rtvi.set_bot_ready()
        await tutor.announce_passage()
        await worker.queue_frames([await tutor.greet()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Child disconnected")
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Main bot entry point, compatible with pipecat's runner CLI/dev server."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
