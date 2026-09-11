"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { getNextPassage, getPassageById } from "@/lib/api";
import type { DataSource, Passage } from "@/lib/types";
import ReadingScreen from "@/components/reading/ReadingScreen";
import DataSourceBadge from "@/components/DataSourceBadge";

export default function ReadPage() {
  return (
    <Suspense>
      <ReadPageInner />
    </Suspense>
  );
}

function ReadPageInner() {
  // A real person's explicit story choice (the story map's tap-a-node flow,
  // docs/FEATURE_IDEAS.md's gameplay ideation) arrives as ?passage_id=... -
  // absent, this page auto-selects exactly as before.
  const chosenPassageId = useSearchParams().get("passage_id") ?? undefined;
  const router = useRouter();
  const { data: session, status } = useSession();
  const studentId = session?.user?.studentId;
  const [passage, setPassage] = useState<Passage | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated" || !studentId) return;
    let cancelled = false;
    const request = chosenPassageId
      ? getPassageById(studentId, chosenPassageId)
      : getNextPassage(studentId);
    request
      .then((result) => {
        if (cancelled) return;
        setPassage(result.data);
        setSource(result.source);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [status, studentId, chosenPassageId]);

  // A real gap: after finishing a passage, the only offered action was
  // "Read Again" (the same story). This fetches a fresh auto-selected next
  // passage exactly like the very first page load would, dropping any
  // explicit ?passage_id= so the URL and the auto-select vs. chosen
  // distinction stay honest. ReadingScreen is keyed on passage.id below so
  // swapping passage fully remounts it - a clean reset with no new
  // reset-state logic needed there.
  async function handleNextStory() {
    if (!studentId) return;
    setError(null);
    setPassage(null);
    router.replace("/read");
    try {
      const result = await getNextPassage(studentId);
      setPassage(result.data);
      setSource(result.source);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    // Full-page gradient, min-h-screen, same saturation the whole way down -
    // not a colorful band up top fading into a pale or plain body. See
    // docs/BUILD_LOG.md for why this replaced the earlier pale-tint version.
    <main className="min-h-screen bg-gradient-to-b from-sky-400 via-sky-300 to-amber-300 px-4 py-8 sm:py-10">
      <div className="mx-auto mb-6 flex max-w-3xl items-center justify-between">
        <Link
          href="/"
          className="text-sm font-medium text-white/80 transition hover:text-white"
        >
          &larr; Home
        </Link>
        <div className="flex items-center gap-4">
          <DataSourceBadge source={source} />
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="text-sm font-medium text-white/80 transition hover:text-white"
          >
            Sign out
          </button>
        </div>
      </div>

      {error && (
        <p className="mx-auto max-w-3xl rounded-xl bg-rose-50 p-4 text-rose-800 ring-1 ring-rose-200">
          Could not load a passage: {error}
        </p>
      )}

      {!error && !passage && (
        <div className="mx-auto flex max-w-3xl flex-col items-center gap-3 py-16 text-center">
          <span className="animate-bounce text-3xl" aria-hidden>
            📚
          </span>
          <p className="font-[family-name:var(--font-kid)] text-lg font-medium text-white drop-shadow-sm">
            Finding your next story...
          </p>
        </div>
      )}

      {passage && (
        <ReadingScreen
          key={passage.id}
          passage={passage}
          chosenPassageId={chosenPassageId}
          onNextStory={handleNextStory}
          studentId={studentId}
        />
      )}
    </main>
  );
}
