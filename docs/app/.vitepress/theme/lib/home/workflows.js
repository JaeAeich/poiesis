// Workflows on the hero lattice: several shapes, some steps in parallel, some in sequence.
// A step waits for its inputs, runs (coral), then is done (blue). Labels never move.
import { clamp, ease, lerp } from "../core.js";
import { HEX_WIDTH, ROW_HEIGHT, hexCenter, traceHex } from "./hex.js";

/**
 * @typedef {object} FlowShape
 * @property {string} name
 * @property {[number, number, string][]} nodes [row offset, column offset, label]
 * @property {number[][]} deps indices of each node's inputs
 */

/** @type {FlowShape[]} */
export const FLOW_SHAPES = [
  {
    name: "chain",
    nodes: [
      [0, 0, "qc"],
      [0, 1, "trim"],
      [0, 2, "map"],
      [0, 3, "call"],
    ],
    deps: [[], [0], [1], [2]],
  },
  {
    name: "fan",
    nodes: [
      [1, 0, "split"],
      [0, 1, "map"],
      [1, 1, "map"],
      [2, 1, "map"],
      [1, 2, "merge"],
    ],
    deps: [[], [0], [0], [0], [1, 2, 3]],
  },
  {
    name: "diamond",
    nodes: [
      [1, 0, "qc"],
      [0, 1, "trim"],
      [2, 1, "kmer"],
      [1, 2, "asm"],
    ],
    deps: [[], [0], [0], [1, 2]],
  },
  {
    name: "pair",
    nodes: [
      [0, 0, "idx"],
      [0, 1, "map"],
      [0, 2, "count"],
      [2, 0, "qc"],
      [2, 1, "trim"],
      [2, 2, "sort"],
    ],
    deps: [[], [0], [1], [], [3], [4]],
  },
  {
    name: "scatter",
    nodes: [
      [0, 0, "split"],
      [1, 0, "call"],
      [1, 1, "call"],
      [0, 1, "call"],
      [2, 1, "gather"],
    ],
    deps: [[], [0], [0], [0], [1, 2, 3]],
  },
];

const EDGE_MARGIN_X = 34;
const EDGE_MARGIN_TOP = 30;
const HELIX_CLEARANCE = 52; // keep workflows this far above the helix
const LINK_SAMPLE_STEP = 0.25; // links are checked for obstacles at these fractions

const FADE_IN_MS = 700;
const FIRST_STEP_STAGGER_MS = 450;
const STEP_MIN_MS = 2200;
const STEP_JITTER_MS = 1400;
const LINGER_MS = 2200; // a finished workflow stays this long, then fades out
const FADE_OUT_MS = 1600;
const PULSE_PERIOD = 260; // ms per radian of the running pulse
const LINK_FLOW_RATE = 60; // ms per px of dash offset on a live link
const LABEL_FONT = "500 8.5px 'JetBrains Mono', monospace";
const LABEL_OFFSET_Y = 3.5;

/**
 * @typedef {{ r: number, c: number, x: number, y: number }} SlotNode
 * @typedef {{ T: FlowShape, r: number, c: number, nodes: SlotNode[] }} FlowSlot a place a shape fits
 *
 * @typedef {object} FlowStep
 * @property {number} r
 * @property {number} c
 * @property {number} x
 * @property {number} y
 * @property {string} label
 * @property {number[]} dep
 * @property {number} dur run time, ms
 * @property {number} shown time it appeared, or 0
 * @property {number} start time it started running, or 0
 * @property {"wait" | "run" | "done"} state
 *
 * @typedef {{ name: string, t0: number, end: number, gone?: boolean, nodes: FlowStep[] }} Flow
 */

/**
 * Every place each workflow shape fits above the helix without touching an obstacle.
 * @param {{ width: number, bottom: number, isBlocked: (x: number, y: number) => boolean }} area
 *   `bottom` is the helix's y; workflows stay clear above it
 * @returns {FlowSlot[]}
 */
export function findFlowSlots({ width, bottom, isBlocked }) {
  const slots = [];
  const rows = Math.ceil(bottom / ROW_HEIGHT);
  const cols = Math.ceil(width / HEX_WIDTH) + 1;
  const inBounds = (node) =>
    node.x > EDGE_MARGIN_X &&
    node.x < width - EDGE_MARGIN_X &&
    node.y > EDGE_MARGIN_TOP &&
    node.y < bottom - HELIX_CLEARANCE &&
    !isBlocked(node.x, node.y);
  const linkClear = (from, to) => {
    for (let u = LINK_SAMPLE_STEP; u < 1; u += LINK_SAMPLE_STEP) {
      if (isBlocked(lerp(from.x, to.x, u), lerp(from.y, to.y, u))) return false;
    }
    return true;
  };

  for (const shape of FLOW_SHAPES) {
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const nodes = shape.nodes.map(([dr, dc]) => {
          // odd row offsets shift right on odd base rows, so the shape keeps its form
          const row = r + dr;
          const col = c + dc + (dr % 2 && r % 2 ? 1 : 0);
          const [x, y] = hexCenter(row, col);
          return { r: row, c: col, x, y };
        });
        const fits =
          nodes.every(inBounds) &&
          shape.deps.every((inputs, k) => inputs.every((d) => linkClear(nodes[d], nodes[k])));
        if (fits) slots.push({ T: shape, r, c, nodes });
      }
    }
  }
  return slots;
}

/**
 * Start a workflow in a free slot, preferring a shape not already on screen.
 * @param {Flow[]} flows
 * @param {FlowSlot[]} slots
 * @param {number} now
 * @returns {boolean} whether one started
 */
export function spawnFlow(flows, slots, now) {
  // keep a ring of empty cells around running workflows
  const taken = new Set();
  for (const flow of flows) {
    for (const node of flow.nodes) {
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) taken.add(node.r + dr + ":" + (node.c + dc));
      }
    }
  }
  const liveShapes = new Set(flows.map((flow) => flow.name));
  let pool = slots.filter((slot) => !slot.nodes.some((node) => taken.has(node.r + ":" + node.c)));
  const fresh = pool.filter((slot) => !liveShapes.has(slot.T.name));
  if (fresh.length) pool = fresh;
  if (!pool.length) return false;

  const slot = pool[Math.floor(Math.random() * pool.length)];
  flows.push({
    name: slot.T.name,
    t0: now,
    end: 0,
    nodes: slot.nodes.map((node, i) => ({
      ...node,
      label: slot.T.nodes[i][2],
      dep: slot.T.deps[i],
      dur: STEP_MIN_MS + Math.random() * STEP_JITTER_MS,
      shown: 0,
      start: 0,
      state: "wait",
    })),
  });
  return true;
}

/**
 * Advance a workflow's steps to `now`.
 * @param {Flow} flow
 * @param {number} now
 * @returns {number} the workflow's opacity (0 once it has faded out)
 */
export function advanceFlow(flow, now) {
  flow.nodes.forEach((node, i) => {
    // a step appears once its inputs are running; the first steps appear one after another
    const inputsStarted = node.dep.every((d) => flow.nodes[d].state !== "wait");
    if (
      !node.shown &&
      (node.dep.length ? inputsStarted : now - flow.t0 > i * FIRST_STEP_STAGGER_MS)
    ) {
      node.shown = now;
    }
    const inputsDone = node.dep.every((d) => flow.nodes[d].state === "done");
    if (node.state === "wait" && node.shown && now - node.shown > FADE_IN_MS && inputsDone) {
      node.state = "run";
      node.start = now;
    }
    if (node.state === "run" && now - node.start > node.dur) node.state = "done";
  });
  if (!flow.end && flow.nodes.every((node) => node.state === "done")) flow.end = now;
  return flow.end ? 1 - clamp((now - flow.end - LINGER_MS) / FADE_OUT_MS) : 1;
}

/**
 * Advance and draw every workflow; returns the ones still on screen.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Flow[]} flows
 * @param {number} now
 * @param {{ coral: string, blue: string, muted: string, bg: string }} colors
 * @returns {Flow[]}
 */
export function drawFlows(ctx, flows, now, colors) {
  for (const flow of flows) {
    const opacity = advanceFlow(flow, now);
    if (flow.end && opacity <= 0) {
      flow.gone = true;
      continue;
    }
    drawLinks(ctx, flow, now, opacity, colors.coral);
    ctx.font = LABEL_FONT;
    ctx.textAlign = "center";
    for (const node of flow.nodes) {
      if (node.shown) drawStep(ctx, node, now, opacity, colors);
    }
    ctx.textAlign = "start";
  }
  ctx.globalAlpha = 1;
  return flows.filter((flow) => !flow.gone);
}

/** Links draw out from the upstream step when the downstream one appears. */
function drawLinks(ctx, flow, now, opacity, color) {
  for (const node of flow.nodes) {
    if (!node.shown) continue;
    const grown = ease(clamp((now - node.shown) / FADE_IN_MS));
    for (const d of node.dep) {
      const input = flow.nodes[d];
      const live = input.state === "done";
      ctx.globalAlpha = opacity * (live ? 0.55 : 0.25);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.2;
      ctx.setLineDash([3, 4]);
      ctx.lineDashOffset = live ? -now / LINK_FLOW_RATE : 0;
      ctx.beginPath();
      ctx.moveTo(input.x, input.y);
      ctx.lineTo(lerp(input.x, node.x, grown), lerp(input.y, node.y, grown));
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
}

function drawStep(ctx, node, now, opacity, colors) {
  const alpha = opacity * ease(clamp((now - node.shown) / FADE_IN_MS));
  const waiting = node.state === "wait";
  const running = node.state === "run";
  const done = node.state === "done";
  const pulse = running ? 0.5 + 0.5 * Math.sin((now - node.start) / PULSE_PERIOD) : 0;

  // knock the lattice out behind the step
  ctx.globalAlpha = alpha * 0.92;
  ctx.fillStyle = colors.bg;
  traceHex(ctx, node.x, node.y);
  ctx.fill();
  if (running || done) {
    ctx.globalAlpha = alpha * (running ? 0.1 + 0.1 * pulse : 0.15);
    ctx.fillStyle = running ? colors.coral : colors.blue;
    traceHex(ctx, node.x, node.y);
    ctx.fill();
  }
  ctx.globalAlpha = alpha * (waiting ? 0.45 : 0.85);
  ctx.strokeStyle = done ? colors.blue : colors.coral;
  ctx.lineWidth = running ? 1.5 : 1.2;
  if (waiting) ctx.setLineDash([3, 3]);
  traceHex(ctx, node.x, node.y);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.globalAlpha = alpha * (waiting ? 0.45 : 0.8);
  ctx.fillStyle = done ? colors.blue : running ? colors.coral : colors.muted;
  ctx.fillText(node.label, node.x, node.y + LABEL_OFFSET_Y);
}
