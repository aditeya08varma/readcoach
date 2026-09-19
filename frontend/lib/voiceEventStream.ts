// Voice event source abstraction for contracts/voice_events.md.
//
// Two implementations: createMockVoiceEventSource (a scripted timer, used
// for UI development and the demo-safe fallback) and
// createLiveVoiceEventSource (the real thing - connects to the actual
// running voice bot in backend/voice/ over WebRTC and receives its real
// event stream). ReadingScreen only depends on the VoiceEventSource
// interface below, so callers don't need to know which one they're using.
//
// This used to be documented as "not built yet, here's the swap plan" - it
// stayed that way through this entire project until this pass, when it
// became clear the polished reading screen had only ever been exercised
// against the mock timer, never against a real session, despite the real
// voice bot itself working (see docs/BUILD_LOG.md). Building this surfaced
// a real, previously undiscovered bug in backend/voice/tutor_processor.py:
// `_emit` built a Daily-specific message frame directly, which silently
// never got delivered under the WebRTC transport (`-t webrtc`) - the only
// transport ever actually tested with a live client. Fixed there by routing
// through Pipecat's RTVIProcessor.send_server_message, the transport-
// agnostic, officially supported way to reach a connected
// @pipecat-ai/client-js client. Verified for real: a temporary test event
// was pushed from the running bot and confirmed to arrive intact on a
// bare-bones test client before this file was written.
//
// Note the contract's "turn-based fallback mode": events may arrive in
// bursts rather than one at a time, so consumers must not assume real-time
// cadence between events.

import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import type { Passage, VoiceEvent } from "./types";
import { VoiceEventSchema } from "./schemas";

const VOICE_BOT_URL =
  process.env.NEXT_PUBLIC_VOICE_BOT_URL?.replace(/\/$/, "") ||
  "http://localhost:7860";

export interface VoiceEventSource {
  start(): void | Promise<void>;
  // Returns a promise so callers can wait for real teardown (releasing the
  // mic, closing the peer connection) to actually finish before starting a
  // new session - see createLiveVoiceEventSource's stop() for the real bug
  // this exists to prevent: starting a fresh connection before the old
  // one's microphone/peer connection has actually been released.
  stop(): void | Promise<void>;
}

export type VoiceEventHandler = (event: VoiceEvent) => void;

interface MockPlaybackOptions {
  /** ms between finalized words, roughly matching a child's oral reading rate. */
  msPerWord?: number;
  /** Fraction of words that get a simulated miscue right before they're recognized. */
  miscueRate?: number;
}

/**
 * Mock VoiceEventSource: walks the passage's `words` array on a timer and
 * emits `word_recognized` (plus occasional `miscue_detected` /
 * `hint_spoken`) events matching the exact shapes in
 * contracts/voice_events.md, ending in `passage_complete`. This is what
 * drives the reading screen's live word highlight today, before the real
 * Daily/Pipecat voice pipeline is wired in.
 */
export function createMockVoiceEventSource(
  passage: Passage,
  onEvent: VoiceEventHandler,
  options: MockPlaybackOptions = {}
): VoiceEventSource {
  const { msPerWord = 420, miscueRate = 0.12 } = options;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  let elapsed = 0;
  let selfCorrections = 0;
  let miscueCount = 0;
  // Real feedback from a real reading session (see docs/BUILD_LOG.md): a
  // hint interjected mid-word read as talking over the child, not helping.
  // The real backend now teaches every real stumble in one pass after the
  // whole passage is read, asking the child to say it again to confirm -
  // this mock mirrors that exact pacing (queue during reading, teach during
  // review) rather than the old immediate/delayed mid-read hint.
  const reviewQueue: { index: number; word: string; skillId: string }[] = [];

  function scheduleWord(index: number) {
    if (stopped || index >= passage.words.length) {
      if (!stopped) {
        const durationMinutes = elapsed / 60000;
        const wordsCorrect = passage.words.length - miscueCount;
        const wcpm =
          durationMinutes > 0
            ? Math.round(wordsCorrect / durationMinutes)
            : wordsCorrect;
        const accuracy =
          Math.round(
            ((passage.words.length - miscueCount) / passage.words.length) * 100
          ) / 100;
        emit({
          type: "passage_complete",
          t: elapsed,
          wcpm,
          accuracy,
          self_corrections: selfCorrections,
        });
        runReview();
      }
      return;
    }

    const jitter = Math.round(msPerWord * (Math.random() * 0.5 - 0.25));
    const delay = Math.max(120, msPerWord + jitter);

    timer = setTimeout(() => {
      elapsed += delay;
      const word = passage.words[index];
      const isMiscue = Math.random() < miscueRate && word.length > 2;

      if (isMiscue) {
        miscueCount += 1;
        const isSelfCorrection = Math.random() < 0.4;
        if (isSelfCorrection) selfCorrections += 1;
        const skillId = passage.primary_skill || passage.skills[0] || "unknown";
        emit({
          type: "miscue_detected",
          t: elapsed,
          reference_index: index,
          reference_word: word,
          spoken_word: fuzzMisread(word),
          miscue_type: isSelfCorrection ? "self_correction" : "substitution",
          skill_id: skillId,
        });

        // Self-corrections already show the child caught it themselves -
        // only real, uncorrected stumbles get queued for review.
        if (!isSelfCorrection) {
          reviewQueue.push({ index, word, skillId });
        }
      }

      emit({
        type: "word_recognized",
        t: elapsed,
        word,
        start_ms: elapsed - Math.round(delay * 0.6),
        end_ms: elapsed,
        confidence: isMiscue ? 0.62 + Math.random() * 0.15 : 0.85 + Math.random() * 0.14,
      });

      scheduleWord(index + 1);
    }, delay);
  }

  function runReview() {
    if (stopped || reviewQueue.length === 0) return;
    let i = 0;
    const teachNext = () => {
      if (stopped || i >= reviewQueue.length) return;
      const item = reviewQueue[i];
      elapsed += Math.round(msPerWord * 1.2);
      emit({
        type: "hint_spoken",
        t: elapsed,
        skill_id: item.skillId,
        text: `Let's sound that one out: ${item.word}.`,
      });
      timer = setTimeout(() => {
        if (stopped) return;
        elapsed += Math.round(msPerWord * 1.8);
        emit({
          type: "review_word_result",
          t: elapsed,
          reference_index: item.index,
          reference_word: item.word,
          correct: true,
        });
        i += 1;
        teachNext();
      }, Math.round(msPerWord * 2.5));
    };
    teachNext();
  }

  function emit(event: VoiceEvent) {
    if (!stopped) onEvent(event);
  }

  return {
    start() {
      stopped = false;
      elapsed = 0;
      selfCorrections = 0;
      miscueCount = 0;
      reviewQueue.length = 0;
      scheduleWord(0);
    },
    stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
    },
  };
}

function fuzzMisread(word: string): string {
  if (word.length <= 3) return word.slice(0, 1) + "..";
  return word.slice(0, Math.max(2, word.length - 2)) + "..";
}

export type LiveVoiceStatus =
  | "connecting"
  | "ready"
  | "error"
  | "disconnected";

export interface LiveVoiceCallbacks {
  onStatus?: (status: LiveVoiceStatus, detail?: string) => void;
}

/**
 * Real VoiceEventSource: connects to the actual running voice bot
 * (backend/voice/bot.py) over WebRTC using Pipecat's client SDK, and
 * forwards its real event stream - which already arrives in exactly the
 * contracts/voice_events.md shape, since that's the same dict `_emit`
 * builds server-side - straight to `onEvent`, no translation needed.
 *
 * Requires the bot process to already be running (see backend/voice/README.md)
 * and reachable at NEXT_PUBLIC_VOICE_BOT_URL (defaults to
 * http://localhost:7860, the Pipecat dev runner's default). If it isn't
 * running, `connect()` rejects and `onStatus("error", ...)` fires - callers
 * should fall back to the mock source rather than leave the screen stuck.
 *
 * `passageId`, when given, is a real person's explicit story choice (the
 * story map's tap-a-node flow - see docs/FEATURE_IDEAS.md's gameplay
 * ideation). It's sent via `POST /choose_passage` on the bot's own server
 * immediately before connecting - not through the WebRTC connection
 * request's own custom-data option, which was tried first and confirmed
 * empirically broken in this client/server version combination (see
 * contracts/api_contract.md's GET /students/{id}/passages/{passage_id}
 * entry for the full story of that dead end).
 *
 * `studentId`, when given, is the real logged-in parent's own student
 * (see frontend/auth.ts / docs/BUILD_LOG.md's auth writeup) - sent the exact
 * same way, via `POST /choose_student` right before connecting, so the bot
 * resolves this specific real student instead of always defaulting to the
 * one shared demo student (backend/voice/mastery_client.py's
 * _get_or_create_demo_student). Absent (e.g. no session yet), the bot falls
 * back to the demo student exactly as it always did before login existed.
 *
 * Both choices are tagged with a session id minted right here, right before
 * either POST fires, and that same id rides along as `?session_id=` on the
 * WebRTC connection below - Pipecat's own runner already accepts and
 * forwards that param to `run_bot()` as `runner_args.session_id`. This is
 * what lets the bot key its pending-choice state per connection instead of
 * one shared global: two real browser tabs starting a session close
 * together used to be able to steal each other's chosen passage/student
 * (tab B's choose_passage call overwriting tab A's before A's own
 * connection had consumed it) - a real, confirmed race, not a hypothetical
 * one (see bot.py's own comment on _pending_passage_choice for the full
 * writeup).
 */
export function createLiveVoiceEventSource(
  onEvent: VoiceEventHandler,
  callbacks: LiveVoiceCallbacks = {},
  passageId?: string,
  studentId?: string
): VoiceEventSource {
  let client: PipecatClient | null = null;
  let audioEl: HTMLAudioElement | null = null;
  let stopped = false;

  return {
    async start() {
      stopped = false;
      callbacks.onStatus?.("connecting");

      const sessionId = crypto.randomUUID();

      await Promise.all([
        passageId
          ? fetch(`${VOICE_BOT_URL}/choose_passage`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ passage_id: passageId, session_id: sessionId }),
            }).catch((err) => {
              // Best-effort: if this fails, the bot just falls back to
              // auto-selecting its own passage below, same as if no story had
              // been explicitly chosen at all - not fatal to starting a session.
              console.warn("[voice] failed to set chosen passage, bot will auto-select instead:", err);
            })
          : Promise.resolve(),
        studentId
          ? fetch(`${VOICE_BOT_URL}/choose_student`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ student_id: studentId, session_id: sessionId }),
            }).catch((err) => {
              console.warn("[voice] failed to set chosen student, bot will use the demo student instead:", err);
            })
          : Promise.resolve(),
      ]);
      if (stopped) return; // stop() was called while the requests above were in flight

      audioEl = document.createElement("audio");
      audioEl.autoplay = true;
      // Not visually part of the UI - this element exists purely to give
      // the browser somewhere to play the bot's real TTS audio out loud.
      audioEl.style.display = "none";
      document.body.appendChild(audioEl);

      const pcClient = new PipecatClient({
        transport: new SmallWebRTCTransport(),
        enableMic: true,
        enableCam: false,
        callbacks: {
          onBotReady: () => {
            if (!stopped) callbacks.onStatus?.("ready");
          },
          onDisconnected: () => {
            if (!stopped) callbacks.onStatus?.("disconnected");
          },
          onServerMessage: (data: unknown) => {
            if (stopped) return;
            // Real gap found by audit: this used to trust `data as VoiceEvent`
            // with zero runtime check, so a payload that drifted from
            // contracts/voice_events.md (a backend bug, a mid-session
            // contract change, a stray non-event message on the same data
            // channel) would flow straight into handleEvent's switch and
            // either silently no-op on the `default` branch or, worse, hit a
            // field that doesn't actually exist and throw deep inside a
            // component. The connection itself is otherwise healthy here
            // (this isn't a connect/disconnect failure - see onError/
            // onDisconnected below for that), so the safe response to one bad
            // message is to log it clearly and drop just that message, not
            // tear down the whole live session into the mock fallback.
            const parsed = VoiceEventSchema.safeParse(data);
            if (!parsed.success) {
              // console.warn, not console.error: this is a deliberately
              // tolerated path (see the comment above) - one bad/unrecognized
              // message gets dropped and the session keeps running. Real bug
              // found live: Next.js 16 dev mode intercepts console.error
              // specifically and throws up a blocking red overlay, which
              // directly undoes the "log clearly and keep going without
              // disrupting the session" intent this code already had -
              // Pipecat's own RTVI protocol sends its own internal control
              // messages over this same data channel (bot-ready, connection
              // state, etc.) that were never meant to match our 8 custom
              // event types, so this path fires routinely on a real
              // connection, not just on a genuine contract drift.
              console.warn(
                "[voice] received a server message that failed validation, ignoring it:",
                parsed.error.issues,
                data
              );
              return;
            }
            onEvent(parsed.data);
          },
          onTrackStarted: (track, participant) => {
            // Only the bot's own audio track, never our own mic echoed back
            // (see @pipecat-ai/client-react's PipecatClientAudio, which this
            // mirrors without pulling in the React package for one element).
            if (!stopped && track.kind === "audio" && !participant?.local && audioEl) {
              audioEl.srcObject = new MediaStream([track]);
            }
          },
          onError: (message) => {
            if (!stopped) callbacks.onStatus?.("error", String(message));
          },
        },
      });
      client = pcClient;

      pcClient
        // Real bug found live (see docs/BUILD_LOG.md): this was `connection_url`
        // (snake_case), which SmallWebRTCTransportConnectionOptions has never
        // recognized - only `connectionUrl` (deprecated but functional) or
        // `webrtcRequestParams` (current). The wrong key meant `.connect()`
        // silently got no real URL at all, so every real-bot attempt failed
        // regardless of the CORS fix. Using the deprecated-but-still-working
        // `connectionUrl` key here as the fast, guaranteed-correct fix under
        // time pressure - migrating to `webrtcRequestParams` is real cleanup
        // work for later, not blocking on it now.
        .connect({ connectionUrl: `${VOICE_BOT_URL}/api/offer?session_id=${sessionId}` })
        .catch((err: unknown) => {
          if (!stopped) {
            callbacks.onStatus?.(
              "error",
              err instanceof Error ? err.message : String(err)
            );
          }
        });
    },
    async stop() {
      stopped = true;
      // Real bug found from real "Read Again" testing: this used to fire
      // disconnect() without waiting for it, so a fresh connect() (and a
      // fresh getUserMedia() mic request) could start before the old peer
      // connection and microphone were actually released - a real race
      // between tearing down one WebRTC/mic session and starting the next.
      // Awaiting it here doesn't fully rule that out as the cause (this
      // environment's tooling can't grant real microphone access to test
      // an actual reconnect end to end), but it closes a real, confirmed
      // race regardless of whether it was the whole story.
      const pending = client?.disconnect().catch(() => {});
      client = null;
      audioEl?.remove();
      audioEl = null;
      await pending;
    },
  };
}
