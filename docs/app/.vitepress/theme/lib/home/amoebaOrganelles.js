// The amoeba's insides. Positions are fractions of the radius R from the centre, shifted by
// (sx, sy) towards the pseudopod; t drives the slow drift (0 with reduced motion).
import { clamp, ease, lerp } from "../core.js";
import { FULL_CIRCLE } from "./shared.js";

const GRANULES = 34;
const ER_SHEETS = 3;
const GOLGI_CISTERNAE = 4;
const GOLGI_VESICLES = 3;
const MITOCHONDRIA = [
  [0.16, -0.08],
  [-0.27, 0.6],
  [0.13, 0.72],
  [0.2, 0.4],
];
const FOOD_VACUOLES = [
  [-0.13, 0.86],
  [-0.3, 0.32],
];
const FEEDER_CANALS = 6;
const CONTRACTILE_RATE = 0.0012; // radians per ms of the fill/empty cycle
const CONTRACTILE_STILL_FILL = 0.6; // with reduced motion
const CHROMATIN_DOTS = 9;
/** Engulfed food is digested after this long. */
export const FOOD_LIFE_MS = 4200;
const FOOD_TRAVEL = 0.7; // food reaches the nucleus at this fraction of its life

/**
 * @typedef {object} Cell
 * @property {number} cx
 * @property {number} cy
 * @property {number} R
 * @property {number} sx
 * @property {number} sy
 * @property {number} t drift time
 * @property {number} now real time, for food
 * @property {boolean} reduce
 * @property {import("./amoeba.js").Food[]} food
 * @property {string} blue
 * @property {string} coral
 */

function dot(ctx, x, y, radius, color, alpha) {
  ctx.globalAlpha = alpha;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, FULL_CIRCLE);
  ctx.fill();
}

function circle(ctx, x, y, radius, color, alpha, lineWidth = 1) {
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, FULL_CIRCLE);
  ctx.stroke();
}

/**
 * @param {CanvasRenderingContext2D} ctx
 * @param {Cell} cell
 */
export function drawOrganelles(ctx, cell) {
  const { cx, cy, R, sx, sy, t } = cell;
  drawGranules(ctx, cell);
  // the nucleus is placed first; other parts sit around it
  const nucleus = {
    x: cx + sx * 0.5 - R * 0.04 + Math.cos(t * 0.0001) * R * 0.02,
    y: cy + sy * 0.5 + R * 0.26 + Math.sin(t * 0.00013) * R * 0.02,
    r: R * 0.13,
  };
  drawReticulum(ctx, nucleus, t, cell.blue);
  drawGolgi(ctx, cell);
  drawMitochondria(ctx, cell);
  drawFoodVacuoles(ctx, cell);
  drawContractileVacuole(ctx, cell);
  drawNucleus(ctx, nucleus, cell);
  drawEngulfedFood(ctx, nucleus, cell);
}

/** Fine granules streaming with the cytoplasm. */
function drawGranules(ctx, { cx, cy, R, sx, sy, t, blue }) {
  for (let i = 0; i < GRANULES; i++) {
    const u = (i * 0.618) % 1;
    const v = (i * 0.382 + 0.13) % 1;
    const gx = -0.42 + 0.68 * u + Math.sin(t * 0.00006 + i) * 0.02;
    const gy = -0.3 + 1.22 * v + Math.cos(t * 0.00005 + i) * 0.02;
    if (Math.hypot(gx, gy) < 0.95) {
      dot(ctx, cx + sx * 1.3 + gx * R, cy + sy * 1.3 + gy * R, 0.6 + (i % 3) * 0.35, blue, 0.15);
    }
  }
}

/** Endoplasmic reticulum: wavy sheets around the nucleus. */
function drawReticulum(ctx, nucleus, t, blue) {
  ctx.lineWidth = 0.9;
  for (let k = 0; k < ER_SHEETS; k++) {
    const radius = nucleus.r * (1.35 + k * 0.28);
    ctx.globalAlpha = 0.13 - k * 0.025;
    ctx.strokeStyle = blue;
    ctx.beginPath();
    for (let a = -1.1 + k * 0.25; a < 2.2 + k * 0.25; a += 0.06) {
      const wave = radius * (1 + 0.06 * Math.sin(a * 9 + t * 0.0006 + k));
      ctx.lineTo(nucleus.x + Math.cos(a) * wave, nucleus.y + Math.sin(a) * wave);
    }
    ctx.stroke();
  }
}

/** Golgi: a stack of short curved cisternae with a few vesicles. */
function drawGolgi(ctx, { cx, cy, R, blue }) {
  ctx.save();
  ctx.translate(cx - R * 0.2, cy - R * 0.16);
  ctx.rotate(-0.3);
  ctx.strokeStyle = blue;
  for (let k = 0; k < GOLGI_CISTERNAE; k++) {
    ctx.globalAlpha = 0.24 - k * 0.03;
    ctx.lineWidth = 1.4 - k * 0.15;
    ctx.beginPath();
    ctx.arc(0, R * 0.16, R * (0.1 + k * 0.022), -2.2, -0.95);
    ctx.stroke();
  }
  for (let k = 0; k < GOLGI_VESICLES; k++) {
    dot(ctx, R * (0.11 + k * 0.03), R * (0.03 - k * 0.02), 1.4, blue, 0.2);
  }
  ctx.restore();
}

/** Mitochondria with zig-zag cristae. */
function drawMitochondria(ctx, { cx, cy, R, sx, sy, t, blue }) {
  MITOCHONDRIA.forEach(([fx, fy], i) => {
    const x = cx + sx + R * fx + Math.sin(t * 0.00008 + i) * R * 0.02;
    const y = cy + sy + R * fy + Math.cos(t * 0.00007 + i) * R * 0.02;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(i * 1.7 + t * 0.00015);
    ctx.globalAlpha = 0.26;
    ctx.strokeStyle = blue;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.ellipse(0, 0, R * 0.07, R * 0.032, 0, 0, FULL_CIRCLE);
    ctx.stroke();
    ctx.globalAlpha = 0.2;
    ctx.beginPath();
    for (let j = -3; j <= 3; j++) ctx.lineTo(j * R * 0.017, (j % 2 ? 1 : -1) * R * 0.018);
    ctx.stroke();
    ctx.restore();
  });
}

/** Food vacuoles with digesting contents. */
function drawFoodVacuoles(ctx, { cx, cy, R, sx, sy, t, blue, coral }) {
  FOOD_VACUOLES.forEach(([fx, fy], i) => {
    const x = cx + sx + R * fx + Math.sin(t * 0.00006 + i) * R * 0.02;
    const y = cy + sy + R * fy + Math.cos(t * 0.00005 + i) * R * 0.02;
    const radius = R * (0.06 + 0.015 * i);
    circle(ctx, x, y, radius, blue, 0.2);
    dot(ctx, x + radius * 0.2, y - radius * 0.15, radius * 0.38, coral, 0.24);
    dot(ctx, x - radius * 0.3, y + radius * 0.25, radius * 0.16, coral, 0.18);
  });
}

/** Contractile vacuole with feeder canals: fills, then empties. */
function drawContractileVacuole(ctx, { cx, cy, R, sx, sy, t, reduce, blue }) {
  const fill = reduce ? CONTRACTILE_STILL_FILL : (Math.sin(t * CONTRACTILE_RATE) + 1) / 2;
  const x = cx + sx - R * 0.3;
  const y = cy + sy + R * 0.06;
  const radius = R * (0.035 + 0.06 * fill);
  ctx.strokeStyle = blue;
  ctx.lineWidth = 0.9;
  for (let k = 0; k < FEEDER_CANALS; k++) {
    const a = (k * Math.PI) / 3 + 0.3;
    ctx.globalAlpha = 0.16 * (1 - fill * 0.6);
    ctx.beginPath();
    ctx.moveTo(x + Math.cos(a) * radius * 1.3, y + Math.sin(a) * radius * 1.3);
    ctx.lineTo(x + Math.cos(a) * R * 0.17, y + Math.sin(a) * R * 0.17);
    ctx.stroke();
  }
  dot(ctx, x, y, radius, blue, 0.1 + 0.12 * fill);
  circle(ctx, x, y, radius, blue, 0.26);
}

/** Nucleus: envelope with pores, nucleolus, chromatin. */
function drawNucleus(ctx, nucleus, { R, t, coral }) {
  const { x, y, r } = nucleus;
  dot(ctx, x, y, r, coral, 0.07);
  ctx.globalAlpha = 0.3;
  ctx.strokeStyle = coral;
  ctx.lineWidth = 1.2;
  ctx.setLineDash([R * 0.03, R * 0.01]);
  ctx.beginPath();
  ctx.arc(x, y, r, 0, FULL_CIRCLE);
  ctx.stroke();
  ctx.setLineDash([]);
  dot(ctx, x + r * 0.25, y - r * 0.2, r * 0.3, coral, 0.36);
  for (let k = 0; k < CHROMATIN_DOTS; k++) {
    const a = k * 2.2 + t * 0.0002;
    const distance = r * (0.25 + (0.5 * ((k * 37) % 10)) / 10);
    dot(ctx, x + Math.cos(a) * distance, y + Math.sin(a) * distance, 0.9, coral, 0.3);
  }
}

/** Engulfed food: forms where you clicked, drifts to the nucleus, is digested. */
function drawEngulfedFood(ctx, nucleus, { R, now, food, blue, coral }) {
  for (const piece of food) {
    const life = clamp((now - piece.t0) / FOOD_LIFE_MS);
    const travel = ease(clamp(life / FOOD_TRAVEL));
    const x = lerp(piece.x, nucleus.x - nucleus.r * 1.2, travel);
    const y = lerp(piece.y, nucleus.y + nucleus.r * 0.7, travel);
    const radius =
      R * 0.065 * (life < 0.08 ? life / 0.08 : 1) * (1 - clamp((life - 0.6) / 0.4) * 0.85);
    circle(ctx, x, y, radius, blue, 0.5 * (1 - clamp((life - 0.75) / 0.25)));
    dot(ctx, x, y, radius * 0.45, coral, 0.55 * (1 - clamp((life - 0.5) / 0.5)));
  }
}
