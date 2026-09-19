import Link from "next/link";

const SIZE_CLASSES = {
  sm: "text-lg sm:text-xl",
  md: "text-2xl sm:text-3xl",
  lg: "text-4xl sm:text-5xl",
} as const;

// The brand mark stays one fixed color pairing everywhere, independent of
// each page's own identity color (violet dashboard, emerald map, indigo
// admin, etc.) - only the "Read" half's color flips between light/dark so
// it stays legible on both a saturated gradient and a near-white canvas.
// "Coach" keeps the same amber across both: it's the one accent every page
// already shares (the "Start Reading" button, marigold cards, floaty 🔤).
const TONE_CLASSES = {
  light: { read: "text-white drop-shadow-sm", coach: "text-amber-300 drop-shadow-sm" },
  dark: { read: "text-slate-800", coach: "text-amber-500" },
} as const;

export default function Logo({
  size = "md",
  tone = "light",
  href = "/",
  className = "",
}: {
  size?: keyof typeof SIZE_CLASSES;
  tone?: keyof typeof TONE_CLASSES;
  href?: string | null;
  className?: string;
}) {
  const t = TONE_CLASSES[tone];
  const mark = (
    <span
      className={`font-[family-name:var(--font-kid)] font-extrabold tracking-tight ${SIZE_CLASSES[size]} ${className}`}
    >
      <span className={t.read}>Read</span>
      <span className={t.coach}>Coach</span>
    </span>
  );
  if (!href) return mark;
  return (
    <Link href={href} className="inline-flex items-center transition hover:opacity-90">
      {mark}
    </Link>
  );
}
