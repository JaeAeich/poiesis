// Helpers shared by the home page's canvases and loops.
import { css } from "../core.js";

/** One frame at 60 fps, in ms; speeds are tuned per 60 fps frame. */
export const FRAME_MS = 16.7;
/** While nothing is happening, canvases draw at ~30 fps. */
export const IDLE_FRAME_MS = 33;
/** A long pause (tab in background) counts as at most this many frames. */
const MAX_FRAME_SCALE = 3;
/** A layer this covered by the next one is invisible; skip drawing it. */
const COVER_HIDDEN = 0.98;
/** Canvases never render above this pixel ratio. */
const MAX_DPR = 2;
/** Arc end angle slightly past 2π so stroked circles have no seam. */
export const FULL_CIRCLE = 7;

/**
 * Frame clock with an optional idle throttle. Call it with the frame timestamp; it returns how
 * many 60 fps frames have passed since the last drawn frame, or 0 when this frame should be
 * skipped because `throttle` is on and the idle interval has not elapsed.
 * @returns {(now: number, throttle?: boolean) => number}
 */
export function createFrameClock() {
  let lastFrame = 0;
  return (now, throttle = false) => {
    if (throttle && now - lastFrame < IDLE_FRAME_MS) return 0;
    const scale = Math.min(MAX_FRAME_SCALE, (now - (lastFrame || now)) / FRAME_MS) || 1;
    lastFrame = now;
    return scale;
  };
}

/**
 * Whether the section stack has slid the next layer fully over `layer`.
 * @param {HTMLElement} layer
 */
export const isCovered = (layer) => +(layer.dataset.cover || 0) > COVER_HIDDEN;

/** Device pixel ratio to render canvases at. */
export const canvasDpr = () => Math.min(MAX_DPR, devicePixelRatio || 1);

/**
 * Read a set of theme colours from CSS custom properties.
 * @template {Record<string, string>} T
 * @param {T} tokens map of name to custom property, e.g. { blue: "--blue" }
 * @returns {{ [K in keyof T]: string }}
 */
export function readColors(tokens) {
  const colors = {};
  for (const [name, property] of Object.entries(tokens)) colors[name] = css(property);
  return colors;
}

/**
 * Size a canvas's backing store for `dpr` and reset its transform to CSS pixels.
 * @param {HTMLCanvasElement} canvas
 * @param {CanvasRenderingContext2D} ctx
 */
export function sizeCanvas(canvas, ctx, width, height, dpr) {
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

/**
 * An offscreen canvas of `width` x `height` CSS px at `dpr`, with its context scaled to CSS px.
 * @returns {{ canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D }}
 */
export function createLayer(width, height, dpr) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, width * dpr);
  canvas.height = Math.max(1, height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  return { canvas, ctx };
}

/**
 * Fill a circle.
 * @param {CanvasRenderingContext2D} ctx
 */
export function fillCircle(ctx, x, y, radius) {
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, FULL_CIRCLE);
  ctx.fill();
}

/**
 * Stroke a circle.
 * @param {CanvasRenderingContext2D} ctx
 */
export function strokeCircle(ctx, x, y, radius) {
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, FULL_CIRCLE);
  ctx.stroke();
}
