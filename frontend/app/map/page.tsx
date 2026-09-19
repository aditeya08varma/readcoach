"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { getStoryMap } from "@/lib/api";
import type { DataSource, StoryMap } from "@/lib/types";
import StoryMapView from "@/components/map/StoryMapView";
import DataSourceBadge from "@/components/DataSourceBadge";
import Logo from "@/components/ui/Logo";
// Same shared narrative file StoryMapView reads its category taglines and
// milestone text from - one file, so the overall journey line below never
// tells a different story than the per-category copy right underneath it.
import storyNarrative from "../../../content/story_narrative.json";

// The child's real overall progress: a plain average of every real mastery
// weight already sitting in the fetched story map, not a new metric and not
// a new request - storyMap is already client-side by the time this page
// ever renders it. An empty map (no skills at all) reads as 0 progress
// rather than dividing by zero.
function overallProgress(storyMap: StoryMap): number {
  let total = 0;
  let count = 0;
  for (const category of storyMap.categories) {
    for (const skill of category.skills) {
      total += skill.weight;
      count += 1;
    }
  }
  return count === 0 ? 0 : total / count;
}

// The highest "min" threshold the child's real progress has actually
// reached - not the nearest one, and not assuming the JSON arrives already
// sorted, since this is content another task authors independently.
function journeyStatusText(progress: number): string {
  const entries = storyNarrative.journey_status_by_progress;
  return entries.reduce((best, entry) => (entry.min <= progress && entry.min >= best.min ? entry : best), entries[0])
    .text;
}

export default function MapPage() {
  const { data: session, status } = useSession();
  const studentId = session?.user?.studentId;
  const router = useRouter();
  const pathname = usePathname();
  const [storyMap, setStoryMap] = useState<StoryMap | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);

  // Real gap found by audit: this page (and /dashboard, /read) only ever
  // gated its own data fetch on `status === "authenticated"` - an
  // unauthenticated visitor never got sent anywhere, they just watched an
  // empty-state shell forever. Redirect for real, with a callback param the
  // login page (app/login/page.tsx) already reads and returns to after a
  // successful login.
  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace(`/login?callbackUrl=${encodeURIComponent(pathname)}`);
    }
  }, [status, router, pathname]);

  useEffect(() => {
    if (status !== "authenticated" || !studentId) return;
    let cancelled = false;
    getStoryMap(studentId).then((r) => {
      if (cancelled) return;
      setStoryMap(r.data);
      setSource(r.source);
    });
    return () => {
      cancelled = true;
    };
  }, [status, studentId]);

  return (
    // Full-page gradient, min-h-screen, same saturation the whole way down -
    // not a colorful band up top fading into a pale or plain body. See
    // docs/BUILD_LOG.md for why this replaced the earlier pale-tint version.
    <main className="min-h-screen bg-gradient-to-b from-emerald-400 via-teal-400 to-sky-400 px-4 py-8 sm:py-10">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6">
          <div className="flex items-center justify-between">
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
          <div className="mt-3 flex justify-center">
            <Logo size="sm" tone="light" href={null} />
          </div>
        </div>

        <div className="mb-8">
          <h1 className="font-[family-name:var(--font-kid)] text-xl font-bold text-white drop-shadow-sm sm:text-2xl">
            {session?.user?.displayName}&apos;s Story Map
          </h1>
          <p className="text-sm text-white/85">
            Every skill you&apos;re building, and the stories that go with it.
          </p>
          {storyMap && (
            <p className="mt-1 text-sm font-medium text-white/95">{journeyStatusText(overallProgress(storyMap))}</p>
          )}
        </div>

        {storyMap && studentId ? (
          <StoryMapView storyMap={storyMap} studentId={studentId} />
        ) : (
          <div className="animate-pulse space-y-4">
            <div className="h-40 rounded-2xl bg-white/50" />
            <div className="h-40 rounded-2xl bg-white/50" />
          </div>
        )}
      </div>
    </main>
  );
}
