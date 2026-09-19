"use client";

import type { ButtonHTMLAttributes } from "react";
import { motion } from "framer-motion";
import { celebrate, playPop, type PopKind } from "@/lib/confettiPop";

type PlumpVariant = "primary" | "secondary" | "white";

const VARIANT_CLASSES: Record<PlumpVariant, string> = {
  primary: "btn-3d-amber bg-gradient-to-b from-amber-400 to-amber-500 text-white",
  secondary: "btn-3d-sky bg-gradient-to-b from-sky-500 to-sky-600 text-white",
  white: "btn-3d-white bg-white text-sky-700 ring-1 ring-sky-200",
};

// Wraps a real onClick with the same tactile press + confetti + synthesized
// pop used in the Storybook Arcade design concept - the visual/audio layer
// is purely additive here, never a replacement for the button's actual
// behavior, which is why this only ever forwards to a real onClick rather
// than owning any app logic itself.
export default function PlumpButton({
  variant = "secondary",
  pop = "secondary",
  confettiCount,
  className = "",
  onClick,
  disabled,
  children,
  ...rest
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onDrag" | "onDragStart" | "onDragEnd" | "onAnimationStart"> & {
  variant?: PlumpVariant;
  pop?: PopKind;
  confettiCount?: number;
}) {
  function handleClick(e: React.MouseEvent<HTMLButtonElement>) {
    if (!disabled) {
      const rect = e.currentTarget.getBoundingClientRect();
      celebrate(
        rect.left + rect.width / 2,
        rect.top + rect.height / 2,
        confettiCount ?? (variant === "primary" ? 42 : 22)
      );
      playPop(pop);
      const el = e.currentTarget;
      el.classList.remove("btn-bounce");
      void el.offsetWidth;
      el.classList.add("btn-bounce");
    }
    onClick?.(e);
  }

  return (
    // Real gap found while auditing what actually happens on hover here:
    // nothing did - only a real click triggered any feedback at all (the
    // existing btn-3d press, confetti, sound). whileHover adds a real,
    // separate spring lift BEFORE a click even happens, deliberately scoped
    // to hover only (no whileTap) so it never fights the existing CSS 3D
    // press-down effect that already owns the actual click moment.
    <motion.button
      {...rest}
      disabled={disabled}
      onClick={handleClick}
      whileHover={disabled ? undefined : { scale: 1.03, y: -2 }}
      transition={{ type: "spring", stiffness: 400, damping: 17 }}
      className={`btn-3d inline-flex items-center justify-center gap-2 rounded-3xl px-7 py-3.5 font-[family-name:var(--font-kid)] text-lg font-bold disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT_CLASSES[variant]} ${className}`}
    >
      {children}
    </motion.button>
  );
}
