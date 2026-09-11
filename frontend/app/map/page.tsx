"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSession, signOut } from "next-auth/react";
import { getStoryMap } from "@/lib/api";
import type { DataSource, StoryMap } from "@/lib/types";
import StoryMapView from "@/components/map/StoryMapView";
import DataSourceBadge from "@/components/DataSourceBadge";

export default function MapPage() {
  const { data: session, status } = useSession();
  const studentId = session?.user?.studentId;
  const [storyMap, setStoryMap] = useState<StoryMap | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);

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
        <div className="mb-6 flex items-center justify-between">
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

        <div className="mb-8">
          <h1 className="font-[family-name:var(--font-kid)] text-xl font-bold text-white drop-shadow-sm sm:text-2xl">
            {session?.user?.displayName}&apos;s Story Map
          </h1>
          <p className="text-sm text-white/85">
            Every skill you&apos;re building, and the stories that go with it.
          </p>
        </div>

        {storyMap ? (
          <StoryMapView storyMap={storyMap} />
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
