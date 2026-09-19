"use client";

import { useMemo } from "react";
import { derivePunctuation } from "@/lib/passageText";
import type { Passage } from "@/lib/types";

export type WordStatus = "pending" | "current" | "correct" | "miscue";

export default function PassageDisplay({
  passage,
  wordStatuses,
  challengeWordIndex = null,
  challengeCleared = false,
  showChallengeCelebration = false,
}: {
  passage: Passage;
  /** Status per index into passage.words, same length/order as passage.words. */
  wordStatuses: WordStatus[];
  /** "Challenge word" gameplay - see docs/FEATURE_IDEAS.md. Index into
   * passage.words to mark specially, null if the passage has none. */
  challengeWordIndex?: number | null;
  /** True once the challenge word has been read correctly or self-corrected. */
  challengeCleared?: boolean;
  /** True only for the brief moment right after it clears, for a one-shot pop. */
  showChallengeCelebration?: boolean;
}) {
  // Display-only punctuation, aligned against passage.words positionally -
  // see lib/passageText.ts for why passage.words itself can never carry
  // punctuation (it has to match speech recognition output word-for-word).
  const punctuation = useMemo(
    () => derivePunctuation(passage.text, passage.words),
    [passage.text, passage.words]
  );

  return (
    <div className="rounded-[2rem] bg-gradient-to-br from-amber-50 via-white to-sky-50 p-5 shadow-lg ring-2 ring-sky-200/70 sm:p-8">
      <h1 className="flex items-center gap-2 font-[family-name:var(--font-kid)] text-xl font-bold text-slate-800 sm:text-2xl">
        <span aria-hidden>📖</span>
        {passage.title}
      </h1>
      {passage.selection_reason?.explanation && (
        <p className="mt-1 text-sm italic text-slate-500">
          {passage.selection_reason.explanation}
        </p>
      )}
      {/* Explicit text-left, not just relying on the browser's own left-as-
          default: a reported audit saw this render fully justified on a
          375px phone, producing the classic large/uneven inter-word gaps on
          short wrapped lines - bad for word-tracking for a beginning
          reader. Live re-check here (computed text-align, and measuring the
          actual gap between every rendered word span) found this element
          and its whole ancestor chain already computing to plain "start"
          with a uniform ~5px gap between every word regardless of line
          length, so the justify itself wasn't reproducible against the
          current build. Pinning text-left explicitly, rather than leaving
          it to inherit the default, means that stays true regardless of
          anything upstream (a future prose/typography wrapper, a global
          style change) rather than depending on nobody ever setting
          text-align on an ancestor. */}
      <p className="mt-5 text-left font-[family-name:var(--font-kid)] text-xl leading-loose tracking-wide text-slate-800 sm:mt-6 sm:text-2xl md:text-[1.75rem]">
        {passage.words.map((word, i) => {
          const isChallengeWord = i === challengeWordIndex;
          const challengeJustCleared = isChallengeWord && challengeCleared && showChallengeCelebration;
          return (
            <span key={i}>
              <span
                className={[
                  "relative inline-block rounded-lg px-1 py-0.5 transition-all duration-300 ease-out",
                  wordStyleFor(wordStatuses[i]),
                  isChallengeWord && challengeCleared
                    ? "ring-2 ring-amber-400 ring-offset-1"
                    : "",
                ].join(" ")}
                style={
                  challengeJustCleared
                    ? { animation: "word-pop 0.5s ease-out" }
                    : wordStatuses[i] === "current"
                      ? { animation: "word-pop 0.4s ease-out" }
                      : undefined
                }
              >
                {isChallengeWord && !challengeCleared && (
                  <span
                    className="absolute -top-3 left-1/2 -translate-x-1/2 text-xs"
                    style={{ animation: "word-pop 1.6s ease-in-out infinite" }}
                    aria-hidden
                  >
                    ⭐
                  </span>
                )}
                {isChallengeWord && challengeCleared && (
                  <span
                    className="absolute -top-3 left-1/2 -translate-x-1/2 text-xs"
                    aria-hidden
                  >
                    🌟
                  </span>
                )}
                {punctuation[i]?.before}
                {word}
                {punctuation[i]?.after}
                {wordStatuses[i] === "current" && (
                  <span
                    className="absolute -bottom-1 left-1/2 h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-sky-500"
                    aria-hidden
                  />
                )}
              </span>{" "}
            </span>
          );
        })}
      </p>
    </div>
  );
}

function wordStyleFor(status: WordStatus | undefined): string {
  switch (status) {
    case "current":
      return "bg-sky-300 text-slate-900 shadow-sm";
    case "correct":
      return "bg-emerald-100 text-slate-700";
    case "miscue":
      // Softer than a hard block fill - a warm underline so a stumble reads
      // as "let's look at this one again", not a red-marked wrong answer.
      return "bg-amber-100 text-slate-800 underline decoration-amber-400 decoration-wavy decoration-2 underline-offset-4";
    default:
      return "text-slate-400";
  }
}
