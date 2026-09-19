"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Settings, Target, Ruler, FlaskConical, type LucideIcon } from "lucide-react";
import { getEngineeringDashboard } from "@/lib/api";
import type { DataSource, EngineeringDashboard } from "@/lib/types";
import DataSourceBadge from "@/components/DataSourceBadge";
import LatencyChart from "@/components/admin/LatencyChart";
import PenguinMascot from "@/components/reading/PenguinMascot";
import Logo from "@/components/ui/Logo";

export default function EngineeringDashboardPage() {
  const [dashboard, setDashboard] = useState<EngineeringDashboard | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    getEngineeringDashboard().then((r) => {
      if (cancelled) return;
      setDashboard(r.data);
      setSource(r.source);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    // Real feedback: this used to be a full-saturation indigo/blue
    // background, exactly as loud as the kid-facing screens, undercutting
    // the "calm technical tool" this page is meant to read as - the same
    // fix as /dashboard, for the same reason (see that file's own comment).
    // Indigo stays the identity color, just concentrated into accents on a
    // calm, near-neutral canvas instead of the whole background.
    <main className="min-h-screen bg-gradient-to-b from-indigo-50 via-white to-indigo-50 px-4 py-10">
      <div className="mx-auto max-w-3xl">
        <div className="mb-6">
          <div className="flex items-center justify-between">
            <Link href="/" className="text-sm text-slate-500 hover:text-slate-700">
              &larr; Home
            </Link>
            <DataSourceBadge source={source} />
          </div>
          <div className="mt-3 flex justify-center">
            <Logo size="sm" tone="dark" href={null} />
          </div>
        </div>

        <div className="mb-6 flex items-center gap-3">
          <span
            aria-hidden
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white text-indigo-600 shadow-md ring-1 ring-indigo-100"
          >
            <Settings className="h-5 w-5" strokeWidth={2.25} />
          </span>
          <h1 className="font-[family-name:var(--font-classy)] text-2xl font-bold text-slate-800">
            Pipeline Engineering Dashboard
          </h1>
          {/* Still the quietest version of this on any page - this is a
              technical tool for a different persona than the rest of the
              app, so it stays an accent rather than competing with the
              actual data on screen - but a real, visible one now rather
              than a nearly-missable tiny icon. Singing, since this is the
              one screen that's all about this app's own real pipeline
              metrics. */}
          <div
            className="ml-auto hidden h-16 w-16 shrink-0 items-center justify-center rounded-full border-[3px] shadow-sm sm:flex"
            style={{
              background: "radial-gradient(circle at 34% 28%, #a5b4fca6, #a5b4fc60)",
              borderColor: "#a5b4fc",
            }}
          >
            <PenguinMascot pose="sing" className="h-11 w-11" />
          </div>
        </div>

        {!dashboard && (
          <div className="animate-pulse space-y-3" aria-hidden>
            <div className="h-40 rounded-3xl bg-slate-100" />
            <div className="h-24 rounded-3xl bg-slate-100" />
          </div>
        )}

        {dashboard && (
          <>
            {/* Real bug found while redoing this page's colors: this
                section was accidentally left tinted amber from an earlier
                pass, sitting oddly next to the second section's indigo -
                both now consistently indigo, this page's one identity
                color. */}
            <section className="mb-8 rounded-3xl bg-white p-6 shadow-md ring-1 ring-indigo-100">
              <h2 className="mb-4 font-[family-name:var(--font-kid)] text-lg font-bold text-slate-800">
                Per-stage latency (ms)
              </h2>
              <LatencyChart dashboard={dashboard} />
            </section>

            <section className="rounded-3xl bg-white p-6 shadow-md ring-1 ring-indigo-100">
              <h2 className="mb-4 font-[family-name:var(--font-kid)] text-lg font-bold text-slate-800">Eval scores</h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <EvalTile
                  icon={Target}
                  label="Diagnostic accuracy"
                  value={`${Math.round(dashboard.eval.diagnostic_accuracy * 100)}%`}
                />
                <EvalTile
                  icon={Ruler}
                  label="Question groundedness"
                  value={`${Math.round(dashboard.eval.question_groundedness * 100)}%`}
                />
                <EvalTile
                  icon={FlaskConical}
                  label="Sample size"
                  value={String(dashboard.eval.sample_size)}
                />
              </div>
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function EvalTile({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="flex flex-col items-center gap-1.5 rounded-2xl bg-indigo-50/70 p-4 text-center ring-1 ring-indigo-200/70 transition hover:-translate-y-0.5 hover:shadow-sm">
      <span aria-hidden className="text-indigo-500">
        <Icon className="h-5 w-5" strokeWidth={2.25} />
      </span>
      <div className="font-[family-name:var(--font-kid)] text-2xl font-bold text-slate-800">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
