"use client";

import Link from "next/link";
import type { MapCategory, MapPassageRef, MapSkillNode, StoryMap } from "@/lib/types";
import { celebrate, playPop } from "@/lib/confettiPop";
import PenguinMascot, { type PenguinPose } from "@/components/reading/PenguinMascot";

const CATEGORY_META: Record<
  string,
  { label: string; icon: string; color: string; bg: string; ring: string }
> = {
  phonics: {
    label: "Phonics Path",
    icon: "🔤",
    color: "#0284c7",
    // Real feedback: at "-50" these cards were nearly white and sat
    // flatly against the page's own vivid green-to-sky gradient
    // background, an abrupt jump rather than a card that actually
    // belongs on that page. A real two-tone gradient one full step
    // darker, plus a stronger ring, gives each card its own visible
    // color and a genuine sense of depth instead.
    bg: "bg-gradient-to-b from-sky-200 to-sky-100",
    ring: "ring-sky-300",
  },
  vocabulary: {
    label: "Vocabulary Trail",
    icon: "📚",
    color: "#d97706",
    bg: "bg-gradient-to-b from-amber-200 to-amber-100",
    ring: "ring-amber-300",
  },
  comprehension: {
    label: "Comprehension Summit",
    icon: "🏔️",
    color: "#7c3aed",
    bg: "bg-gradient-to-b from-violet-200 to-violet-100",
    ring: "ring-violet-300",
  },
};

const MASTERED_THRESHOLD = 0.8;

// A real, literal winding path now (Duolingo's own skill-tree layout was
// named directly as the reference) - repeating left/center/right offsets
// applied to each node in turn, in percentage terms so it scales safely at
// any width from 320px up rather than a fixed pixel offset that could
// overflow a narrow phone. Four steps per wave (center, right, center,
// left) rather than true sine-curve math - visually reads as a gentle S,
// which is what this needed, without the precision an actual curve
// generator would take to get right for content this doesn't have (bezier
// paths following exact rendered node centers).
const ZIGZAG = ["translate-x-0", "translate-x-[26%]", "translate-x-0", "-translate-x-[26%]"];

// Trailside company for the wide margins either side of the path itself -
// real feedback that the page still looked bare next to how much motion the
// rest of the app has. Two independent cadences, not one shared list: the
// penguin cycles through its four poses (wave, dance, sleep, sing) on its
// own every-3rd-step beat, and the emoji flourishes cycle on their own beat
// one step off from that. Splitting them this way is what actually
// guarantees a family scrolling the full 12-step phonics path sees every
// single one of the four poses at least once - a single shared list this
// long would only reach every other pose within any real category this app
// actually has. The penguin reappears here deliberately (Duolingo's own owl
// shows up beside its path more than once too) rather than being invented
// as a second, competing character.
const PENGUIN_POSES: PenguinPose[] = ["wave", "dance", "sleep", "sing"];
const EMOJI_DECOR = ["📖", "⭐", "🐟", "☁️"];

// Real feedback: this screen said "map"/"path"/"trail"/"journey" in its own
// copy, but the layout underneath was a plain grid with no sense of where a
// real child actually is on that journey right now. Mirrors pick_next_
// passage's own real rule (backend/mastery/passage_selection.py: weakest
// skill with a real passage available, ties broken by that skill's own
// place in the taxonomy's foundational order) purely to LABEL a node, not
// to decide anything - the real pick still happens server-side the moment
// Start Reading is actually tapped. Walking storyMap.categories in the
// order the server already returns them (already that same foundational
// order) makes this a faithful preview of what Start Reading will do next.
function findCurrentSkillId(storyMap: StoryMap): string | null {
  let best: MapSkillNode | null = null;
  for (const category of storyMap.categories) {
    for (const node of category.skills) {
      if (node.passages.length === 0) continue;
      if (node.weight >= MASTERED_THRESHOLD) continue;
      if (!best || node.weight < best.weight) {
        best = node;
      }
    }
  }
  return best?.skill_id ?? null;
}

export default function StoryMapView({ storyMap }: { storyMap: StoryMap }) {
  const currentSkillId = findCurrentSkillId(storyMap);
  return (
    <div className="flex flex-col gap-6 sm:gap-8">
      {storyMap.categories.map((category) => (
        <CategoryPath key={category.category} category={category} currentSkillId={currentSkillId} />
      ))}
    </div>
  );
}

function CategoryPath({
  category,
  currentSkillId,
}: {
  category: MapCategory;
  currentSkillId: string | null;
}) {
  const meta = CATEGORY_META[category.category] ?? {
    label: category.category,
    icon: "🗺️",
    color: "#475569",
    bg: "bg-slate-50",
    ring: "ring-slate-200",
  };
  const masteredCount = category.skills.filter((s) => s.weight >= MASTERED_THRESHOLD).length;

  return (
    <section className={`rounded-3xl ${meta.bg} p-5 shadow-lg ring-2 ${meta.ring} sm:p-6`}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2.5 font-[family-name:var(--font-kid)] text-lg font-bold text-slate-800">
          <span
            aria-hidden
            className="flex h-8 w-8 items-center justify-center rounded-xl bg-white text-base shadow-sm"
          >
            {meta.icon}
          </span>
          {meta.label}
        </h2>
        {/* A real sense of "how far along this leg of the journey" at a
            glance, without reading every single card. */}
        <span className="rounded-full bg-white/70 px-3 py-1 text-xs font-bold text-slate-600">
          {masteredCount}/{category.skills.length} mastered
        </span>
      </div>

      {/* A narrow, centered column (not the full section width) - Duolingo's
          own path stays this narrow even on a wide desktop screen, which is
          exactly what keeps the zigzag readable instead of stretching it
          across a much wider container than it was ever meant for. */}
      <div className="mx-auto flex max-w-xs flex-col items-center">
        {(() => {
          const currentIndex = category.skills.findIndex((s) => s.skill_id === currentSkillId);
          return category.skills.map((node, i) => {
            // Two independent triggers sharing the same margin, one step
            // apart so they never land on the same node: the penguin at
            // every step whose number is a multiple of 3 (3, 6, 9, ...),
            // the emoji at every step one before that (2, 5, 8, ...). Both
            // ordinals are derived straight from i, not a running counter,
            // so this stays a pure function of each step's own index - and
            // both alternate sides independently, starting on opposite
            // sides of each other so an adjacent pair never doubles up.
            const showPenguin = (i + 1) % 3 === 0;
            const showEmoji = i % 3 === 1;
            const penguinOrdinal = (i - 2) / 3;
            const emojiOrdinal = (i - 1) / 3;
            const decor: { kind: "penguin"; pose: PenguinPose } | { kind: "emoji"; content: string } | null =
              showPenguin
                ? { kind: "penguin", pose: PENGUIN_POSES[penguinOrdinal % PENGUIN_POSES.length] }
                : showEmoji
                  ? { kind: "emoji", content: EMOJI_DECOR[emojiOrdinal % EMOJI_DECOR.length] }
                  : null;
            const side: "left" | "right" = showPenguin
              ? penguinOrdinal % 2 === 0
                ? "right"
                : "left"
              : emojiOrdinal % 2 === 0
                ? "left"
                : "right";
            return (
              <div
                key={node.skill_id}
                className="path-step-in relative flex w-full flex-col items-center"
                style={{ animationDelay: `${i * 0.09}s` }}
              >
                {i > 0 && (
                  <PathConnector filled={category.skills[i - 1].weight >= MASTERED_THRESHOLD} color={meta.color} />
                )}
                <PathStep
                  node={node}
                  step={i + 1}
                  color={meta.color}
                  isCurrent={node.skill_id === currentSkillId}
                  // A node further down the path than the one actually being
                  // recommended right now, that a child hasn't touched at all
                  // yet, reads visually quieter - Duolingo's own path dims
                  // everything not yet reached. Deliberately dimming only,
                  // never disabling: this app's own real rule (see
                  // pick_next_passage) never blocks a family from freely
                  // choosing any story, so the link underneath stays fully
                  // real and clickable either way.
                  isFuture={currentIndex !== -1 && i > currentIndex}
                  offsetClass={ZIGZAG[i % ZIGZAG.length]}
                />
                {decor && <SideDecoration decor={decor} side={side} color={meta.color} />}
              </div>
            );
          });
        })()}
      </div>
    </section>
  );
}

// Sits in the section's own wide margin just outside the narrow path
// column, never inside it - anchored to the full-width step wrapper's own
// edge (left-full / right-full) rather than a fixed pixel offset, so it
// naturally lands in whatever real whitespace that screen width actually
// has. Doubled in size on direct request; at that size it no longer clears
// the margin available between 640-767px (the sm: breakpoint this used to
// switch on at), so activation moved to md: (768px) instead - checked
// against this project's own required breakpoints, not guessed.
// A small floating cue next to a pose that isn't self-explanatory from
// motion alone - the dance and the wave both read fine on their own, but a
// penguin with its eyes shut or its beak flapping needed one extra hint to
// actually land as "asleep" or "singing" rather than just looking odd.
const POSE_BADGE: Partial<Record<PenguinPose, string>> = {
  sleep: "💤",
  sing: "🎵",
};

function SideDecoration({
  decor,
  side,
  color,
}: {
  decor: { kind: "penguin"; pose: PenguinPose } | { kind: "emoji"; content: string };
  side: "left" | "right";
  color: string;
}) {
  const posClass = side === "right" ? "left-full ml-8 lg:ml-20" : "right-full mr-8 lg:mr-20";
  const badge = decor.kind === "penguin" ? POSE_BADGE[decor.pose] : undefined;
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute top-1/2 hidden -translate-y-1/2 md:block ${posClass}`}
    >
      {decor.kind === "emoji" ? (
        // The same bubble language as the penguin below, scaled down a
        // notch so the penguin still reads as the star of this margin -
        // a bare floating emoji next to a properly bubbled penguin looked
        // like only half the page had actually been finished.
        <div
          className="floaty flex h-24 w-24 items-center justify-center rounded-full border-[3px] shadow-md lg:h-32 lg:w-32"
          style={{
            background: `radial-gradient(circle at 34% 28%, ${color}55, ${color}22)`,
            borderColor: `${color}bb`,
          }}
        >
          <span className="text-5xl lg:text-6xl">{decor.content}</span>
        </div>
      ) : (
        // A real, properly colored bubble, not a barely-tinted wash that
        // read as basically white - a two-tone radial fill plus a solid
        // ring in this section's own accent color, the same "icon resting
        // in a colored circle" language the up-next penguin and the reading
        // screen's own avatar already use. The bubble keeps the exact same
        // overall footprint already checked against every required
        // breakpoint; only the penguin inside it shrank to leave real room
        // for the ring of color around it.
        <div
          className="relative flex h-32 w-32 items-center justify-center rounded-full border-4 shadow-md lg:h-48 lg:w-48"
          style={{
            background: `radial-gradient(circle at 34% 28%, ${color}99, ${color}55)`,
            borderColor: color,
            boxShadow: `0 12px 26px ${color}40`,
          }}
        >
          <PenguinMascot pose={decor.pose} className="h-24 w-24 lg:h-36 lg:w-36" />
          {badge && (
            <span className="pose-badge absolute -right-1 -top-1 text-3xl lg:text-4xl">{badge}</span>
          )}
        </div>
      )}
    </div>
  );
}

// A short vertical segment between two nodes instead of a plain arrow -
// real progress (mastered) fills it in that category's own color, so the
// path itself shows how far a child has actually walked, not just each
// node in isolation.
function PathConnector({ filled, color }: { filled: boolean; color: string }) {
  return (
    <span
      aria-hidden
      className="h-6 w-1.5 shrink-0 rounded-full"
      style={{ backgroundColor: filled ? color : "#cbd5e1" }}
    />
  );
}

function PathStep({
  node,
  step,
  color,
  isCurrent,
  isFuture,
  offsetClass,
}: {
  node: MapSkillNode;
  step: number;
  color: string;
  isCurrent: boolean;
  isFuture: boolean;
  offsetClass: string;
}) {
  const pct = Math.round(node.weight * 100);
  const mastered = node.weight >= MASTERED_THRESHOLD;
  const attemptedCount = node.passages.filter((p) => p.attempted).length;
  const hasStarted = pct > 0 || attemptedCount > 0;
  const dim = isFuture && !mastered && !hasStarted;

  return (
    <div
      className={`flex w-full flex-col items-center gap-2 transition-all duration-300 ${offsetClass} ${
        dim ? "opacity-45 saturate-50" : "opacity-100"
      }`}
    >
      {/* A real penguin standing at the one node Start Reading will
          actually pick next - the same "you are here" job the amber badge
          already did, now with an actual companion doing the pointing
          instead of an emoji, waving hello rather than just idling. Same
          properly colored bubble the side-path penguins now stand in, in
          this category's own accent color. */}
      {isCurrent && (
        <div
          className="flex h-14 w-14 items-center justify-center rounded-full border-[3px] shadow-sm sm:h-16 sm:w-16"
          style={{
            background: `radial-gradient(circle at 34% 28%, ${color}99, ${color}55)`,
            borderColor: color,
          }}
        >
          <PenguinMascot pose="wave" className="h-11 w-11 sm:h-12 sm:w-12" />
        </div>
      )}
      {/* The big, round node - this is the actual "path" piece: a real
          circle a child taps their way along, colored solid once mastered,
          softly tinted while still ahead of them. */}
      <div className="relative" title={node.label}>
        {isCurrent && (
          <span className="absolute -top-4 left-1/2 flex -translate-x-1/2 items-center gap-1 whitespace-nowrap rounded-full bg-amber-400 px-2.5 py-0.5 text-[10px] font-bold text-white shadow-sm">
            Up next
          </span>
        )}
        <div
          className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-full border-4 text-xl font-bold text-white shadow-md transition hover:scale-105 ${
            isCurrent ? "here-pulse" : ""
          }`}
          style={{
            backgroundColor: mastered ? "#10b981" : hasStarted ? color : `${color}55`,
            borderColor: isCurrent ? "#fbbf24" : "white",
          }}
        >
          {mastered ? "✓" : step}
        </div>
        {/* A truly earned skill keeps a small, permanent twinkle rather than
            sitting exactly as still as everything else - the same sparkle
            already used for a just-finished reading session, reused here so
            "mastered" reads as an ongoing little celebration, not a flat
            green dot indistinguishable from any other filled circle. */}
        {mastered && (
          <>
            <span
              className="mastered-sparkle absolute -right-1 -top-1 text-xs animate-[sparkle_1.6s_ease-in-out_infinite]"
              aria-hidden
            >
              ✨
            </span>
            <span
              className="mastered-sparkle absolute -bottom-1 -left-1 text-[10px] animate-[sparkle_1.6s_ease-in-out_infinite_0.4s]"
              aria-hidden
            >
              ✨
            </span>
          </>
        )}
      </div>

      {/* Everything below the circle stays centered regardless of the
          circle's own zigzag offset above it - readable content shouldn't
          wander with the decorative path, only the node marking it does. */}
      <span className="max-w-[10rem] text-center font-[family-name:var(--font-kid)] text-xs font-bold text-slate-700">
        {node.label}
      </span>

      <div
        className="h-2 w-24 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${node.label} mastery, ${pct}%`}
      >
        <div
          className="h-full rounded-full transition-all duration-500 ease-out"
          style={{
            // A non-zero mastery weight can be genuinely small (one session
            // only moves the blend ~30% of the way, see mastery.py) - a
            // real, honest 3-4% would otherwise round to a sliver thinner
            // than the rounded end caps and read as visually empty. Floor
            // only applies once there's any real progress to show at all.
            width: pct === 0 ? "0%" : `${Math.max(pct, 6)}%`,
            background: mastered
              ? "linear-gradient(90deg, #10b981, #34d399)"
              : `linear-gradient(90deg, ${color}, ${color}cc)`,
          }}
        />
      </div>

      {node.passages.length === 0 ? (
        <p className="text-[11px] italic text-slate-400">No story yet</p>
      ) : (
        <>
          {/* A genuinely untouched skill showing "0% mastery · 0/1 stories
              read" twelve times over reads as a wall of noise repeating the
              same non-fact - "not started" says the same thing once,
              plainly. Explicit mastery % only appears once there's real
              signal, alongside "stories read" so 1/1 read next to a
              still-partial bar reads as real, ongoing progress (see
              docs/BUILD_LOG.md) rather than a bug. */}
          <p className="text-[11px] font-semibold text-slate-500">
            {hasStarted ? (
              <>
                {pct}% mastery · {attemptedCount}/{node.passages.length} stories read
              </>
            ) : (
              <span className="italic text-slate-400">Not started yet</span>
            )}
          </p>
          <div className="mb-2 flex w-full max-w-[12rem] flex-col gap-1.5">
            {node.passages.map((p) => (
              <PassageLink key={p.id} passage={p} accentColor={color} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function PassageLink({ passage, accentColor }: { passage: MapPassageRef; accentColor: string }) {
  return (
    <Link
      href={`/read?passage_id=${encodeURIComponent(passage.id)}`}
      title={`Read "${passage.title}"`}
      onClick={(e) => {
        // A real click on a real story - navigation happens for real via
        // next/link below, this is purely the same delight layer real
        // buttons get elsewhere (components/ui/PlumpButton.tsx), scaled
        // down to fit this compact list rather than a full plump button.
        const rect = e.currentTarget.getBoundingClientRect();
        celebrate(rect.left + rect.width / 2, rect.top + rect.height / 2, 16);
        playPop("small");
      }}
      // Real feedback from a real recording: plain 11px text with a
      // hover-only background read as "not clickable" - a tiny target with
      // no visible affordance until the cursor happened to land right on
      // it. This is now a genuine pill button - filled, bordered, with a
      // trailing arrow - so which exact area responds to a tap is obvious
      // at a glance, not something to discover by poking around the card.
      className="group flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[11px] font-bold transition hover:-translate-y-0.5 hover:shadow-sm active:scale-95"
      style={{
        borderColor: `${accentColor}40`,
        backgroundColor: `${accentColor}14`,
        color: accentColor,
      }}
    >
      <span aria-hidden className="card-wiggle-icon inline-block shrink-0">
        {passage.attempted ? "✅" : "📖"}
      </span>
      <span className="truncate">{passage.title}</span>
      <span aria-hidden className="ml-auto shrink-0 opacity-60 transition group-hover:translate-x-0.5 group-hover:opacity-100">
        →
      </span>
    </Link>
  );
}
