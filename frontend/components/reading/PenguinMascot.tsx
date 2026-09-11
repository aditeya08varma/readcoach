"use client";

import type { VoiceState } from "./VoiceIndicator";

// Real feedback: the reading screen's own coach presence was a single small
// emoji sitting in a status bar - functional, but plain next to how much
// character the rest of this app has ("soo bland and non engaging"). A real,
// hand-drawn (not emoji) mascot with parts that animate independently -
// blinking eyes, waving flippers, a talking beak - reads as a genuine
// companion the way Duolingo's owl does, not just a recolored icon. A
// penguin specifically, by explicit request - distinct from the owl used
// elsewhere as the app's own brand mark (home screen, login/signup); this
// one is the reading screen's own energetic companion, not a rebrand.

// A second, separate set of purely decorative poses for the map's trailside
// penguins - deliberately NOT folded into VoiceState above, since that type
// carries real meaning for the reading screen's actual pipeline (listening,
// thinking, speaking...) and "dancing" or "asleep" has no such real meaning
// there. `pose` takes over the root render entirely when set; `state` stays
// optional so decorative call sites don't need to fake a voice state just
// to satisfy the type.
//
// Real feedback on the first pass at this: every pose was the exact same
// standing silhouette with only one part moving differently, which reads as
// one character idly twitching, not four different actions. The way an
// actual well-known character like Duolingo's owl pulls this off is real,
// distinct artwork per pose, not one rig with a single animated joint - a
// sleeping pose lies down, a dancing pose has both arms out and a foot
// kicked, a singing pose has its mouth genuinely open around a microphone.
// Each pose below is its own real, separately drawn body for exactly that
// reason, sharing only this character's own established color palette so
// it still reads as the same penguin throughout.
//
// A second real round of feedback on that pass: the flat, unoutlined fills
// read as a rough first draft next to the rest of this app's own polish.
// Every silhouette-defining shape now carries a consistent dark outline
// (the actual thing that gives well-known flat-illustration characters,
// Duolingo's own owl included, their finished "sticker" look instead of a
// blob of color) rather than color meeting color with no edge at all.
export type PenguinPose = "wave" | "dance" | "sleep" | "sing";

const BODY_DARK = "#333a4d";
const BODY_CREAM = "#fdfbf5";
const BEAK = "#f5a742";
const BEAK_SHADOW = "#e08f2e";
const CHEEK = "#ffb4a8";
const OUTLINE = "#1c2130";

// Spread as props onto every silhouette-defining shape (body, limbs, feet,
// beak) so each one gets the exact same weight, color, and joint style of
// outline - a mismatched outline here or there would look like more of an
// oversight than having none at all.
const OUTLINE_PROPS = { stroke: OUTLINE, strokeWidth: 2.5, strokeLinejoin: "round" as const };
const OUTLINE_PROPS_SM = { stroke: OUTLINE, strokeWidth: 2, strokeLinejoin: "round" as const };

export default function PenguinMascot({
  state = "idle",
  pose,
  className = "",
}: {
  state?: VoiceState;
  pose?: PenguinPose;
  className?: string;
}) {
  if (pose) {
    return <PosePenguin pose={pose} className={className} />;
  }
  return (
    <svg viewBox="0 0 120 130" className={`penguin-${state} drop-shadow-sm ${className}`} aria-hidden>
      <g className="penguin-body">
        {/* feet */}
        <ellipse cx="45" cy="114" rx="10" ry="5" fill={BEAK} {...OUTLINE_PROPS_SM} />
        <ellipse cx="75" cy="114" rx="10" ry="5" fill={BEAK} {...OUTLINE_PROPS_SM} />
        {/* main body - dark back, cream belly */}
        <ellipse cx="60" cy="72" rx="36" ry="40" fill={BODY_DARK} {...OUTLINE_PROPS} />
        <ellipse cx="60" cy="80" rx="21" ry="28" fill={BODY_CREAM} stroke={OUTLINE} strokeWidth="1.6" />
        {/* flippers */}
        <ellipse
          className="penguin-flipper-left"
          cx="25"
          cy="64"
          rx="8.5"
          ry="21"
          fill={BODY_DARK}
          {...OUTLINE_PROPS_SM}
          style={{ transformOrigin: "25px 46px" }}
        />
        <ellipse
          className="penguin-flipper-right"
          cx="95"
          cy="64"
          rx="8.5"
          ry="21"
          fill={BODY_DARK}
          {...OUTLINE_PROPS_SM}
          style={{ transformOrigin: "95px 46px" }}
        />
        {/* baby head-fuzz */}
        <path d="M50 18 Q60 4 70 18" stroke={BODY_DARK} strokeWidth="5" fill="none" strokeLinecap="round" />
        {/* cheeks */}
        <circle cx="40" cy="60" r="6" fill={CHEEK} opacity="0.55" />
        <circle cx="80" cy="60" r="6" fill={CHEEK} opacity="0.55" />
        {/* eyes */}
        <g className="penguin-eyes">
          <circle cx="48" cy="50" r="9.5" fill="white" stroke={OUTLINE} strokeWidth="1.4" />
          <circle cx="72" cy="50" r="9.5" fill="white" stroke={OUTLINE} strokeWidth="1.4" />
          <circle cx="49.5" cy="51.5" r="4.8" fill="#20232d" />
          <circle cx="73.5" cy="51.5" r="4.8" fill="#20232d" />
          <circle cx="51.5" cy="49" r="1.6" fill="white" />
          <circle cx="75.5" cy="49" r="1.6" fill="white" />
        </g>
        {/* beak - upper fixed, lower animates for talking */}
        <path d="M52 61 L68 61 L60 65 Z" fill={BEAK} {...OUTLINE_PROPS_SM} />
        <path
          className="penguin-beak-lower"
          d="M53 65 L67 65 L60 71 Z"
          fill={BEAK_SHADOW}
          {...OUTLINE_PROPS_SM}
          style={{ transformOrigin: "60px 65px" }}
        />
      </g>
    </svg>
  );
}

function PosePenguin({ pose, className }: { pose: PenguinPose; className: string }) {
  const rootClass = `penguin-pose-${pose} drop-shadow-sm ${className}`;
  switch (pose) {
    case "wave":
      return <WavePenguin className={rootClass} />;
    case "dance":
      return <DancePenguin className={rootClass} />;
    case "sleep":
      return <SleepPenguin className={rootClass} />;
    case "sing":
      return <SingPenguin className={rootClass} />;
  }
}

// Standing tall, one long arm raised straight up by its own ear with a
// couple of motion arcs at the hand - the other arm stays down at its side,
// so the raised one reads as a deliberate greeting, not a symmetrical pose.
function WavePenguin({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 120 130" className={className} aria-hidden>
      <g className="penguin-body">
        <ellipse cx="45" cy="114" rx="10" ry="5" fill={BEAK} {...OUTLINE_PROPS_SM} />
        <ellipse cx="75" cy="114" rx="10" ry="5" fill={BEAK} {...OUTLINE_PROPS_SM} />
        <ellipse cx="60" cy="72" rx="36" ry="40" fill={BODY_DARK} {...OUTLINE_PROPS} />
        <ellipse cx="60" cy="80" rx="21" ry="28" fill={BODY_CREAM} stroke={OUTLINE} strokeWidth="1.6" />
        {/* resting left flipper */}
        <ellipse cx="26" cy="66" rx="8.5" ry="20" fill={BODY_DARK} {...OUTLINE_PROPS_SM} />
        {/* raised right arm, its own tip rounded out into the hand rather
            than a separate circle stacked on top - a second shape there,
            each with its own outline, was reading as a stray dot rather
            than a hand attached to the arm. */}
        <path
          className="penguin-flipper-right"
          d="M89 58 C98 53 106 42 107 28 C108 16 101 4 89 5 C79 6 75 15 79 23 C83 33 84 46 80 58 Z"
          fill={BODY_DARK}
          {...OUTLINE_PROPS_SM}
          style={{ transformOrigin: "30% 95%" }}
        />
        {/* wave motion arcs */}
        <path
          className="wave-motion-line"
          d="M112 8 Q120 6 117 15"
          stroke="white"
          strokeWidth="2.4"
          fill="none"
          strokeLinecap="round"
          opacity="0.85"
        />
        <path
          className="wave-motion-line"
          d="M114 22 Q122 22 118 29"
          stroke="white"
          strokeWidth="2.2"
          fill="none"
          strokeLinecap="round"
          opacity="0.6"
        />
        <path d="M50 18 Q60 4 70 18" stroke={BODY_DARK} strokeWidth="5" fill="none" strokeLinecap="round" />
        <circle cx="40" cy="60" r="6" fill={CHEEK} opacity="0.55" />
        <circle cx="80" cy="60" r="6" fill={CHEEK} opacity="0.55" />
        <g>
          <circle cx="48" cy="50" r="9.5" fill="white" stroke={OUTLINE} strokeWidth="1.4" />
          <circle cx="72" cy="50" r="9.5" fill="white" stroke={OUTLINE} strokeWidth="1.4" />
          <circle cx="49.5" cy="51.5" r="4.8" fill="#20232d" />
          <circle cx="73.5" cy="51.5" r="4.8" fill="#20232d" />
          <circle cx="51.5" cy="49" r="1.6" fill="white" />
          <circle cx="75.5" cy="49" r="1.6" fill="white" />
        </g>
        <path d="M52 61 L68 61 L60 65 Z" fill={BEAK} {...OUTLINE_PROPS_SM} />
        <path d="M53 65 L67 65 L60 70 Z" fill={BEAK_SHADOW} {...OUTLINE_PROPS_SM} />
      </g>
    </svg>
  );
}

// Both arms thrown out to the sides and one foot kicked up off the ground -
// the whole silhouette is off-balance in a way a standing penguin never is,
// which is what actually sells "mid dance move" rather than "standing
// still with wiggling arms."
function DancePenguin({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 120 130" className={className} aria-hidden>
      <g className="penguin-body">
        {/* planted foot */}
        <ellipse cx="78" cy="114" rx="10" ry="5" fill={BEAK} {...OUTLINE_PROPS_SM} />
        {/* kicked-out foot */}
        <ellipse cx="30" cy="98" rx="10" ry="5" fill={BEAK} {...OUTLINE_PROPS_SM} transform="rotate(-35 30 98)" />
        <ellipse cx="62" cy="72" rx="35" ry="39" fill={BODY_DARK} {...OUTLINE_PROPS} />
        <ellipse cx="63" cy="80" rx="20" ry="27" fill={BODY_CREAM} stroke={OUTLINE} strokeWidth="1.6" />
        {/* left arm thrown up-left */}
        <path
          className="penguin-flipper-left"
          d="M34 55 C22 48 14 32 18 16 C20 9 28 12 29 20 C31 31 36 46 42 57 Z"
          fill={BODY_DARK}
          {...OUTLINE_PROPS_SM}
          style={{ transformOrigin: "80% 95%" }}
        />
        {/* right arm thrown up-right */}
        <path
          className="penguin-flipper-right"
          d="M90 55 C102 48 110 32 106 16 C104 9 96 12 95 20 C93 31 88 46 82 57 Z"
          fill={BODY_DARK}
          {...OUTLINE_PROPS_SM}
          style={{ transformOrigin: "20% 95%" }}
        />
        <path d="M52 18 Q62 4 72 18" stroke={BODY_DARK} strokeWidth="5" fill="none" strokeLinecap="round" />
        <circle cx="43" cy="60" r="6" fill={CHEEK} opacity="0.6" />
        <circle cx="83" cy="60" r="6" fill={CHEEK} opacity="0.6" />
        {/* joyful closed, curved eyes */}
        <path d="M45 51 Q51 44 57 51" stroke={OUTLINE} strokeWidth="3.4" fill="none" strokeLinecap="round" />
        <path d="M69 51 Q75 44 81 51" stroke={OUTLINE} strokeWidth="3.4" fill="none" strokeLinecap="round" />
        <path d="M55 61 L71 61 L63 65 Z" fill={BEAK} {...OUTLINE_PROPS_SM} />
        <path d="M56 65 L70 65 L63 70 Z" fill={BEAK_SHADOW} {...OUTLINE_PROPS_SM} />
      </g>
    </svg>
  );
}

// Lying down, not standing propped up - tipped onto its back with a pillow
// under the head and a small blanket over its feet, eyes shut as flat
// resting lines instead of the standing character's round open ones.
function SleepPenguin({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 120 130" className={className} aria-hidden>
      {/* pillow, drawn first so the head overlaps its near edge */}
      <ellipse cx="28" cy="78" rx="20" ry="13" fill="#fef3c7" stroke={OUTLINE} strokeWidth="2" />
      <g className="penguin-body">
        {/* reclined body, rotated onto its back rather than standing */}
        <g transform="rotate(-90 60 72)">
          <ellipse cx="60" cy="72" rx="36" ry="40" fill={BODY_DARK} {...OUTLINE_PROPS} />
          <ellipse cx="60" cy="80" rx="21" ry="28" fill={BODY_CREAM} stroke={OUTLINE} strokeWidth="1.6" />
          <ellipse cx="25" cy="64" rx="8.5" ry="20" fill={BODY_DARK} {...OUTLINE_PROPS_SM} />
          <ellipse cx="95" cy="64" rx="8.5" ry="20" fill={BODY_DARK} {...OUTLINE_PROPS_SM} />
          <circle cx="40" cy="60" r="6" fill={CHEEK} opacity="0.5" />
          <circle cx="80" cy="60" r="6" fill={CHEEK} opacity="0.5" />
          {/* closed, resting eyes */}
          <path d="M43 50 Q48 53 53 50" stroke={OUTLINE} strokeWidth="3" fill="none" strokeLinecap="round" />
          <path d="M67 50 Q72 53 77 50" stroke={OUTLINE} strokeWidth="3" fill="none" strokeLinecap="round" />
          <path d="M52 61 L68 61 L60 65 Z" fill={BEAK} {...OUTLINE_PROPS_SM} />
        </g>
      </g>
      {/* blanket over the lower half, tucked over the feet */}
      <path d="M4 92 Q60 74 116 92 L116 124 Q60 138 4 124 Z" fill="#c7d2fe" stroke={OUTLINE} strokeWidth="2" opacity="0.95" />
    </svg>
  );
}

// Standing tall with its mouth genuinely open around a held microphone,
// rather than the standing character's small closed beak - the open mouth
// and the mic are what make "singing" legible on their own, before the
// floating music-note badge next to it adds the rest.
function SingPenguin({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 120 130" className={className} aria-hidden>
      <g className="penguin-body">
        <ellipse cx="45" cy="114" rx="10" ry="5" fill={BEAK} {...OUTLINE_PROPS_SM} />
        <ellipse cx="75" cy="114" rx="10" ry="5" fill={BEAK} {...OUTLINE_PROPS_SM} />
        <ellipse cx="60" cy="72" rx="36" ry="40" fill={BODY_DARK} {...OUTLINE_PROPS} />
        <ellipse cx="60" cy="80" rx="21" ry="28" fill={BODY_CREAM} stroke={OUTLINE} strokeWidth="1.6" />
        <ellipse cx="26" cy="66" rx="8.5" ry="20" fill={BODY_DARK} {...OUTLINE_PROPS_SM} />
        {/* arm raised, holding the mic up by the mouth */}
        <path
          className="penguin-flipper-right"
          d="M88 58 C99 52 105 34 101 18 C100 11 92 13 92 21 C92 32 86 46 80 58 Z"
          fill={BODY_DARK}
          {...OUTLINE_PROPS_SM}
          style={{ transformOrigin: "30% 95%" }}
        />
        <rect x="95" y="14" width="4.5" height="15" rx="2.2" fill="#9ca3af" stroke={OUTLINE} strokeWidth="1.4" />
        <circle cx="97" cy="11" r="6.5" fill="#4b5563" stroke={OUTLINE} strokeWidth="1.4" />
        <path d="M50 18 Q60 4 70 18" stroke={BODY_DARK} strokeWidth="5" fill="none" strokeLinecap="round" />
        <circle cx="40" cy="60" r="6" fill={CHEEK} opacity="0.55" />
        <circle cx="80" cy="60" r="6" fill={CHEEK} opacity="0.55" />
        {/* eyes shut with feeling */}
        <path d="M45 51 Q51 45 57 51" stroke={OUTLINE} strokeWidth="3.2" fill="none" strokeLinecap="round" />
        <path d="M69 51 Q75 45 81 51" stroke={OUTLINE} strokeWidth="3.2" fill="none" strokeLinecap="round" />
        {/* wide open singing mouth */}
        <path d="M48 58 L72 58 L60 64 Z" fill={BEAK} {...OUTLINE_PROPS_SM} />
        <ellipse
          className="penguin-beak-lower"
          cx="60"
          cy="68"
          rx="9"
          ry="8"
          fill="#7a2e2e"
          stroke={OUTLINE}
          strokeWidth="2"
          style={{ transformOrigin: "50% 0%" }}
        />
        <ellipse cx="60" cy="72" rx="4" ry="2.6" fill="#c9645f" />
      </g>
    </svg>
  );
}
