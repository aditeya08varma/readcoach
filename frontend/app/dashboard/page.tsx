"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSession, signOut } from "next-auth/react";
import { getMastery, getSessions } from "@/lib/api";
import type { DataSource, MasterySkill, SessionSummary } from "@/lib/types";
import FluencyTrendChart from "@/components/dashboard/FluencyTrendChart";
import MasteryBarChart from "@/components/dashboard/MasteryBarChart";
import DataSourceBadge from "@/components/DataSourceBadge";
import PenguinMascot from "@/components/reading/PenguinMascot";

const CATEGORY_LEGEND: Array<{ label: string; color: string }> = [
  { label: "Phonics", color: "#0284c7" },
  { label: "Vocabulary", color: "#d97706" },
  { label: "Comprehension", color: "#7c3aed" },
];

const STAT_ICONS: Record<string, string> = {
  Sessions: "📅",
  "Latest WCPM": "⏱️",
  "Latest accuracy": "🎯",
  "Self-corrections": "🔁",
};

// Real feedback: this recap section only ever showed the single latest
// session's own Claude-written paragraph, even on a day a child read three
// or four separate stories - a parent checking in after story night saw
// only the last one, with no sense that the rest had even happened. Real
// local-calendar-day grouping, not a rolling "last 24 hours" window, so a
// parent checking the dashboard the morning after story night still sees
// that whole evening's real recap instead of it silently rolling off.
function isSameLocalDay(aIso: string, bIso: string): boolean {
  const a = new Date(aIso);
  const b = new Date(bIso);
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

// A real, hand-built sentence over the real plain numbers every session
// already carries (wcpm/accuracy/self_corrections), the same kind of
// template mockData.ts's own fallback already uses - not a second Claude
// call to narrate a whole day, which would be real new backend surface for
// a dashboard recap this can already say accurately with real arithmetic.
// The single-story case is left completely alone: that day's one real
// session_recap is already Claude's own warmer, more specific paragraph,
// and reads better than a templated one-story "average."
function buildDailyRecap(todaysSessions: SessionSummary[]): string {
  const count = todaysSessions.length;
  const avgWcpm = Math.round(todaysSessions.reduce((sum, s) => sum + s.wcpm, 0) / count);
  const avgAccuracy = Math.round(
    (todaysSessions.reduce((sum, s) => sum + s.accuracy, 0) / count) * 100
  );
  const totalSelfCorrections = todaysSessions.reduce((sum, s) => sum + s.self_corrections, 0);
  return (
    `Today your child read ${count} stories, averaging ${avgWcpm} words per minute ` +
    `with ${avgAccuracy}% accuracy, and caught ${totalSelfCorrections} of their own ` +
    `mistakes along the way. Keep up the great practice!`
  );
}

export default function DashboardPage() {
  const { data: session, status } = useSession();
  const studentId = session?.user?.studentId;
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [mastery, setMastery] = useState<MasterySkill[] | null>(null);
  const [sessionsSource, setSessionsSource] = useState<DataSource | null>(null);
  const [masterySource, setMasterySource] = useState<DataSource | null>(null);

  useEffect(() => {
    if (status !== "authenticated" || !studentId) return;
    let cancelled = false;
    getSessions(studentId).then((r) => {
      if (cancelled) return;
      setSessions(r.data);
      setSessionsSource(r.source);
    });
    getMastery(studentId).then((r) => {
      if (cancelled) return;
      setMastery(r.data);
      setMasterySource(r.source);
    });
    return () => {
      cancelled = true;
    };
  }, [status, studentId]);

  const latest = sessions?.[sessions.length - 1];
  const todaysSessions = sessions && latest
    ? sessions.filter((s) => isSameLocalDay(s.started_at, latest.started_at))
    : null;
  const dailyRecap =
    todaysSessions && todaysSessions.length > 1
      ? buildDailyRecap(todaysSessions)
      : latest?.session_recap ?? null;

  return (
    // Real feedback: this was exactly as candy-saturated as the kid's
    // reading screen, which undercuts the "trustworthy tool for an adult"
    // feeling a parent dashboard usually wants - a Grade 1 mastery bar and
    // a quarterly business chart would have gotten identical treatment.
    // Violet stays this page's identity color (matches its nav card on the
    // home screen), but concentrated into accents now rather than a
    // full-saturation background - a calm, mostly-neutral canvas the
    // colored stat tiles and charts can stand out against, closer to how a
    // real parent-facing dashboard actually reads. Kid-facing screens
    // (home, read, map) keep their full vibrancy - this restraint is
    // specifically for the two adult-facing screens (here and /admin/
    // engineering), not the whole app.
    <main className="min-h-screen bg-gradient-to-b from-violet-50 via-white to-violet-50 px-4 py-8 sm:py-10">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <Link
            href="/"
            className="text-sm font-medium text-slate-500 transition hover:text-slate-700"
          >
            &larr; Home
          </Link>
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="text-sm font-medium text-slate-500 transition hover:text-slate-700"
          >
            Sign out
          </button>
        </div>

        <div className="mb-8 flex items-center gap-4">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white text-xl font-bold text-violet-600 shadow-md ring-1 ring-violet-100">
            {(session?.user?.displayName ?? "?").slice(0, 1)}
          </div>
          <div>
            <h1 className="font-[family-name:var(--font-kid)] text-xl font-bold text-slate-800 sm:text-2xl">
              {session?.user?.displayName}&apos;s Reading Progress
            </h1>
            <p className="text-sm text-slate-500">Grade {session?.user?.grade}</p>
          </div>
          {/* This page was deliberately calmed down for the adult reading
              it (see the page's own gradient comment above), so this still
              stays a genuine accent rather than the full hero treatment
              the kid-facing screens get - but a real, visible one now,
              not a small icon easy to miss next to the heading. */}
          <div
            className="ml-auto hidden h-20 w-20 shrink-0 items-center justify-center rounded-full border-[3px] shadow-md sm:flex"
            style={{
              background: "radial-gradient(circle at 34% 28%, #c4b5fda6, #c4b5fd60)",
              borderColor: "#c4b5fd",
            }}
          >
            <PenguinMascot pose="wave" className="h-14 w-14" />
          </div>
        </div>

        {latest && (
          <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
            <StatTile
              icon={STAT_ICONS.Sessions}
              color="sky"
              label="Sessions"
              value={String(sessions?.length ?? 0)}
            />
            <StatTile
              icon={STAT_ICONS["Latest WCPM"]}
              color="meadow"
              label="Latest WCPM"
              value={String(latest.wcpm)}
            />
            <StatTile
              icon={STAT_ICONS["Latest accuracy"]}
              color="marigold"
              label="Latest accuracy"
              value={`${Math.round(latest.accuracy * 100)}%`}
            />
            <StatTile
              icon={STAT_ICONS["Self-corrections"]}
              color="grape"
              label="Self-corrections"
              value={String(latest.self_corrections)}
            />
          </div>
        )}

        {dailyRecap && (
          <section className="mb-8 rounded-3xl bg-gradient-to-br from-amber-50 to-amber-100/60 p-5 ring-1 ring-amber-200 sm:p-6">
            <h2 className="mb-2 flex items-center gap-2 font-[family-name:var(--font-kid)] text-sm font-bold text-amber-900">
              <span aria-hidden>✨</span>
              {todaysSessions && todaysSessions.length > 1 ? "Today's recap" : "Last session recap"}
            </h2>
            <p className="text-sm leading-relaxed text-amber-950">{dailyRecap}</p>
          </section>
        )}

        <section className="mb-6 rounded-3xl bg-white p-5 shadow-md ring-1 ring-violet-100 sm:mb-8 sm:p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-[family-name:var(--font-kid)] text-lg font-bold text-slate-800">Fluency trend</h2>
            <DataSourceBadge source={sessionsSource} />
          </div>
          {!sessions ? (
            <ChartSkeleton />
          ) : sessions.length === 0 ? (
            <ChartEmptyState message="Read your first story to see your fluency trend!" />
          ) : (
            <FluencyTrendChart sessions={sessions} />
          )}
        </section>

        <section className="rounded-3xl bg-white p-5 shadow-md ring-1 ring-fuchsia-100 sm:p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-[family-name:var(--font-kid)] text-lg font-bold text-slate-800">Skill mastery</h2>
            <DataSourceBadge source={masterySource} />
          </div>
          <div className="mb-4 flex flex-wrap gap-2 text-xs">
            {CATEGORY_LEGEND.map((c) => (
              <span
                key={c.label}
                className="flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 font-semibold text-slate-600 ring-1 ring-slate-200"
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: c.color }}
                />
                {c.label}
              </span>
            ))}
          </div>
          {mastery ? <MasteryBarChart skills={mastery} /> : <ChartSkeleton rows={6} />}
        </section>
      </div>
    </main>
  );
}

const STAT_TILE_COLORS = {
  sky: "bg-sky-100 text-sky-600",
  meadow: "bg-emerald-100 text-emerald-600",
  marigold: "bg-amber-100 text-amber-600",
  grape: "bg-violet-100 text-violet-600",
} as const;

// Each tile's card takes its own accent color instead of plain white, so
// the four stats read as a lively, distinct row rather than four identical
// gray boxes.
const STAT_TILE_CARD_CLASSES = {
  sky: "bg-sky-50/95 ring-sky-200",
  meadow: "bg-emerald-50/95 ring-emerald-200",
  marigold: "bg-amber-50/95 ring-amber-200",
  grape: "bg-violet-50/95 ring-violet-200",
} as const;

function StatTile({
  icon,
  color,
  label,
  value,
}: {
  icon: string;
  color: keyof typeof STAT_TILE_COLORS;
  label: string;
  value: string;
}) {
  return (
    <div className={`flex flex-col items-center gap-1 rounded-2xl p-3.5 text-center shadow-md ring-2 transition hover:-translate-y-0.5 hover:shadow-lg sm:p-4 ${STAT_TILE_CARD_CLASSES[color]}`}>
      <span
        className={`flex h-9 w-9 items-center justify-center rounded-xl text-base ${STAT_TILE_COLORS[color]}`}
        aria-hidden
      >
        {icon}
      </span>
      <div className="font-[family-name:var(--font-kid)] text-xl font-bold text-slate-800 sm:text-2xl">{value}</div>
      <div className="text-[11px] text-slate-500 sm:text-xs">{label}</div>
    </div>
  );
}

/** Lightweight pulsing placeholder shown while a chart's data is loading. */
function ChartSkeleton({ rows = 1 }: { rows?: number }) {
  return (
    <div className="animate-pulse space-y-2 py-2" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-6 rounded-lg bg-slate-100" />
      ))}
      {rows === 1 && <div className="h-64 rounded-lg bg-slate-100" />}
    </div>
  );
}

/** Real feedback: a chart with genuinely zero data points used to just
 * render as an empty box - technically correct, but indistinguishable from
 * broken at a glance. Same height as the real chart it stands in for, so
 * the section doesn't visibly resize once a first real story fills it in. */
function ChartEmptyState({ message }: { message: string }) {
  return (
    <div className="flex h-64 flex-col items-center justify-center gap-2 rounded-lg bg-slate-50 text-center">
      <span className="text-3xl" aria-hidden>
        📈
      </span>
      <p className="max-w-xs text-sm font-medium text-slate-500">{message}</p>
    </div>
  );
}
