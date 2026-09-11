"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import type { MiscueType, Passage, VoiceEvent } from "@/lib/types";
import {
  createLiveVoiceEventSource,
  createMockVoiceEventSource,
  type LiveVoiceStatus,
  type VoiceEventSource,
} from "@/lib/voiceEventStream";
import { celebrate, playPop } from "@/lib/confettiPop";
import PlumpButton from "@/components/ui/PlumpButton";
import PassageDisplay, { type WordStatus } from "./PassageDisplay";
import VoiceIndicator, { type VoiceState } from "./VoiceIndicator";

interface Summary {
  wcpm: number;
  accuracy: number;
  self_corrections: number;
}

export default function ReadingScreen({
  passage: initialPassage,
  chosenPassageId,
  onNextStory,
  studentId,
}: {
  passage: Passage;
  // A real person's explicit story choice (the story map's tap-a-node flow,
  // docs/FEATURE_IDEAS.md's gameplay ideation) - passed through to the live
  // bot via POST /choose_passage (see lib/voiceEventStream.ts). Undefined
  // means auto-select, exactly like before this feature existed.
  chosenPassageId?: string;
  // Real gap found: after finishing a passage, "Read Again" (the same
  // story) was the only option offered. The page owns fetching a fresh
  // auto-selected passage since that's the same data-access layer every
  // other screen already goes through.
  onNextStory?: () => void;
  // The real logged-in parent's own student (see frontend/auth.ts) - passed
  // through to the live bot via POST /choose_student (see
  // lib/voiceEventStream.ts) so a real session updates this specific
  // student's real mastery, not the shared demo student. Undefined falls
  // back to the demo student, same as before login existed.
  studentId?: string;
}) {
  // Real bug found during real testing, fixed here: this screen used to
  // always render whatever passage the page fetched for itself, completely
  // unrelated to whichever passage the real voice bot actually picked for
  // the live session - the child would see one story while the bot listened
  // for a different one, misreading almost every word as a miscue. The bot
  // now announces its real passage via `passage_loaded` (contracts/
  // voice_events.md) the moment it connects, and that becomes authoritative
  // the instant it arrives. Mock mode never emits this event, so `passage`
  // correctly stays whatever the page fetched, unchanged from before.
  const [livePassage, setLivePassage] = useState<Passage | null>(null);
  const passage = livePassage ?? initialPassage;

  // Word statuses are derived from two pieces of state rather than mutated
  // directly: `recognizedCount` (how many word_recognized events have landed
  // - contracts/voice_events.md doesn't put a reference index on that event,
  // only on miscue_detected, so the mock's in-order emission plus a running
  // count is enough to align) and `miscueIndices` (which reference indices
  // got flagged). Deriving avoids a bug where a miscue_detected event and the
  // word_recognized event for the same word - which the mock, and the real
  // aligner, both emit back-to-back - would otherwise race to set that
  // word's status and the miscue mark could get clobbered back to "correct".
  const [recognizedCount, setRecognizedCount] = useState(0);
  const [miscueIndices, setMiscueIndices] = useState<Set<number>>(new Set());
  const [isComplete, setIsComplete] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [hint, setHint] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [started, setStarted] = useState(false);
  // Real bug found from a real recording: `started` flips true on the very
  // first click, before anything has actually been read once - showing
  // "Read Again" while the very first read is still in progress. This
  // tracks whether a read has ever actually finished, deliberately never
  // reset by handleStart (only a fresh page/passage should clear it), so the
  // label stays "Start Reading" through the whole first read and only
  // switches once there's something to genuinely read "again".
  const [hasCompletedOnce, setHasCompletedOnce] = useState(false);
  // "Challenge word" gameplay - see docs/FEATURE_IDEAS.md. The reading
  // screen already knows, from the word-by-word event stream alone, which
  // index is marked as the challenge word (passage.challenge_word_index)
  // and whether that specific index resolved to a miscue or a self
  // correction, so "cleared" is purely a local derivation - no new voice
  // event or backend/voice change needed for this.
  const [challengeWordMiscueType, setChallengeWordMiscueType] = useState<MiscueType | null>(null);
  const [showChallengeCelebration, setShowChallengeCelebration] = useState(false);
  const wasChallengeClearedRef = useRef(false);
  // Real vs simulated reading (see lib/voiceEventStream.ts). Defaults to
  // attempting the real bot every time - if it can't be reached, this falls
  // back to the mock automatically rather than leaving the screen stuck, but
  // says so explicitly rather than silently pretending it's live.
  const [sourceMode, setSourceMode] = useState<"live" | "mock">("live");
  const [liveStatus, setLiveStatus] = useState<LiveVoiceStatus | null>(null);
  const [fellBackToMock, setFellBackToMock] = useState(false);
  const sourceRef = useRef<VoiceEventSource | null>(null);
  const hintTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const challengeCelebrationTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const challengeIndex = passage.challenge_word_index ?? null;
  // Cleared once we've read past it and either never flagged a miscue there
  // at all (plain correct read) or the miscue there was specifically a self
  // correction (catching your own mistake is a win here, not a miss - same
  // stance the mastery model already takes, see backend/mastery/mastery.py).
  // A real, uncorrected substitution/omission/insertion leaves this false
  // for the rest of the session - the existing miscue styling already
  // covers that case, no extra "missed" treatment needed.
  const challengeCleared =
    challengeIndex !== null &&
    recognizedCount > challengeIndex &&
    (challengeWordMiscueType === null || challengeWordMiscueType === "self_correction");

  const wordStatuses = useMemo<WordStatus[]>(() => {
    // Once the passage is complete there's no more "current" word - every
    // recognized word settles to correct/miscue instead of the last one
    // staying stuck highlighted as in-progress.
    const lastIsCurrent = !isComplete;
    return passage.words.map((_, i) => {
      if (miscueIndices.has(i)) return "miscue";
      if (i < recognizedCount - 1) return "correct";
      if (i === recognizedCount - 1) return lastIsCurrent ? "current" : "correct";
      return "pending";
    });
  }, [passage.words, recognizedCount, miscueIndices, isComplete]);

  useEffect(() => {
    return () => {
      sourceRef.current?.stop();
      if (hintTimeoutRef.current) clearTimeout(hintTimeoutRef.current);
      if (challengeCelebrationTimeoutRef.current) clearTimeout(challengeCelebrationTimeoutRef.current);
    };
  }, []);


  useEffect(() => {
    if (challengeCleared && !wasChallengeClearedRef.current) {
      setShowChallengeCelebration(true);
      if (challengeCelebrationTimeoutRef.current) clearTimeout(challengeCelebrationTimeoutRef.current);
      challengeCelebrationTimeoutRef.current = setTimeout(() => setShowChallengeCelebration(false), 1800);
    }
    wasChallengeClearedRef.current = challengeCleared;
  }, [challengeCleared]);

  function handleEvent(event: VoiceEvent) {
    switch (event.type) {
      case "passage_loaded": {
        setLivePassage(event.passage);
        break;
      }
      case "word_recognized": {
        setRecognizedCount((c) => Math.min(c + 1, passage.words.length));
        setVoiceState("listening");
        break;
      }
      case "miscue_detected": {
        setMiscueIndices((prev) => {
          const next = new Set(prev);
          next.add(event.reference_index);
          return next;
        });
        if (event.reference_index === challengeIndex) {
          setChallengeWordMiscueType(event.miscue_type);
        }
        break;
      }
      case "hint_spoken": {
        setVoiceState("speaking");
        setHint(event.text);
        if (hintTimeoutRef.current) clearTimeout(hintTimeoutRef.current);
        hintTimeoutRef.current = setTimeout(() => {
          setHint(null);
          setVoiceState("listening");
        }, 2200);
        break;
      }
      case "passage_complete": {
        setRecognizedCount(passage.words.length);
        setIsComplete(true);
        setHasCompletedOnce(true);
        setVoiceState("done");
        setSummary({
          wcpm: event.wcpm,
          accuracy: event.accuracy,
          self_corrections: event.self_corrections,
        });
        // Real bug found from a real recording: a hint that was still mid-
        // timeout when the passage finished kept showing on screen at the
        // same time as the "Great reading!" summary - two contradictory
        // states shown together. The session is over, so any coaching tip
        // about the read that's now finished is no longer relevant.
        if (hintTimeoutRef.current) clearTimeout(hintTimeoutRef.current);
        setHint(null);
        break;
      }
      default:
        break;
    }
  }

  async function handleStart() {
    setStarted(true);
    setSummary(null);
    setHint(null);
    setRecognizedCount(0);
    setMiscueIndices(new Set());
    setChallengeWordMiscueType(null);
    setShowChallengeCelebration(false);
    wasChallengeClearedRef.current = false;
    setIsComplete(false);
    setFellBackToMock(false);
    setLiveStatus(null);
    // Reset to the page's own fetched passage - if the previous attempt was
    // live, this clears its passage_loaded result rather than leaving stale
    // data from a prior session visible during/after a fresh one.
    setLivePassage(null);
    // Real bug found from real "Read Again" testing: a fresh connection
    // used to start before the previous one's microphone and peer
    // connection had actually finished being released, a real race between
    // tearing down one live session and starting the next. Awaiting the
    // old source's teardown first closes that race - see
    // createLiveVoiceEventSource's stop() for the other half of this fix.
    await sourceRef.current?.stop();

    if (sourceMode === "mock") {
      setVoiceState("listening");
      // Explicitly initialPassage, not the possibly-stale `passage` const
      // from this render's closure (a live session moments ago could have
      // set it to something else; setLivePassage(null) above won't be
      // visible until the next render).
      const source = createMockVoiceEventSource(initialPassage, handleEvent);
      sourceRef.current = source;
      source.start();
      return;
    }

    setVoiceState("idle");

    const source = createLiveVoiceEventSource(handleEvent, {
      onStatus: async (status, detail) => {
        setLiveStatus(status);
        if (status === "error") {
          console.warn("[voice] live bot unreachable, falling back to simulated reading:", detail);
          await sourceRef.current?.stop();
          setFellBackToMock(true);
          setVoiceState("listening");
          const mock = createMockVoiceEventSource(initialPassage, handleEvent);
          sourceRef.current = mock;
          mock.start();
        }
      },
    }, chosenPassageId, studentId);
    sourceRef.current = source;
    source.start();
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 sm:gap-6">
      <VoiceIndicator state={voiceState} />

      {hint && (
        <div
          className="relative ml-2 max-w-lg rounded-2xl rounded-tl-sm bg-gradient-to-br from-amber-50 to-amber-100 px-4 py-3 text-amber-900 shadow-sm ring-1 ring-amber-200"
          style={{ animation: "bubble-in 0.25s ease-out" }}
        >
          <span className="mb-0.5 flex items-center gap-1.5 font-[family-name:var(--font-kid)] text-sm font-bold text-amber-700">
            <span aria-hidden>💡</span> Coach says
          </span>
          <p className="font-[family-name:var(--font-kid)] text-base leading-snug">{hint}</p>
        </div>
      )}

      <PassageDisplay
        passage={passage}
        wordStatuses={wordStatuses}
        challengeWordIndex={challengeIndex}
        challengeCleared={challengeCleared}
        showChallengeCelebration={showChallengeCelebration}
      />

      {!started && (
        <label className="flex w-fit items-center gap-2 self-start rounded-full bg-white/90 px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm">
          <input
            type="checkbox"
            checked={sourceMode === "mock"}
            onChange={(e) => setSourceMode(e.target.checked ? "mock" : "live")}
            className="h-3.5 w-3.5"
          />
          Use simulated demo instead of the real voice bot
        </label>
      )}

      {sourceMode === "live" && liveStatus === "connecting" && (
        <p className="w-fit rounded-full bg-white/90 px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm">
          Connecting to the voice bot...
        </p>
      )}
      {sourceMode === "live" && liveStatus === "ready" && (
        <p className="w-fit rounded-full bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700 shadow-sm ring-1 ring-emerald-200">
          Connected - start reading out loud whenever you&apos;re ready.
        </p>
      )}
      {fellBackToMock && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 ring-1 ring-amber-200">
          Couldn&apos;t reach the real voice bot at {" "}
          <code className="text-xs">localhost:7860</code> - switched to a simulated
          reading instead. Make sure <code className="text-xs">bot.py</code> is
          running if you want the real thing.
        </p>
      )}

      <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
          <PlumpButton
            variant="secondary"
            pop="primary"
            onClick={handleStart}
            disabled={voiceState === "listening" || voiceState === "speaking"}
          >
            <span aria-hidden>{hasCompletedOnce ? "🔁" : "🎤"}</span>
            {hasCompletedOnce ? "Read Again" : "Start Reading"}
          </PlumpButton>

          {isComplete && (
            <>
              {onNextStory && (
                <PlumpButton variant="white" pop="secondary" onClick={onNextStory}>
                  <span aria-hidden>➡️</span>
                  Next Story
                </PlumpButton>
              )}
              <Link
                href="/map"
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  celebrate(rect.left + rect.width / 2, rect.top + rect.height / 2, 14);
                  playPop("small");
                }}
                className="inline-flex items-center justify-center gap-2 rounded-3xl px-6 py-3.5 font-[family-name:var(--font-kid)] text-lg font-bold text-white/90 drop-shadow-sm transition hover:scale-[1.02] hover:text-white active:scale-[0.96]"
              >
                <span aria-hidden>🗺️</span>
                Choose a Story
              </Link>
            </>
          )}
        </div>

        {summary && (
          <div
            className="grid grid-cols-3 gap-2 sm:gap-3"
            style={{ animation: "fade-up 0.3s ease-out" }}
          >
            <SummaryTile icon="⏱️" value={String(summary.wcpm)} label="wcpm" />
            <SummaryTile
              icon="🎯"
              value={`${Math.round(summary.accuracy * 100)}%`}
              label="accuracy"
            />
            <SummaryTile
              icon="🔁"
              value={String(summary.self_corrections)}
              label="self-fixes"
            />
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryTile({ icon, value, label }: { icon: string; value: string; label: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 rounded-2xl bg-emerald-50 px-3 py-2.5 text-center ring-1 ring-emerald-200 sm:flex-row sm:gap-2 sm:px-4">
      <span aria-hidden className="text-base">
        {icon}
      </span>
      <span className="font-[family-name:var(--font-kid)] text-sm text-emerald-900">
        <strong className="text-base">{value}</strong>{" "}
        <span className="text-xs text-emerald-700">{label}</span>
      </span>
    </div>
  );
}
