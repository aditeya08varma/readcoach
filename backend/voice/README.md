# backend/voice - ReadCoach voice pipeline

Real-time voice bot: Daily (mic in) -> Deepgram streaming STT -> TutorProcessor
(backend/tutor's real tutoring state machine, see tutor_processor.py) ->
Cartesia TTS -> Daily (audio out). Stage 0 proved this loop's raw latency with
a hello-world small-talk LLM step; that step has since been replaced with the
real tutoring logic during integration. See `bot.py`'s module docstring and
`../../docs/BUILD_LOG.md` for the full story of what changed and why.

## Install

```bash
cd backend/voice
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` with real values for `DAILY_API_KEY`, `DEEPGRAM_API_KEY`,
`ANTHROPIC_API_KEY`, and `CARTESIA_API_KEY` (see `.env.example` for where to
get each one).

For the mastery service integration (passage selection + session
persistence) to work, also start `backend/mastery` separately (see that
directory's own setup) before running the bot - it defaults to
`http://localhost:8000`, overridable via `MASTERY_SERVICE_URL`. If that
service isn't running, the bot still works, it just falls back to a fixed
local passage and doesn't persist the session anywhere.

## Create/join a Daily room for testing

You don't need to manually create a room first. Running the bot with
`-t daily` (below) uses pipecat's runner, which will:

- create a temporary Daily room for you automatically (needs only
  `DAILY_API_KEY`), **or**
- reuse a specific room if you set `DAILY_ROOM_URL` in your shell
  environment (handy if you want a stable link to keep reopening)

Either way, when the bot starts it logs a room URL - open that URL in a
browser tab, allow microphone access, and you're in the same room as the
bot.

## Run the bot

```bash
python bot.py -t daily
```

This starts a local dev server (default `http://localhost:7860`) that hosts
the bot process. On first connection to the room, the bot greets you by name
of the passage it picked ("Let's read [title]...") and then listens as you
read it aloud - it will interject a spoken phonics hint if you stumble on a
word, then ask a couple of comprehension questions once you finish the
passage.

Useful flags:
- `-t webrtc` runs the bot against pipecat's built-in browser client instead
  of Daily (open `http://localhost:7860/client/`) - a faster loop for
  checking the STT/LLM/TTS wiring itself without touching Daily at all.
- `-v` / `-vv` for more verbose logging if something isn't working.

## Manually verifying round-trip latency (you, not me - I don't have API keys)

The Stage 0 target is **speak -> hear a spoken response in under 2-3
seconds**. To check it once your `.env` has real keys:

1. Run `python bot.py -t daily` and join the room it prints.
2. Say a short, simple sentence ("The quick brown fox.") and start a stopwatch
   (or just count) the moment you stop talking.
3. Stop timing the moment you hear the bot start speaking back.
4. Repeat 3-5 times - the first turn is often slower (cold connections to
   Deepgram/Anthropic/Cartesia), so judge steady-state turns 2+.

If it's consistently over ~3s, check (roughly in likely-cause order):
- Network/region distance to Daily/Deepgram/Anthropic/Cartesia endpoints.
- `enable_metrics=True` is already set in `bot.py`'s `PipelineParams` -
  pipecat logs per-service timing (STT/LLM/TTS) to the console, which tells
  you which stage is actually slow instead of guessing.
- Whether Cartesia's default demo voice ID in `bot.py`
  (`DEFAULT_CARTESIA_VOICE_ID`) is doing anything unexpected - swap it for a
  voice ID from your own Cartesia account if so.

If the streaming pipeline turns out to be unreliable (dropped words, VAD
misfires, laggy turn-taking) rather than just slow, that's what
`push_to_talk_bot.py` is for - see its module docstring for the fallback
design and the TODOs to finish it.

## What gets emitted over the data channel

The full event contract (`contracts/voice_events.md`) is now produced live:
`word_recognized` as Deepgram finalizes each word, `miscue_detected` and
`hint_spoken` from backend/tutor's alignment engine as you read,
`passage_complete` once you finish, `comprehension_turn` (now including an
additive `feedback_text` field, added during integration) for each graded
answer, and `session_ended` at the close. All of it goes out over the Daily
data channel as urgent transport-message frames:

```json
{"type": "word_recognized", "t": 1234, "word": "fox", "start_ms": 1180, "end_ms": 1234, "confidence": 0.93}
```

You can see these by opening the browser dev console on the Daily room page
and inspecting `app-message` events, or by having a small script join the
room as a second participant and log incoming data-channel messages.

`voice_events.py` (renamed from `events.py` during integration - see the
build log for the module-name-collision bug that motivated it) still holds
the shared event-building/clock helper for `word_recognized`; the other four
event types are built by backend/tutor's own `events.py` and
`alignment.py`, imported into this pipeline via `tutor_processor.py`.

## Sanity-checking the code without API keys

```bash
python -m py_compile bot.py push_to_talk_bot.py voice_events.py tutor_processor.py mastery_client.py
python -c "import bot"                 # imports cleanly, no keys needed
python -c "import push_to_talk_bot"    # imports cleanly, no keys needed
```

Both bot modules only read `os.environ[...]` for API keys inside
`run_bot()`, which only runs once pipecat's runner actually starts a
session - so a plain `import` never needs real keys. Actually running a
session (`python bot.py -t daily`) does need them.
