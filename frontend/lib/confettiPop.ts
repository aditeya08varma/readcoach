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

function step() {
  if (!ctx || !canvas) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const alive: Particle[] = [];
  for (const p of particles) {
    p.vy += 0.16;
    p.x += p.vx;
    p.y += p.vy;
    p.rot += p.vrot;
    p.life -= 0.014;
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
  rafId = particles.length > 0 ? requestAnimationFrame(step) : null;
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
