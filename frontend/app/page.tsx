"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { motion } from "framer-motion";
import { celebrate, playPop } from "@/lib/confettiPop";
import { getSessions } from "@/lib/api";
import PenguinMascot from "@/components/reading/PenguinMascot";
import Logo from "@/components/ui/Logo";

// next/link isn't a plain DOM element, so it needs motion.create() to
// become animatable - this keeps its own real client-side navigation
// behavior completely intact, framer-motion only ever touches the visual
// transform/shadow on top of it.
const MotionLink = motion.create(Link);

interface HomeStats {
  storiesRead: number;
  avgWcpm: number | null;
  avgAccuracy: number | null;
}

function average(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

export default function Home() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const [stats, setStats] = useState<HomeStats | null>(null);

  useEffect(() => {
    if (status !== "authenticated") return;
    let cancelled = false;
    getSessions(session.user.studentId).then((r) => {
      if (cancelled) return;
      const sessions = r.data;
      setStats({
        storiesRead: sessions.length,
        avgWcpm: average(sessions.map((s) => s.wcpm)),
        avgAccuracy: average(sessions.map((s) => s.accuracy)),
      });
    });
    return () => {
      cancelled = true;
    };
  }, [status, session?.user?.studentId]);

  function handleStartReading(e: React.MouseEvent<HTMLButtonElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    celebrate(rect.left + rect.width / 2, rect.top + rect.height / 2, 42);
    playPop("primary");
    router.push("/read");
  }

  return (
    // One continuous gradient for the whole page, not a colorful band up top
    // fading into a pale/plain body - min-h-screen so it genuinely covers
    // the full screen on a real monitor, same as it always naturally did on
    // a phone where the content alone is already taller than the viewport.
    <main className="relative min-h-screen overflow-hidden bg-gradient-to-b from-sky-400 via-sky-500 to-rose-400 pb-16">
      {/* Hidden below sm: on a narrow phone these land on top of real text -
          a real overlap bug caught by actually checking the 375px width,
          not just desktop. Purely decorative, so hiding them there costs
          nothing. Spread across the full page now, not just the top. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 hidden sm:block">
        <span className="floaty absolute left-[8%] top-[10%] text-3xl opacity-70 sm:text-4xl">
          ⭐
        </span>
        <span
          className="floaty absolute right-[10%] top-[7%] text-2xl opacity-60 sm:text-3xl"
          style={{ animationDelay: "1.2s" }}
        >
          ✨
        </span>
        <span
          className="floaty absolute left-[14%] top-[34%] text-2xl opacity-50 sm:text-3xl"
          style={{ animationDelay: "2.1s" }}
        >
          ☁️
        </span>
        <span
          className="floaty absolute right-[13%] top-[30%] text-3xl opacity-60 sm:text-4xl"
          style={{ animationDelay: "0.6s" }}
        >
          📖
        </span>
        <span
          className="floaty absolute left-[6%] bottom-[10%] text-2xl opacity-50 sm:text-3xl"
          style={{ animationDelay: "1.7s" }}
        >
          🌟
        </span>
        <span
          className="floaty absolute right-[7%] bottom-[8%] text-2xl opacity-50 sm:text-3xl"
          style={{ animationDelay: "0.3s" }}
        >
          🔤
        </span>
      </div>

      <div className="relative flex items-center justify-between px-4 pt-4 sm:px-6">
        <Logo size="sm" tone="light" href={null} />
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="text-sm font-medium text-white/80 transition hover:text-white"
        >
          Sign out
        </button>
      </div>

      <div className="relative px-4 pb-6 pt-8 sm:pt-10">
        <div className="mx-auto max-w-3xl text-center">
          {/* The owl that used to greet a family here is now this same
              penguin every other screen already has - one consistent
              companion for the whole app rather than two different
              characters splitting that job between them. Sized to actually
              anchor the hero the way a real character should, not sit as a
              small icon next to it. */}
          <div
            className="mx-auto flex h-28 w-28 items-center justify-center rounded-full border-4 shadow-xl sm:h-32 sm:w-32"
            style={{
              background: "radial-gradient(circle at 34% 28%, #fbbf24a6, #fbbf2460)",
              borderColor: "#fbbf24",
            }}
          >
            <PenguinMascot pose="wave" className="h-20 w-20 sm:h-24 sm:w-24" />
          </div>
          <h1 className="mt-3 font-[family-name:var(--font-kid)] text-4xl font-bold text-white drop-shadow-sm sm:text-5xl">
            Hi {session?.user?.displayName ?? "there"}! Ready to read?
          </h1>
          <p className="mx-auto mt-3 max-w-md text-base font-medium text-white/90 sm:text-lg">
            Your coach is listening whenever you are.
          </p>

          <button
            onClick={handleStartReading}
            className="btn-3d btn-3d-amber mt-7 inline-flex items-center justify-center gap-2 rounded-3xl bg-gradient-to-b from-amber-400 to-amber-500 px-8 py-4 font-[family-name:var(--font-kid)] text-xl font-bold text-white transition-transform hover:scale-[1.02]"
          >
            <span aria-hidden>🎤</span>
            Start Reading
          </button>
        </div>
      </div>

      <div className="relative mx-auto max-w-3xl px-4">
        <StatStrip stats={stats} />
      </div>

      <div className="relative mx-auto max-w-5xl px-4 pt-10">
        <h2 className="mb-5 font-[family-name:var(--font-kid)] text-lg font-bold text-white drop-shadow-sm sm:text-xl">
          Jump into a screen
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <NavCard
            href="/read"
            icon="📖"
            color="sky"
            title="Reading screen"
            description="Kid-facing passage with live word highlight"
          />
          <NavCard
            href="/map"
            icon="🗺️"
            color="meadow"
            title="Story map"
            description="Skill progress and stories, as a journey"
          />
          <NavCard
            href="/dashboard"
            icon="📊"
            color="grape"
            title="Parent dashboard"
            description="Fluency trend and skill mastery"
          />
          <NavCard
            href="/admin/engineering"
            icon="⚙️"
            color="marigold"
            title="Engineering dashboard"
            description="Pipeline latency and eval scores"
          />
        </div>
      </div>
    </main>
  );
}

function StatStrip({ stats }: { stats: HomeStats | null }) {
  // Real feedback: mixing "…"/"—" (loading, no-number-yet) with a real "0"
  // (a genuine, meaningful count) on the same row read as two different
  // visual languages for the one underlying idea, "nothing here yet." A
  // brand-new account gets one plain, encouraging message instead - once
  // there's a real story read, wcpm/accuracy always exist alongside it, so
  // this branch is the only place "no data" ever needs saying at all.
  if (stats === null) {
    return (
      <div
        className="grid grid-cols-3 gap-3 rounded-3xl bg-amber-50/95 p-3 shadow-lg ring-2 ring-amber-200 sm:gap-4 sm:p-4"
        aria-hidden
      >
        <div className="h-16 animate-pulse rounded-2xl bg-white/70" />
        <div className="h-16 animate-pulse rounded-2xl bg-white/70" />
        <div className="h-16 animate-pulse rounded-2xl bg-white/70" />
      </div>
    );
  }

  if (stats.storiesRead === 0) {
    return (
      <div className="flex items-center gap-3 rounded-3xl bg-amber-50/95 p-4 shadow-lg ring-2 ring-amber-200">
        <span className="text-2xl" aria-hidden>
          📖
        </span>
        <p className="text-sm font-medium text-slate-600">
          You haven&apos;t read a story yet - tap{" "}
          <span className="font-bold text-slate-800">Start Reading</span> to begin!
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-3 gap-3 rounded-3xl bg-amber-50/95 p-3 shadow-lg ring-2 ring-amber-200 sm:gap-4 sm:p-4">
      <StatPill icon="📚" value={String(stats.storiesRead)} label="Stories read" />
      <StatPill
        icon="⏱️"
        value={stats.avgWcpm != null ? String(Math.round(stats.avgWcpm)) : "—"}
        label="Avg wcpm"
      />
      <StatPill
        icon="🎯"
        value={stats.avgAccuracy != null ? `${Math.round(stats.avgAccuracy * 100)}%` : "—"}
        label="Avg accuracy"
      />
    </div>
  );
}

function StatPill({ icon, value, label }: { icon: string; value: string; label: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 rounded-2xl bg-white/70 px-2 py-3 text-center sm:px-3">
      <span aria-hidden className="text-xl sm:text-2xl">
        {icon}
      </span>
      <span className="font-[family-name:var(--font-kid)] text-lg font-bold text-slate-800 sm:text-xl">
        {value}
      </span>
      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 sm:text-xs">
        {label}
      </span>
    </div>
  );
}

const CARD_ICON_CLASSES = {
  sky: "bg-sky-100 text-sky-600",
  meadow: "bg-emerald-100 text-emerald-600",
  grape: "bg-violet-100 text-violet-600",
  marigold: "bg-amber-100 text-amber-600",
} as const;

// Each nav card is now tinted to its own destination's color instead of
// plain white, so the four cards read as distinct, branded "stickers" on
// the vibrant page background rather than four identical white slabs.
const CARD_BG_CLASSES = {
  sky: "bg-sky-50/95 ring-sky-200 hover:ring-sky-300",
  meadow: "bg-emerald-50/95 ring-emerald-200 hover:ring-emerald-300",
  grape: "bg-violet-50/95 ring-violet-200 hover:ring-violet-300",
  marigold: "bg-amber-50/95 ring-amber-200 hover:ring-amber-300",
} as const;

function NavCard({
  href,
  icon,
  color,
  title,
  description,
}: {
  href: string;
  icon: string;
  color: keyof typeof CARD_ICON_CLASSES;
  title: string;
  description: string;
}) {
  return (
    <MotionLink
      href={href}
      onClick={(e: React.MouseEvent<HTMLAnchorElement>) => {
        // Real navigation happens for real via next/link below - this is
        // the same delight layer real buttons get elsewhere (lib/
        // confettiPop.ts, components/ui/PlumpButton.tsx), never a
        // replacement for it.
        const rect = e.currentTarget.getBoundingClientRect();
        celebrate(rect.left + rect.width / 2, rect.top + rect.height / 2, 20);
        playPop("small");
      }}
      whileHover={{ y: -6, scale: 1.02 }}
      whileTap={{ scale: 0.96 }}
      transition={{ type: "spring", stiffness: 350, damping: 20 }}
      className={`group flex flex-col gap-2.5 rounded-3xl p-5 shadow-lg ring-2 transition-shadow hover:shadow-xl ${CARD_BG_CLASSES[color]}`}
    >
      <span
        className={`card-wiggle-icon inline-flex h-11 w-11 items-center justify-center rounded-2xl text-2xl ${CARD_ICON_CLASSES[color]}`}
        aria-hidden
      >
        {icon}
      </span>
      <span className="font-[family-name:var(--font-kid)] font-bold text-slate-800">
        {title}
      </span>
      <span className="text-sm text-slate-500">{description}</span>
    </MotionLink>
  );
}
