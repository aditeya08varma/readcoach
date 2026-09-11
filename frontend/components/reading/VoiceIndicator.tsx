"use client";

import PenguinMascot from "./PenguinMascot";

export type VoiceState = "idle" | "listening" | "thinking" | "speaking" | "done";

const STATE_COPY: Record<VoiceState, { label: string }> = {
  idle: { label: "Ready when you are" },
  listening: { label: "Listening to you read..." },
  // Mastery-aware hint pacing, made visible (docs/FEATURE_IDEAS.md) - shown
  // the moment the tutor deliberately holds a hint back instead of jumping
  // in, so that decision reads as "the coach is giving you a chance" rather
  // than a silent, unexplained pause.
  thinking: { label: "Giving you a moment to try that one..." },
  speaking: { label: "Coach is talking" },
  done: { label: "Great reading!" },
};

// Per-state visuals: each state gets its own ring color and backdrop, so
// "listening" vs "speaking" vs "done" feel like distinct moods rather than
// the same bounce recolored. The mascot's own animation now lives on its
// own SVG parts (see PenguinMascot.tsx + globals.css's .penguin-* rules)
// instead of a single avatarAnim class wrapping a flat emoji.
const STATE_STYLES: Record<VoiceState, { ring: string; avatarBg: string; bar: string; wrapAnim: string }> = {
  idle: {
    ring: "ring-slate-200",
    avatarBg: "bg-white",
    bar: "bg-slate-300",
    wrapAnim: "",
  },
  listening: {
    ring: "ring-sky-300",
    avatarBg: "bg-white",
    bar: "bg-sky-400",
    wrapAnim: "animate-[listen-pulse_1.6s_ease-in-out_infinite]",
  },
  thinking: {
    ring: "ring-amber-300",
    avatarBg: "bg-white",
    bar: "bg-amber-400",
    wrapAnim: "animate-[listen-pulse_1.6s_ease-in-out_infinite]",
  },
  speaking: {
    ring: "ring-violet-300",
    avatarBg: "bg-white",
    bar: "bg-violet-400",
    wrapAnim: "animate-[speak-glow_1.2s_ease-in-out_infinite]",
  },
  done: {
    ring: "ring-emerald-300",
    avatarBg: "bg-white",
    bar: "bg-emerald-400",
    wrapAnim: "",
  },
};

/**
 * A friendly coach avatar + small waveform. Not the differentiator (the
 * voice interaction is), so no elaborate animation system — but each state
 * gets a distinct color + motion so a 6-8 year old can tell "the coach is
 * listening" from "the coach is talking" without reading the label.
 */
export default function VoiceIndicator({ state }: { state: VoiceState }) {
  const copy = STATE_COPY[state];
  const styles = STATE_STYLES[state];
  const active = state === "listening" || state === "thinking" || state === "speaking";

  return (
    <div
      className={`flex items-center gap-4 rounded-3xl bg-[#fffaf0] px-5 py-4 shadow-md ring-2 transition-all duration-300 sm:gap-5 sm:px-6 sm:py-5 ${styles.ring} ${styles.wrapAnim}`}
    >
      <div className="relative shrink-0">
        <div
          className={`flex h-20 w-20 items-center justify-center rounded-full shadow-sm transition-colors duration-300 sm:h-24 sm:w-24 ${styles.avatarBg}`}
        >
          <PenguinMascot state={state} className="h-16 w-16 sm:h-20 sm:w-20" />
        </div>
        {state === "done" && (
          <>
            <span
              className="absolute -right-1 -top-1 text-sm animate-[sparkle_1.4s_ease-in-out_infinite]"
              aria-hidden
            >
              ✨
            </span>
            <span
              className="absolute -bottom-1 -left-1 text-xs animate-[sparkle_1.4s_ease-in-out_infinite_0.3s]"
              aria-hidden
            >
              ✨
            </span>
          </>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
        <p className="font-[family-name:var(--font-kid)] text-base font-semibold text-slate-700 sm:text-lg">
          {copy.label}
        </p>
        <div className="flex h-8 items-end gap-1" aria-hidden>
          {Array.from({ length: 5 }).map((_, i) => (
            <span
              key={i}
              className={`w-1.5 rounded-full transition-colors duration-300 ${styles.bar} ${
                active ? "animate-[waveform_1s_ease-in-out_infinite]" : ""
              }`}
              style={{
                height: active ? undefined : "6px",
                animationDelay: `${i * 0.1}s`,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
