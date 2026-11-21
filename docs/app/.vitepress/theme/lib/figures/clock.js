// Frame timing shared by the figures.

/** A long gap between frames (tab hidden, figure scrolled away) counts as at most this, ms. */
const MAX_FRAME_MS = 50;

/**
 * Returns a function that turns rAF timestamps into the ms elapsed since the previous call
 * (0 on the first call, capped at MAX_FRAME_MS).
 * @returns {(now: number) => number}
 */
export function createDeltaClock() {
  let last = 0;
  return (now) => {
    const elapsed = Math.min(MAX_FRAME_MS, now - (last || now));
    last = now;
    return elapsed;
  };
}
