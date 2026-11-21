// Physics for the engine logos: each floats near its slot on a spring, bounces off the walls,
// the floor, the engine table and the other logos.
import { clamp, lerp } from "../core.js";
import { FRAME_MS } from "./shared.js";

const RESTITUTION = 0.7; // velocity kept by a bounce
const SPRING = 0.018; // pull towards the slot, per frame
const DAMPING = 0.86; // velocity kept per frame
const MAX_SPEED = 40; // px per frame
const BOB_X = 4; // px of idle drift around the slot
const BOB_Y = 6;
const BOB_RATE_X = 0.6; // radians per second
const BOB_RATE_Y = 0.5;
const LOGO_GAP = 4; // px kept between logos
const THROW_WINDOW_MS = 120; // pointer history used for the throw velocity
const MIN_THROW_DT = 16;
// desktop slots: two staggered columns either side of the table
const SLOTS_MIN_TOP = 90;
const SLOTS_BOTTOM_MARGIN = 110;
const SLOTS_TABLE_INSET = 30;
const MAX_ZIGZAG = 46;
const ZIGZAG_SCALE = 0.16; // of the column width
// phone slots: two staggered rows
const PHONE_ROWS_Y = [0.3, 0.7];
const PHONE_ROW_SHIFT = [-0.15, 0.25]; // of the gap

/**
 * @typedef {{ x: number, y: number }} Slot
 * @typedef {{ x: number, y: number, w: number, h: number }} Rect
 *
 * @typedef {object} Body
 * @property {HTMLElement} el
 * @property {number} x centre, px
 * @property {number} y
 * @property {number} vx px per frame
 * @property {number} vy
 * @property {boolean} held being dragged
 * @property {number} ph bob phase
 * @property {number} r radius
 * @property {number} m mass
 * @property {number} ax slot (anchor) position
 * @property {number} ay
 *
 * @typedef {object} World
 * @property {number} width
 * @property {number} height
 * @property {number} floor px reserved at the bottom
 * @property {Rect} table obstacle the logos bounce off
 * @property {number} clock seconds, drives the bob
 */

/**
 * Phone layout: two staggered rows across the width.
 * @returns {Slot[]}
 */
export function phoneSlots(count, width, height) {
  const perRow = Math.ceil(count / 2);
  const slots = [];
  for (let i = 0; i < count; i++) {
    const row = i < perRow ? 0 : 1;
    const column = row ? i - perRow : i;
    const inRow = row ? count - perRow : perRow;
    const gap = width / inRow;
    slots.push({
      x: gap * (column + 0.5) + gap * PHONE_ROW_SHIFT[row],
      y: height * PHONE_ROWS_Y[row],
    });
  }
  return slots;
}

/**
 * Desktop layout: two zig-zag columns either side of the table.
 * @param {number} count
 * @param {number} width
 * @param {number} height
 * @param {Rect} table
 * @returns {Slot[]}
 */
export function tableSlots(count, width, height, table) {
  const left = table.x;
  const right = width - (table.x + table.w);
  const columns = [
    { cx: left / 2, w: left },
    { cx: table.x + table.w + right / 2, w: right },
  ];
  const perColumn = [Math.ceil(count / 2), Math.floor(count / 2)];
  const top = Math.max(SLOTS_MIN_TOP, table.y + SLOTS_TABLE_INSET);
  const bottom = Math.min(height - SLOTS_BOTTOM_MARGIN, table.y + table.h - SLOTS_TABLE_INSET);
  const slots = [];
  columns.forEach((column, side) => {
    const n = perColumn[side];
    for (let j = 0; j < n; j++) {
      const t = n === 1 ? 0.5 : j / (n - 1);
      const zigzag =
        (j % 2 ? 1 : -1) * Math.min(MAX_ZIGZAG, column.w * ZIGZAG_SCALE) * (side ? -1 : 1);
      slots.push({ x: column.cx + zigzag, y: lerp(top, bottom, t) });
    }
  });
  return slots;
}

/**
 * Advance every free body by `dt` ms, then resolve collisions between bodies.
 * @param {Body[]} bodies
 * @param {number} dt
 * @param {World} world
 */
export function stepBodies(bodies, dt, world) {
  const frames = dt / FRAME_MS;
  world.clock += dt / 1000;
  for (const body of bodies) {
    if (!body.held) moveBody(body, frames, world);
  }
  for (let i = 0; i < bodies.length; i++) {
    for (let j = i + 1; j < bodies.length; j++) collide(bodies[i], bodies[j]);
  }
}

function moveBody(body, frames, world) {
  const { width, height, floor, table, clock } = world;
  const targetX = body.ax + Math.sin(clock * BOB_RATE_X + body.ph) * BOB_X;
  const targetY = body.ay + Math.cos(clock * BOB_RATE_Y + body.ph) * BOB_Y;
  body.vx += (targetX - body.x) * SPRING * frames;
  body.vy += (targetY - body.y) * SPRING * frames;
  const damping = Math.pow(DAMPING, frames);
  body.vx *= damping;
  body.vy *= damping;
  const speed = Math.hypot(body.vx, body.vy);
  if (speed > MAX_SPEED) {
    body.vx *= MAX_SPEED / speed;
    body.vy *= MAX_SPEED / speed;
  }
  body.x += body.vx * frames;
  body.y += body.vy * frames;

  // walls and floor
  if (body.x < body.r) {
    body.x = body.r;
    body.vx = Math.abs(body.vx) * RESTITUTION;
  }
  if (body.x > width - body.r) {
    body.x = width - body.r;
    body.vx = -Math.abs(body.vx) * RESTITUTION;
  }
  if (body.y < body.r) {
    body.y = body.r;
    body.vy = Math.abs(body.vy) * RESTITUTION;
  }
  if (body.y > height - floor - body.r) {
    body.y = height - floor - body.r;
    body.vy = -Math.abs(body.vy) * RESTITUTION;
  }

  // the table: push out along the normal from its nearest point and reflect
  const nearestX = clamp(body.x, table.x, table.x + table.w);
  const nearestY = clamp(body.y, table.y, table.y + table.h);
  let nx = body.x - nearestX;
  let ny = body.y - nearestY;
  const distance = Math.hypot(nx, ny);
  if (distance < body.r && distance > 0) {
    nx /= distance;
    ny /= distance;
    body.x = nearestX + nx * body.r;
    body.y = nearestY + ny * body.r;
    const normalSpeed = body.vx * nx + body.vy * ny;
    if (normalSpeed < 0) {
      body.vx -= (1 + RESTITUTION) * normalSpeed * nx;
      body.vy -= (1 + RESTITUTION) * normalSpeed * ny;
    }
  }
}

/** Separate two overlapping bodies by inverse mass and exchange an impulse; held ones don't move. */
function collide(a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const distance = Math.hypot(dx, dy);
  const minDistance = a.r + b.r + LOGO_GAP;
  if (!(distance > 0 && distance < minDistance)) return;
  const nx = dx / distance;
  const ny = dy / distance;
  const inverseA = a.held ? 0 : 1 / a.m;
  const inverseB = b.held ? 0 : 1 / b.m;
  const inverseSum = inverseA + inverseB;
  if (!inverseSum) return;
  const overlap = minDistance - distance;
  a.x -= (nx * overlap * inverseA) / inverseSum;
  a.y -= (ny * overlap * inverseA) / inverseSum;
  b.x += (nx * overlap * inverseB) / inverseSum;
  b.y += (ny * overlap * inverseB) / inverseSum;
  const relativeSpeed = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny;
  if (relativeSpeed < 0) {
    const impulse = (-(1 + RESTITUTION) * relativeSpeed) / inverseSum;
    a.vx -= impulse * inverseA * nx;
    a.vy -= impulse * inverseA * ny;
    b.vx += impulse * inverseB * nx;
    b.vy += impulse * inverseB * ny;
  }
}

/**
 * Throw velocity (px per frame) from recent pointer samples [time, clientX, clientY].
 * @param {[number, number, number][]} history
 * @param {number} now
 * @returns {{ vx: number, vy: number }}
 */
export function throwVelocity(history, now) {
  const recent = history.filter((sample) => now - sample[0] < THROW_WINDOW_MS);
  const first = recent[0] || [now, 0, 0];
  const last = recent[recent.length - 1] || first;
  const dt = Math.max(MIN_THROW_DT, last[0] - first[0]);
  return {
    vx: ((last[1] - first[1]) / dt) * FRAME_MS,
    vy: ((last[2] - first[2]) / dt) * FRAME_MS,
  };
}
