"""Push-to-talk fallback pipeline - Stage 0 SKELETON, not functional yet.

`contracts/voice_events.md` describes a turn-based fallback mode for if the
full-duplex streaming pipeline in `bot.py` proves unreliable (bad turn-taking,
dropped words, VAD flakiness) during the Stage 0 round-trip-latency
checkpoint:

    "the bot runs in push-to-talk mode instead: the same event types are
    still emitted, just in batches after each recorded turn completes rather
    than incrementally word-by-word. Consumers should not assume
    word_recognized events arrive strictly one at a time in real time -
    treat gaps as normal in fallback mode."

This file is a documented placeholder for that mode, per this pass's scope
(build plan Stage 0 asks for it to be stubbed, not fully built, unless it
turns out to actually be needed). It has NOT been exercised against a live
Daily room - do not treat `bot()`/`run_bot()` below as working code, they
raise `NotImplementedError` on purpose. The module still needs to import
cleanly (no syntax errors) so it doesn't break tooling that scans this
directory.

How this would differ from bot.py once built:
  - The child explicitly signals "my turn is done" instead of VAD driving
    turn-taking automatically. Exactly what that signal is is still open:
    a press-and-hold button in the frontend sending a Daily data-channel
    message is the most likely choice, but a fixed silence timeout reused
    from bot.py's VAD is a fallback-of-the-fallback if the data channel
    itself is part of what's unreliable.
  - Audio for the turn should be buffered client-side-driven rather than
    streamed frame-by-frame into Deepgram as it arrives. Pipecat ships
    `pipecat.processors.audio.audio_buffer_processor.AudioBufferProcessor`
    for exactly this - collect audio for a bounded window, then transcribe
    the whole turn in one shot (either by still using DeepgramSTTService's
    streaming connection but only reading out finalized frames in one flush,
    or by calling Deepgram's prerecorded/batch REST endpoint on the buffered
    audio - the latter is simpler to reason about for a fallback path since
    there's no live connection to keep alive between turns).
  - `voice_events.word_recognized` / `voice_events.SessionClock` (renamed
    from events.py during integration - see the build log for why) do not
    need to change - the event *shape* is identical between modes; only the
    timing of when events fire differs (all at once per turn here, vs.
    incrementally in bot.py).
  - `word_recognized` events for a turn should be pushed as a batch of
    `DailyOutputTransportMessageUrgentFrame`s once that turn's transcript is
    back, the same forwarding mechanism `bot.py`'s `TutorProcessor` (formerly
    `WordRecognizedEmitter`, replaced once tutor-logic-engineer's real
    tutoring state machine was wired in during integration) already uses -
    no new transport-level plumbing needed.

STATUS UPDATE (post-integration): bot.py's live round-trip latency checkpoint
passed cleanly (Stage 0) and the full streaming pipeline has since been
wired end-to-end to real tutoring logic and verified with real API calls
(see the build log). This fallback has NOT been needed so far. Leaving it as
a documented skeleton in case real-world testing with actual children
surfaces turn-taking problems streaming didn't show in solo testing.

TODO before this is real (do these in order if bot.py's checkpoint fails):
  1. Pick and implement the "turn is done" signal.
  2. Add an AudioBufferProcessor (or equivalent) ahead of STT to collect one
     turn's audio instead of streaming continuously.
  3. Decide streaming-Deepgram-read-once-per-turn vs. batch/prerecorded API,
     and implement whichever is simpler given time left.
  4. Emit the batched `word_recognized` events per turn, reusing voice_events.py.
  5. Wire the same TutorProcessor + Cartesia stages from bot.py unchanged -
     only the STT/turn-taking half of the pipeline differs between the two
     modes.
"""

from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams

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


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    """Skeleton only - see module docstring TODOs. Mirrors bot.py's
    `run_bot(transport, runner_args)` signature so switching which module
    the runner boots from is a one-line change once this is built out."""
    raise NotImplementedError(
        "push-to-talk fallback is a documented skeleton (Stage 0 scope), not "
        "implemented. See the TODOs in backend/voice/push_to_talk_bot.py. "
        "Use bot.py (full-duplex streaming) unless/until that pipeline's "
        "round-trip-latency checkpoint shows it's unreliable."
    )


async def bot(runner_args: RunnerArguments):
    """Entry point matching bot.py's shape, for pipecat's runner CLI/dev
    server - not wired up to actually run anything yet."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
