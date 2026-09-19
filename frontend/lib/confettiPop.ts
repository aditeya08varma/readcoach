// Shared "delight" layer for real, functional buttons - a confetti burst and
// a synthesized Web Audio pop, extracted from the Storybook Arcade design
// concept and wired to actual click handlers instead of purely decorative
// ones. Lazy-initialized (canvas + AudioContext) since this only ever runs
// client-side, from inside a real onClick.

type PopKind = "primary" | "secondary" | "small";

let canvas: HTMLCanvasElement | null = null;
let ctx: CanvasRenderingContext2D | null = null;
let particles: Particle[] = [];
let rafId: number | null = null;
let audioCtx: AudioContext | null = null;
// Real bug found from real testing: physics and decay used to advance by a
// fixed amount every animation-frame callback, so a burst's real lifespan
// depended entirely on how often the browser actually delivered rAF frames.
// A tab that's momentarily backgrounded, occluded, or just busy (like during
// a route transition) throttles rAF hard, and a burst meant to fully fade in
// ~1.2s could instead take 10+ real seconds to clear - long enough that its
// particles are still visibly falling over whatever page the user has since
// navigated to (e.g. stray dots drifting over the dashboard's fluency chart,
// or lingering around the reading screen's own Start Reading button after a
// short passage already finished). Tracking real elapsed time and scaling
// every increment by it keeps a burst's true wall-clock lifetime bounded to
// roughly the same ~1.2s regardless of frame rate, so leftover particles
// can never meaningfully outlive the page/interaction that spawned them.
let lastFrameTime = 0;

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  color: string;
  rot: number;
  vrot: number;
  life: number;
  shape: "rect" | "circle";
}

const CONFETTI_COLORS = ["#f43f5e", "#f59e0b", "#8b5cf6", "#10b981", "#0ea5e9"];

function ensureCanvas(): HTMLCanvasElement {
  if (canvas) return canvas;
  canvas = document.createElement("canvas");
  canvas.style.position = "fixed";
  canvas.style.inset = "0";
  canvas.style.pointerEvents = "none";
  canvas.style.zIndex = "999";
  document.body.appendChild(canvas);
  ctx = canvas.getContext("2d");
  resize();
  window.addEventListener("resize", resize);
  return canvas;
}

function resize() {
  if (!canvas || !ctx) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = window.innerWidth * dpr;
  canvas.height = window.innerHeight * dpr;
  canvas.style.width = window.innerWidth + "px";
  canvas.style.height = window.innerHeight + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function step(now: number = performance.now()) {
  if (!ctx || !canvas) return;
  // Scaled against a 60fps baseline (~16.67ms/frame) so every increment
  // below still reads exactly as before at 60fps, but now tracks real time
  // elapsed instead of just "one callback happened" - see lastFrameTime's
  // own comment above for why that distinction is the actual fix. Not
  // clamped: a big gap (a throttled/backgrounded tab finally getting a
  // frame) should let a burst catch up and finish immediately rather than
  // linger, which is the whole point.
  const dtScale = lastFrameTime ? (now - lastFrameTime) / (1000 / 60) : 1;
  lastFrameTime = now;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const alive: Particle[] = [];
  for (const p of particles) {
    p.vy += 0.16 * dtScale;
    p.x += p.vx * dtScale;
    p.y += p.vy * dtScale;
    p.rot += p.vrot * dtScale;
    p.life -= 0.014 * dtScale;
    if (p.life > 0 && p.y < window.innerHeight + 40) {
      alive.push(p);
      ctx.save();
      ctx.globalAlpha = Math.max(p.life, 0);
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      if (p.shape === "rect") {
        ctx.fillRect(-p.size / 2, -p.size / 3, p.size, p.size * 0.66);
      } else {
        ctx.beginPath();
        ctx.arc(0, 0, p.size / 2.4, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }
  }
  particles = alive;
  if (particles.length > 0) {
    rafId = requestAnimationFrame(step);
  } else {
    rafId = null;
    // Reset so the next burst's very first frame computes a fresh dtScale
    // of 1 instead of one huge jump from however long the canvas sat idle.
    lastFrameTime = 0;
  }
}

/** Confetti burst centered at (x, y) in viewport coordinates. */
export function celebrate(x: number, y: number, count = 24) {
  if (typeof window === "undefined") return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  ensureCanvas();
  for (let i = 0; i < count; i++) {
    const angle = Math.random() * Math.PI * 2;
    const speed = 2.4 + Math.random() * 4.2;
    particles.push({
      x,
      y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed - 2.4,
      size: 5 + Math.random() * 5,
      color: CONFETTI_COLORS[(Math.random() * CONFETTI_COLORS.length) | 0],
      rot: Math.random() * Math.PI,
      vrot: (Math.random() - 0.5) * 0.4,
      life: 1,
      shape: Math.random() < 0.5 ? "rect" : "circle",
    });
  }
  if (!rafId) rafId = requestAnimationFrame(step);
}

/**
 * Fully tears down any in-flight confetti burst: cancels the animation
 * loop, drops every particle, and removes the canvas (and its resize
 * listener) from the DOM. Real bug found by a second audit on top of the
 * wall-clock decay fix above: even a burst bounded to ~1.2s is still long
 * enough to visibly bleed across a client-side route change, since
 * `celebrate()` and `router.push()` are called back-to-back in the same
 * handler (see app/page.tsx's handleStartReading) - the canvas is a
 * document.body-level singleton with no React ownership, so nothing ever
 * unmounted it when the page that spawned it went away. The same leftover
 * canvas (fixed, full-viewport, zIndex 999, pointer-events none) is also
 * what a second symptom - celebration glyphs briefly appearing over the
 * reading screen's subtitle on load - actually was: not a separate bug, just
 * this same overlay still drawing on top of whatever mounted next.
 *
 * Call this on every route change (see components/PageTransition.tsx, the
 * one place that already observes every navigation app-wide) instead of
 * further capping the burst's own duration - that only shrinks the window,
 * it can't close it, since a fast-enough navigation can always outrace any
 * fixed duration.
 */
export function teardownConfetti() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
  particles = [];
  lastFrameTime = 0;
  if (canvas) {
    if (typeof window !== "undefined") {
      window.removeEventListener("resize", resize);
    }
    canvas.remove();
  }
  canvas = null;
  ctx = null;
}

const POP_PRESETS: Record<PopKind, { f0: number; f1: number; dur: number; gain: number; shimmer: boolean }> = {
  primary: { f0: 480, f1: 1180, dur: 0.16, gain: 0.22, shimmer: true },
  secondary: { f0: 560, f1: 1080, dur: 0.11, gain: 0.16, shimmer: false },
  small: { f0: 640, f1: 1020, dur: 0.08, gain: 0.11, shimmer: false },
};

function getAudioCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  if (!audioCtx) audioCtx = new AC();
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

/** A short, cute synthesized "pop" - no audio assets, generated on the fly. */
export function playPop(kind: PopKind = "secondary") {
  const c = getAudioCtx();
  if (!c) return;
  const now = c.currentTime;
  const p = POP_PRESETS[kind];

  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = "sine";
  osc.frequency.setValueAtTime(p.f0, now);
  osc.frequency.exponentialRampToValueAtTime(p.f1, now + p.dur);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(p.gain, now + 0.008);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + p.dur + 0.06);
  osc.connect(gain).connect(c.destination);
  osc.start(now);
  osc.stop(now + p.dur + 0.08);

  if (p.shimmer) {
    const osc2 = c.createOscillator();
    const gain2 = c.createGain();
    osc2.type = "triangle";
    osc2.frequency.setValueAtTime(p.f1 * 1.5, now + p.dur * 0.4);
    gain2.gain.setValueAtTime(0.0001, now + p.dur * 0.4);
    gain2.gain.exponentialRampToValueAtTime(0.09, now + p.dur * 0.45);
    gain2.gain.exponentialRampToValueAtTime(0.0001, now + p.dur + 0.14);
    osc2.connect(gain2).connect(c.destination);
    osc2.start(now + p.dur * 0.4);
    osc2.stop(now + p.dur + 0.16);
  }
}

export type { PopKind };
