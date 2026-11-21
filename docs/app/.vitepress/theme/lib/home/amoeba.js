// One large amoeba resting in the hero's top-left corner, organelles visible. Hover it and a
// pseudopod reaches for the pointer; click inside it and it engulfs food.
import { lerp } from "../core.js";
import { FOOD_LIFE_MS, drawOrganelles } from "./amoebaOrganelles.js";

const WIDE_STAGE = 760; // px; narrower stages get a smaller amoeba
const WIDE_SCALE = 0.3; // radius as a fraction of the smaller stage side
const NARROW_SCALE = 0.24;
const WIDE_MAX_RADIUS = 270;
const NARROW_MAX_RADIUS = 150;
const HIT_SCALE = 1.08; // pointer counts as inside up to this times the radius
const OUTLINE_POINTS = 72;
const PSEUDOPOD_SIZE = 0.38;
const PSEUDOPOD_SHARPNESS = 8;
const REACH_RATE = 0.05; // per frame, towards 1 while hovered and 0 otherwise
const TURN_RATE = 0.08; // per frame, of the angle left to the pointer
const BODY_SHIFT = 0.08; // the cytoplasm leans this far (of the radius) into the pseudopod
const MAX_FOOD = 4;

/**
 * @typedef {{ x: number, y: number, t0: number }} Food
 * @typedef {object} Amoeba
 * @property {number} seed varies the outline's wobble
 * @property {number} cx current centre, px
 * @property {number} cy
 * @property {number} R current radius, px (0 before the first frame)
 * @property {number} px pointer position while hovered
 * @property {number} py
 * @property {boolean} on hovered
 * @property {number} reach pseudopod extension, 0..1
 * @property {number} pa pseudopod angle, radians
 * @property {Food[]} food
 */

/** @returns {Amoeba} */
export const createAmoeba = () => ({
  seed: Math.random() * 100,
  cx: 0,
  cy: 0,
  R: 0,
  px: 0,
  py: 0,
  on: false,
  reach: 0,
  pa: 0,
  food: [],
});

/**
 * Where the amoeba sits on a `width` x `height` stage at time `t`; it drifts slowly.
 * @returns {{ R: number, cx: number, cy: number }}
 */
export function amoebaGeometry(width, height, t = 0) {
  const wide = width > WIDE_STAGE;
  const R = Math.min(
    Math.min(width, height) * (wide ? WIDE_SCALE : NARROW_SCALE),
    wide ? WIDE_MAX_RADIUS : NARROW_MAX_RADIUS,
  );
  return {
    R,
    cx: R * 0.42 + Math.sin(t * 0.00007) * R * 0.05 + Math.sin(t * 0.00019) * R * 0.015,
    cy: R * 0.5 + Math.cos(t * 0.00005) * R * 0.04,
  };
}

/** @param {Amoeba} amoeba */
export const amoebaContains = (amoeba, x, y) =>
  amoeba.R && Math.hypot(x - amoeba.cx, y - amoeba.cy) < amoeba.R * HIT_SCALE;

/**
 * Engulf food at (x, y), up to a few pieces at once.
 * @param {Amoeba} amoeba
 */
export function feedAmoeba(amoeba, x, y, now) {
  if (amoeba.food.length < MAX_FOOD) amoeba.food.push({ x, y, t0: now });
}

/** Trace the wobbling outline, bulging towards the pseudopod angle. */
function traceOutline(ctx, amoeba, cx, cy, radius, t, amplitude, seed) {
  ctx.beginPath();
  for (let i = 0; i <= OUTLINE_POINTS; i++) {
    const angle = (i / OUTLINE_POINTS) * Math.PI * 2;
    // angular distance from the pseudopod, 0..π
    const fromPod = Math.abs(
      ((((angle - amoeba.pa) % (Math.PI * 2)) + Math.PI * 3) % (Math.PI * 2)) - Math.PI,
    );
    const pod =
      amoeba.reach * PSEUDOPOD_SIZE * Math.pow(Math.max(0, Math.cos(fromPod)), PSEUDOPOD_SHARPNESS);
    const wobble =
      0.55 * Math.sin(angle * 3 + t * 0.00035 + seed) +
      0.35 * Math.sin(angle * 5 - t * 0.0005 + seed * 2) +
      0.6 * Math.max(0, Math.sin(angle * 2 - t * 0.00022 + seed)) ** 3;
    const scale = 1 + pod + amplitude * wobble;
    ctx.lineTo(cx + Math.cos(angle) * radius * scale, cy + Math.sin(angle) * radius * scale);
  }
  ctx.closePath();
}

/**
 * Move and draw the amoeba for this frame.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Amoeba} amoeba
 * @param {number} now
 * @param {{ width: number, height: number, reduce: boolean, colors: { blue: string, coral: string } }} options
 */
export function drawAmoeba(ctx, amoeba, now, { width, height, reduce, colors }) {
  const t = reduce ? 0 : now;
  const { R, cx, cy } = amoebaGeometry(width, height, t);
  amoeba.cx = cx;
  amoeba.cy = cy;
  amoeba.R = R;
  amoeba.reach = lerp(amoeba.reach, amoeba.on ? 1 : 0, reduce ? 1 : REACH_RATE);
  if (amoeba.on) {
    const target = Math.atan2(amoeba.py - cy, amoeba.px - cx);
    let turn = target - amoeba.pa;
    turn = Math.atan2(Math.sin(turn), Math.cos(turn));
    amoeba.pa += turn * (reduce ? 1 : TURN_RATE);
  }
  const sx = Math.cos(amoeba.pa) * amoeba.reach * R * BODY_SHIFT;
  const sy = Math.sin(amoeba.pa) * amoeba.reach * R * BODY_SHIFT;

  // membrane: soft fill, ectoplasm and endoplasm outlines
  ctx.globalAlpha = 0.035;
  ctx.fillStyle = colors.blue;
  traceOutline(ctx, amoeba, cx, cy, R, t, 0.12, amoeba.seed);
  ctx.fill();
  ctx.globalAlpha = 0.22;
  ctx.strokeStyle = colors.blue;
  ctx.lineWidth = 1.3;
  traceOutline(ctx, amoeba, cx, cy, R, t, 0.12, amoeba.seed);
  ctx.stroke();
  ctx.globalAlpha = 0.08;
  ctx.lineWidth = 1;
  traceOutline(ctx, amoeba, cx, cy, R * 0.9, t, 0.1, amoeba.seed + 0.4);
  ctx.stroke();

  amoeba.food = amoeba.food.filter((food) => now - food.t0 < FOOD_LIFE_MS);
  drawOrganelles(ctx, { cx, cy, R, sx, sy, t, now, reduce, food: amoeba.food, ...colors });
  ctx.globalAlpha = 1;
}
