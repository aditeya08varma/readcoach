// Real gap found by audit: zero automated tests existed anywhere in the
// frontend, despite this file's own comments documenting two separate real
// bugs found from real testing (the rAF-frame-count vs. wall-clock decay bug,
// and - fixed in this same pass - the cross-route confetti bleed teardown
// gap). These tests cover both: particle lifecycle/decay timing, and the new
// route-change teardown behavior.
//
// Canvas 2D rendering isn't implemented by jsdom without the native `canvas`
// package, so HTMLCanvasElement.prototype.getContext is stubbed with a
// minimal fake covering only the drawing calls confettiPop.ts actually makes
// (clearRect/save/restore/translate/rotate/fillRect/beginPath/arc/fill/
// setTransform) - enough for the real decay/lifecycle math to run for real,
// without needing a native canvas build in this environment.
//
// requestAnimationFrame/cancelAnimationFrame are stubbed so each frame can be
// driven manually with a controlled `now`, making the wall-clock decay math
// (lastFrameTime/dtScale) deterministic instead of depending on real timers.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { celebrate, teardownConfetti } from "./confettiPop";

function makeFakeCtx(): CanvasRenderingContext2D {
  const ctx = {
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    rotate: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    fillRect: vi.fn(),
    setTransform: vi.fn(),
    fillStyle: "",
    globalAlpha: 1,
  };
  return ctx as unknown as CanvasRenderingContext2D;
}

const originalGetContext = HTMLCanvasElement.prototype.getContext;

describe("lib/confettiPop.ts", () => {
  // A real Map keyed by handle (not a plain array) so the mocked
  // cancelAnimationFrame can faithfully remove a pending frame the way a
  // real browser does - an earlier version of this mock used a plain array
  // that cancelAnimationFrame never actually shrank, which made a
  // teardown-then-fresh-burst test flake (it saw the old, already-cancelled
  // frame still "pending" and miscounted).
  let rafQueue: Map<number, FrameRequestCallback>;
  let rafHandle: number;

  beforeEach(() => {
    document.body.innerHTML = "";
    teardownConfetti();
    rafQueue = new Map();
    rafHandle = 0;

    HTMLCanvasElement.prototype.getContext = ((): unknown =>
      makeFakeCtx()) as typeof HTMLCanvasElement.prototype.getContext;

    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      const handle = ++rafHandle;
      rafQueue.set(handle, cb);
      return handle;
    });
    vi.stubGlobal("cancelAnimationFrame", (handle: number) => {
      rafQueue.delete(handle);
    });
    // jsdom logs "Not implemented" noise for matchMedia by default.
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })
    );
  });

  afterEach(() => {
    teardownConfetti();
    HTMLCanvasElement.prototype.getContext = originalGetContext;
    vi.unstubAllGlobals();
  });

  function shiftNextFrame(): FrameRequestCallback | undefined {
    const nextHandle = Math.min(...rafQueue.keys());
    if (!Number.isFinite(nextHandle)) return undefined;
    const cb = rafQueue.get(nextHandle);
    rafQueue.delete(nextHandle);
    return cb;
  }

  function runUntilIdle(frameGapMs: number, maxFrames = 1000) {
    let now = 0;
    let frames = 0;
    while (rafQueue.size > 0 && frames < maxFrames) {
      now += frameGapMs;
      shiftNextFrame()?.(now);
      frames += 1;
    }
    return { now, frames };
  }

  it("appends exactly one canvas to document.body on the first burst", () => {
    celebrate(100, 100, 5);
    expect(document.body.querySelectorAll("canvas").length).toBe(1);
  });

  it("reuses the same canvas singleton across multiple bursts", () => {
    celebrate(50, 50, 3);
    celebrate(60, 60, 3);
    expect(document.body.querySelectorAll("canvas").length).toBe(1);
  });

  it("decays a burst to completion in roughly its documented ~1.2s wall-clock lifetime at 60fps", () => {
    celebrate(100, 100, 24);
    expect(rafQueue.size).toBe(1);

    const { now, frames } = runUntilIdle(1000 / 60);

    // The loop stops rescheduling itself once every particle's life <= 0 -
    // no callback left queued means the burst is genuinely over.
    expect(rafQueue.size).toBe(0);
    expect(frames).toBeGreaterThan(0);
    expect(now).toBeGreaterThan(900);
    expect(now).toBeLessThan(1600);
  });

  it("keeps a burst's real lifetime bounded across large frame gaps, not tied to frame count", () => {
    // Real bug this guards against (see confettiPop.ts's lastFrameTime
    // comment): decay used to advance by a fixed amount per callback
    // regardless of real elapsed time, so a throttled/backgrounded tab
    // (fewer, larger gaps between delivered frames) made a burst last far
    // longer in real time. Tracking wall-clock time means far fewer, much
    // bigger frames should still clear the burst, not stretch it out.
    celebrate(100, 100, 24);
    const { frames } = runUntilIdle(250);

    expect(rafQueue.size).toBe(0);
    expect(frames).toBeLessThan(15);
  });

  it("teardownConfetti removes the canvas, cancels the pending frame, and stops the loop immediately", () => {
    celebrate(100, 100, 24);
    expect(document.body.querySelectorAll("canvas").length).toBe(1);
    expect(rafQueue.size).toBe(1);

    teardownConfetti();

    expect(document.body.querySelectorAll("canvas").length).toBe(0);
    // The pending frame was genuinely cancelled (cancelAnimationFrame),
    // matching real browser semantics - it will never fire at all, not just
    // fire-and-no-op.
    expect(rafQueue.size).toBe(0);
  });

  it("a frame reference captured before teardown no-ops if it still runs (defense in depth)", () => {
    // Belt-and-suspenders on top of the real cancelAnimationFrame call
    // above: step() itself checks the current canvas/ctx state at the top
    // before touching anything, so even a stray reference to an old frame
    // (held outside this module's own bookkeeping) can't repaint or
    // resurrect state after a teardown.
    celebrate(100, 100, 24);
    const [[, staleCallback]] = [...rafQueue.entries()];
    expect(staleCallback).toBeDefined();

    teardownConfetti();

    expect(() => staleCallback(9999)).not.toThrow();
    // No new frame got scheduled by the stale callback firing post-teardown.
    expect(rafQueue.size).toBe(0);
    expect(document.body.querySelectorAll("canvas").length).toBe(0);
  });

  it("a fresh burst after teardown starts clean with its own canvas and frame", () => {
    celebrate(100, 100, 24);
    teardownConfetti();

    celebrate(100, 100, 5);
    expect(document.body.querySelectorAll("canvas").length).toBe(1);
    expect(rafQueue.size).toBe(1);
  });

  it("is a no-op to call teardownConfetti when nothing is running", () => {
    expect(() => teardownConfetti()).not.toThrow();
    expect(document.body.querySelectorAll("canvas").length).toBe(0);
  });
});
