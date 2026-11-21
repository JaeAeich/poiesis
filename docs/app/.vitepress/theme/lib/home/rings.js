// Task rings on the hero lattice. A ring is a task landing on a node: pending (dashed), running
// (electrons circling the hexagon), then done (blue). A ring you click ("strong") just runs.
import { clamp, ease, lerp } from "../core.js";
import { HEX_SIZE, hexVertex, nearestHex, traceHex } from "./hex.js";
import { fillCircle, strokeCircle } from "./shared.js";

const MAX_RINGS = 12;
const MAX_STRONG_RINGS = 3;
const STRONG_DURATION_MS = 6200;
const DURATION_MS = 5600;
const STRONG_SPEED = 0.45; // laps of the hexagon per second, roughly
const SPEED = 0.2;

// life phases, as fractions of the duration
const PENDING_END = 0.14;
const DONE_START = 0.8;
const DONE_FADE = 0.2;
const STRONG_FADE_IN = 0.06;
const STRONG_FADE_OUT = 0.94;

const ORBIT_RADIUS = HEX_SIZE * 0.52;
const ELECTRON_TRAIL = 6;
const TRAIL_SPACING = 0.07; // in hexagon edges

// throwing tasks from the wheel hub
const BUSY_MAX_RINGS = 9;
const IDLE_MAX_RINGS = 1;
const BUSY_MIN_INTERVAL_MS = 320;
const BUSY_INTERVAL_FACTOR = 2600; // interval = this / spin speed
const IDLE_INTERVAL_MS = 6000;
const THROW_REACH = 0.62; // of the smaller stage side
const THROW_MIN_DISTANCE = 0.22;
const FLIGHT_MS = 520;
const FLIER_TRAIL = 5;
const FLIER_ARC_HEIGHT = 28;

/**
 * @typedef {object} Ring
 * @property {number} x
 * @property {number} y
 * @property {boolean} strong clicked by the visitor
 * @property {number} speed electron speed; the sign is the direction
 * @property {number} t0 start time, ms
 * @property {number} dur lifetime, ms
 *
 * @typedef {{ x: number, y: number, t0: number, dur: number }} Flier a task in flight to its node
 *
 * @typedef {object} TaskRings
 * @property {Ring[]} rings
 * @property {Flier[]} fliers
 * @property {number} lastThrow
 */

/** @returns {TaskRings} */
export const createTaskRings = () => ({ rings: [], fliers: [], lastThrow: 0 });

/**
 * Add a ring unless the field is full or the node already has one. A new strong ring replaces
 * the oldest strong one once there are three.
 * @param {Ring[]} rings
 * @param {{ x: number, y: number, strong: boolean, delay?: number, speed?: number }} spec
 * @param {number} now
 */
export function addRing(rings, { x, y, strong, delay = 0, speed }, now) {
  if (rings.length >= MAX_RINGS || rings.some((ring) => ring.x === x && ring.y === y)) return;
  if (strong) {
    const strongRings = rings.filter((ring) => ring.strong);
    if (strongRings.length >= MAX_STRONG_RINGS) rings.splice(rings.indexOf(strongRings[0]), 1);
  }
  rings.push({
    x,
    y,
    strong,
    speed: speed || (strong ? STRONG_SPEED : SPEED),
    t0: now + delay,
    dur: strong ? STRONG_DURATION_MS : DURATION_MS,
  });
}

/**
 * Phase and opacity of a ring at `progress` (0..1 of its life).
 * @param {Ring} ring
 * @returns {{ phase: "pend" | "run" | "done", alpha: number }}
 */
export function ringPhase(ring, progress) {
  if (ring.strong) {
    const alpha =
      progress < STRONG_FADE_IN
        ? progress / STRONG_FADE_IN
        : 1 - (progress - STRONG_FADE_IN) / STRONG_FADE_OUT;
    return { phase: "run", alpha };
  }
  if (progress < PENDING_END) return { phase: "pend", alpha: progress / PENDING_END };
  if (progress < DONE_START) return { phase: "run", alpha: 1 };
  return { phase: "done", alpha: 1 - (progress - DONE_START) / DONE_FADE };
}

/**
 * @param {CanvasRenderingContext2D} ctx
 * @param {Ring} ring
 * @param {number} now
 * @param {{ blue: string, coral: string }} colors
 */
export function drawRing(ctx, ring, now, colors) {
  const progress = (now - ring.t0) / ring.dur;
  if (progress < 0) return;
  const { phase, alpha } = ringPhase(ring, progress);
  const { x, y, strong } = ring;

  if (phase === "pend") {
    ctx.globalAlpha = alpha * 0.75;
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = colors.coral;
    ctx.lineWidth = 1.2;
    traceHex(ctx, x, y);
    ctx.stroke();
    ctx.setLineDash([]);
    return;
  }
  if (phase === "done") {
    ctx.globalAlpha = alpha * 0.16;
    ctx.fillStyle = colors.blue;
    traceHex(ctx, x, y);
    ctx.fill();
    ctx.globalAlpha = alpha * 0.6;
    ctx.strokeStyle = colors.blue;
    ctx.lineWidth = 1.2;
    traceHex(ctx, x, y);
    ctx.stroke();
    return;
  }

  if (strong) {
    ctx.globalAlpha = alpha * 0.1;
    ctx.fillStyle = colors.coral;
    traceHex(ctx, x, y);
    ctx.fill();
  }
  ctx.globalAlpha = alpha * (strong ? 0.95 : 0.55);
  ctx.strokeStyle = colors.coral;
  ctx.lineWidth = strong ? 2 : 1.2;
  traceHex(ctx, x, y);
  ctx.stroke();
  ctx.globalAlpha = alpha * (strong ? 0.55 : 0.3);
  ctx.strokeStyle = colors.blue;
  ctx.lineWidth = 1;
  strokeCircle(ctx, x, y, ORBIT_RADIUS);
  drawElectrons(ctx, ring, alpha, (now - ring.t0) / 1000, colors.coral);
}

/** Electrons running round the hexagon's edges, each with a fading trail. */
function drawElectrons(ctx, ring, alpha, seconds, color) {
  const count = ring.strong ? 3 : 2;
  const direction = Math.sign(ring.speed) || 1;
  const radius = ring.strong ? 3 : 2.1;
  ctx.fillStyle = color;
  for (let electron = 0; electron < count; electron++) {
    for (let trail = 0; trail < ELECTRON_TRAIL; trail++) {
      // position along the perimeter, in edges (0..6)
      const along =
        (((seconds * ring.speed * 6 - direction * trail * TRAIL_SPACING + (electron * 6) / count) %
          6) +
          6) %
        6;
      const edge = Math.floor(along);
      const fraction = along - edge;
      const [x1, y1] = hexVertex(ring.x, ring.y, edge);
      const [x2, y2] = hexVertex(ring.x, ring.y, (edge + 1) % 6);
      ctx.globalAlpha = alpha * (1 - trail / ELECTRON_TRAIL) * (trail ? 0.5 : 1);
      fillCircle(ctx, lerp(x1, x2, fraction), lerp(y1, y2, fraction), radius * (1 - trail / 10));
    }
  }
}

/**
 * Turning the wheel throws tasks from the hub onto nodes, the way it turns; at rest only the odd one.
 * @param {TaskRings} field
 * @param {object} options
 * @param {number} options.now
 * @param {boolean} options.busy the wheel is spinning
 * @param {number} options.spin absolute spin speed
 * @param {number} options.velocity wheel velocity; its sign sets the electrons' direction
 * @param {{ x: number, y: number }} options.hub where tasks are thrown from
 * @param {number} options.stageSize smaller stage side, px
 * @param {(x: number, y: number) => boolean} options.isBlocked nodes tasks may not land on
 */
export function maybeThrowTask(field, { now, busy, spin, velocity, hub, stageSize, isBlocked }) {
  const interval = busy
    ? Math.max(BUSY_MIN_INTERVAL_MS, BUSY_INTERVAL_FACTOR / spin)
    : IDLE_INTERVAL_MS;
  const maxRings = busy ? BUSY_MAX_RINGS : IDLE_MAX_RINGS;
  if (now - field.lastThrow <= interval || field.rings.length >= maxRings) return;
  field.lastThrow = now;

  const angle = Math.random() * Math.PI * 2;
  const spread = busy ? Math.min(1, 0.45 + spin / 14) : 0.6;
  const distance = (THROW_MIN_DISTANCE + Math.random() * spread) * stageSize * THROW_REACH;
  const target = nearestHex(hub.x + Math.cos(angle) * distance, hub.y + Math.sin(angle) * distance);
  if (!target || isBlocked(target.x, target.y)) return;
  if (field.rings.some((ring) => ring.x === target.x && ring.y === target.y)) return;

  const flight = busy ? FLIGHT_MS : 0;
  if (busy) field.fliers.push({ x: target.x, y: target.y, t0: now, dur: flight });
  const speed = (busy ? 0.22 + Math.min(spin, 20) * 0.012 : SPEED) * (velocity < 0 ? -1 : 1);
  addRing(field.rings, { x: target.x, y: target.y, strong: false, delay: flight, speed }, now);
}

/**
 * Tasks in flight from the hub, arcing up, with a short trail.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Flier[]} fliers
 * @param {{ x: number, y: number }} hub
 * @param {number} now
 * @param {string} color
 */
export function drawFliers(ctx, fliers, hub, now, color) {
  for (const flier of fliers) {
    const progress = ease(clamp((now - flier.t0) / flier.dur));
    for (let trail = 0; trail < FLIER_TRAIL; trail++) {
      const along = clamp(progress - trail * 0.05);
      const x = lerp(hub.x, flier.x, along);
      const y = lerp(hub.y, flier.y, along) - Math.sin(Math.PI * along) * FLIER_ARC_HEIGHT;
      ctx.globalAlpha = (1 - trail / FLIER_TRAIL) * 0.9;
      ctx.fillStyle = color;
      fillCircle(ctx, x, y, 3.4 * (1 - trail / 7));
    }
  }
}
