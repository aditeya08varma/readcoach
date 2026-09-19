// Trail companions for the story map's own margin decorations
// (components/map/StoryMapView.tsx) - real feedback that a plain 📖/⭐/🐟/☁️
// emoji looked like an afterthought next to the penguin's own hand-drawn,
// animated illustration sitting right beside it in the same margin. Three
// real characters, each its own genuinely separate drawing (not one shape
// recolored three times) sharing PenguinMascot.tsx's exact palette and
// outline weight so they read as native to this app's own illustration
// style, not a mismatched import.
//
// Each gets its own distinct animation, the same real principle the
// penguin's own poses already established: a bookworm wiggling out of its
// book, a star twinkling in place, a cloud drifting - not the same generic
// motion recolored three times. All three are plain CSS @keyframes (see
// app/globals.css), not GSAP - simple, single-part, always-looping
// decorative motion, the same reasoning PenguinMascot.tsx's own pose
// characters use for staying CSS-driven.

import { BEAK, BEAK_SHADOW, BODY_CREAM, CHEEK, OUTLINE, OUTLINE_PROPS, OUTLINE_PROPS_SM } from "@/components/reading/PenguinMascot";

export type TrailCompanionKind = "bookworm" | "star" | "cloud";

const WORM_GREEN = "#7cb87a";
const WORM_GREEN_DARK = "#5a9a58";

export default function TrailCompanion({
  kind,
  className = "",
}: {
  kind: TrailCompanionKind;
  className?: string;
}) {
  switch (kind) {
    case "bookworm":
      return <BookwormCompanion className={className} />;
    case "star":
      return <StarCompanion className={className} />;
    case "cloud":
      return <CloudCompanion className={className} />;
  }
}

// A little worm, three stacked segments shrinking toward the head, poking
// straight up out of the gap between an open book's two pages - the whole
// point is "caught in the middle of reading," not a worm that happens to be
// standing near a book.
function BookwormCompanion({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 120 108" className={`trail-bookworm ${className}`} aria-hidden>
      {/* open book, two pages meeting at a center spine */}
      <g>
        <path
          d="M60 40 L14 30 Q10 30 10 34 L10 88 Q10 92 14 92 L60 84 Z"
          fill={BODY_CREAM}
          {...OUTLINE_PROPS}
        />
        <path
          d="M60 40 L106 30 Q110 30 110 34 L110 88 Q110 92 106 92 L60 84 Z"
          fill={BODY_CREAM}
          {...OUTLINE_PROPS}
        />
        {/* page lines, purely decorative */}
        <path d="M20 46 L54 40" stroke={`${OUTLINE}55`} strokeWidth="1.6" strokeLinecap="round" />
        <path d="M20 56 L55 50" stroke={`${OUTLINE}55`} strokeWidth="1.6" strokeLinecap="round" />
        <path d="M100 46 L66 40" stroke={`${OUTLINE}55`} strokeWidth="1.6" strokeLinecap="round" />
        <path d="M100 56 L65 50" stroke={`${OUTLINE}55`} strokeWidth="1.6" strokeLinecap="round" />
        <path d="M60 40 L60 84" stroke={OUTLINE} strokeWidth="2" />
      </g>
      {/* worm, poking up through the spine gap */}
      <g className="trail-bookworm-body">
        <ellipse cx="60" cy="58" rx="13" ry="11" fill={WORM_GREEN_DARK} {...OUTLINE_PROPS_SM} />
        <ellipse cx="60" cy="38" rx="11" ry="10" fill={WORM_GREEN} {...OUTLINE_PROPS_SM} />
        <circle cx="60" cy="18" r="10" fill={WORM_GREEN} {...OUTLINE_PROPS_SM} />
        {/* antennae */}
        <path d="M54 10 L51 2" stroke={OUTLINE} strokeWidth="1.8" strokeLinecap="round" />
        <path d="M66 10 L69 2" stroke={OUTLINE} strokeWidth="1.8" strokeLinecap="round" />
        <circle cx="51" cy="2" r="2" fill={BEAK} stroke={OUTLINE} strokeWidth="1" />
        <circle cx="69" cy="2" r="2" fill={BEAK} stroke={OUTLINE} strokeWidth="1" />
        {/* face */}
        <circle cx="40" cy="60" r="2.6" fill={CHEEK} opacity="0.7" />
        <circle cx="80" cy="60" r="2.6" fill={CHEEK} opacity="0.7" />
        <g className="trail-bookworm-eyes">
          <circle cx="55" cy="17" r="3.4" fill="white" stroke={OUTLINE} strokeWidth="1" />
          <circle cx="65" cy="17" r="3.4" fill="white" stroke={OUTLINE} strokeWidth="1" />
          <circle cx="55.8" cy="17.8" r="1.7" fill="#20232d" />
          <circle cx="65.8" cy="17.8" r="1.7" fill="#20232d" />
        </g>
        <path d="M57 23 Q60 25.5 63 23" stroke={OUTLINE} strokeWidth="1.6" fill="none" strokeLinecap="round" />
      </g>
    </svg>
  );
}

// A rounded, five-pointed star with a face - built from one smooth path
// (curved points, not sharp ones) so it stays inside this app's own
// friendly, nothing-sharp illustration language.
function StarCompanion({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 100 100" className={`trail-star ${className}`} aria-hidden>
      <g className="trail-star-body">
        <path
          d="M50 6 C53 22 56 30 62 34 C77 30 84 33 84 33 C84 33 76 41 71 50 C76 59 84 67 84 67 C84 67 77 70 62 66 C56 70 53 78 50 94 C47 78 44 70 38 66 C23 70 16 67 16 67 C16 67 24 59 29 50 C24 41 16 33 16 33 C16 33 23 30 38 34 C44 30 47 22 50 6 Z"
          fill={BEAK}
          {...OUTLINE_PROPS}
        />
        <circle cx="42" cy="46" r="7" fill={CHEEK} opacity="0.5" />
        <circle cx="58" cy="46" r="7" fill={CHEEK} opacity="0.5" />
        <g className="trail-star-eyes">
          <circle cx="43" cy="44" r="3.6" fill="white" stroke={OUTLINE} strokeWidth="1.2" />
          <circle cx="57" cy="44" r="3.6" fill="white" stroke={OUTLINE} strokeWidth="1.2" />
          <circle cx="44" cy="45" r="1.8" fill="#20232d" />
          <circle cx="58" cy="45" r="1.8" fill="#20232d" />
        </g>
        <path d="M45 53 Q50 57 55 53" stroke={OUTLINE} strokeWidth="1.8" fill="none" strokeLinecap="round" />
      </g>
      {/* twinkle marks, independent of the star's own body so they can
          pulse on their own beat instead of moving with the face */}
      <path className="trail-star-sparkle trail-star-sparkle-a" d="M14 14 L17 21 L24 24 L17 27 L14 34 L11 27 L4 24 L11 21 Z" fill={BEAK_SHADOW} />
      <path className="trail-star-sparkle trail-star-sparkle-b" d="M88 62 L90 67 L95 69 L90 71 L88 76 L86 71 L81 69 L86 67 Z" fill={BEAK_SHADOW} />
    </svg>
  );
}

// A fluffy, low, wide cloud - three overlapping puffs, not one blobby
// ellipse - with a content, sleepy-happy face, drawn from the same
// closed-eye "joy" line the map's own dancing/singing penguins already use.
function CloudCompanion({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 140 90" className={`trail-cloud ${className}`} aria-hidden>
      <g className="trail-cloud-body">
        <ellipse cx="45" cy="52" rx="30" ry="24" fill={BODY_CREAM} {...OUTLINE_PROPS} />
        <ellipse cx="95" cy="52" rx="30" ry="24" fill={BODY_CREAM} {...OUTLINE_PROPS} />
        <ellipse cx="70" cy="38" rx="34" ry="26" fill={BODY_CREAM} {...OUTLINE_PROPS} />
        <ellipse cx="70" cy="60" rx="55" ry="20" fill={BODY_CREAM} {...OUTLINE_PROPS} />
        <circle cx="52" cy="52" r="6" fill={CHEEK} opacity="0.5" />
        <circle cx="88" cy="52" r="6" fill={CHEEK} opacity="0.5" />
        <path d="M48 46 Q54 40 60 46" stroke={OUTLINE} strokeWidth="2.6" fill="none" strokeLinecap="round" />
        <path d="M80 46 Q86 40 92 46" stroke={OUTLINE} strokeWidth="2.6" fill="none" strokeLinecap="round" />
        <path d="M62 58 Q70 63 78 58" stroke={OUTLINE} strokeWidth="2.2" fill="none" strokeLinecap="round" />
      </g>
    </svg>
  );
}
