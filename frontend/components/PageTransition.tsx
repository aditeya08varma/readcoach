"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { teardownConfetti } from "@/lib/confettiPop";

/**
 * App-wide route transitions - real feedback that navigating between
 * screens (home -> map -> read -> dashboard) was a hard, instant cut, which
 * reads as less polished than everything happening *within* one screen
 * (the map's own path entrance, the mascot, button presses). Keyed on the
 * real pathname so AnimatePresence treats each route as a distinct element
 * to cross-fade between, not a single persistent one it never unmounts.
 *
 * Kept deliberately short (180ms) and simple (fade + a small vertical
 * settle) - a transition that lingers reads as slow every single time you
 * click anything, which is a real cost paid on every navigation, not a
 * one-time flourish like the map's own entrance animation.
 */
export default function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const reduceMotion = useReducedMotion();

  // Real bug found by a second audit: a confetti burst spawned on the page
  // being left (e.g. Start Reading's celebrate() + router.push() in the same
  // handler) used to keep animating on top of whatever page loaded next -
  // lib/confettiPop.ts's canvas has no unmount hook of its own tied to
  // navigation. This is the one place that already observes every real
  // route change app-wide, so tearing the burst down the instant the
  // pathname changes closes that gap at the root instead of just capping
  // the burst's own duration further (see confettiPop.ts's teardownConfetti
  // for why that alone can't fully fix it).
  useEffect(() => {
    teardownConfetti();
  }, [pathname]);

  if (reduceMotion) {
    return <>{children}</>;
  }

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={pathname}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.18, ease: "easeOut" }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
