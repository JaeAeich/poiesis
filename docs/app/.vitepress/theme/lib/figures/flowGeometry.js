// Geometry of a flow diagram: node boxes, the edges between them, and where the travelling
// label ("puck") sits for a hop.
import { clamp, ease, lerp } from "../core.js";
import { captionLength } from "./caption.js";

/** Specs are authored on a canvas this wide; wide hosts stretch it to WIDE_WIDTH. */
const DESIGN_WIDTH = 420;
const WIDE_WIDTH = 600;
const DEFAULT_HEIGHT = 250;
const NODE_WIDTH = 118;
const NODE_HEIGHT = 44;
/** Stands in for "no limit" when an edge is parallel to a box side. */
const UNBOUNDED = 1e9;
/** A horizontal hop lifts its puck this far off the line, above it unless too near the top. */
const PUCK_LIFT = 34;
const PUCK_TOP_MARGIN = 14;
/** Puck width: per character of the label, plus padding, never under the minimum. */
const PUCK_CHAR_WIDTH = 6.7;
const PUCK_PADDING = 18;
const PUCK_MIN_WIDTH = 44;
/** Each hop's caption stays up at least this long, longer for longer captions, ms. */
const HOLD_MIN_MS = 700;
const HOLD_BASE_MS = 1200;
const HOLD_PER_CHAR_MS = 40;

/**
 * @typedef {object} FlowNode
 * @property {number} x left, on the design canvas
 * @property {number} y top
 * @property {number} [w] width, default NODE_WIDTH
 * @property {string} label
 * @property {string} [sub] second line
 *
 * @typedef {object} FlowHop
 * @property {string} f node the puck leaves
 * @property {string} t node it reaches
 * @property {string} label puck text
 * @property {string} cap caption, may mark identifiers with <code>
 * @property {"ok" | "bad"} [tone]
 *
 * @typedef {object} FlowSpec
 * @property {string} [title] accessible name
 * @property {number} [h] canvas height
 * @property {Record<string, FlowNode>} nodes
 * @property {[string, string][]} edges
 * @property {FlowHop[]} hops
 *
 * @typedef {{ x: number, y: number, w: number, h: number }} Box
 * @typedef {[number, number]} Point
 */

/**
 * Lay a spec out for a host: canvas size, node boxes, and edges clipped to the box borders.
 * @param {FlowSpec} spec
 * @param {boolean} wide
 */
export function layoutFlow(spec, wide) {
  const width = wide ? WIDE_WIDTH : DESIGN_WIDTH;
  const scale = width / DESIGN_WIDTH;
  /** @type {Record<string, Box>} */
  const boxes = {};
  for (const [id, node] of Object.entries(spec.nodes)) {
    const nodeWidth = node.w || NODE_WIDTH;
    // spread the columns, keep the boxes their authored width
    boxes[id] = {
      x: node.x * scale + (nodeWidth * (scale - 1)) / 2,
      y: node.y,
      w: nodeWidth,
      h: NODE_HEIGHT,
    };
  }
  const edges = spec.edges.map(([from, to]) => ({
    from,
    to,
    start: clipToBox(boxes[from], boxes[to]),
    end: clipToBox(boxes[to], boxes[from]),
  }));
  return { width, height: spec.h || DEFAULT_HEIGHT, boxes, edges };
}

/** @param {Box} box @returns {Point} */
const boxCenter = (box) => [box.x + box.w / 2, box.y + box.h / 2];

/**
 * Where the line from `from`'s centre towards `to`'s centre leaves `from`'s box.
 * @param {Box} from
 * @param {Box} to
 * @returns {Point}
 */
export function clipToBox(from, to) {
  const [x1, y1] = boxCenter(from);
  const [x2, y2] = boxCenter(to);
  const dx = x2 - x1;
  const dy = y2 - y1;
  const t = Math.min(
    dx ? Math.abs(from.w / 2 / dx) : UNBOUNDED,
    dy ? Math.abs(from.h / 2 / dy) : UNBOUNDED,
  );
  return [x1 + dx * t, y1 + dy * t];
}

/**
 * The puck's position `progress` (0..1) of the way along a hop.
 * @param {Record<string, Box>} boxes
 * @param {FlowHop} hop
 * @param {number} progress
 * @returns {Point}
 */
export function puckPosition(boxes, hop, progress) {
  const start = clipToBox(boxes[hop.f], boxes[hop.t]);
  const end = clipToBox(boxes[hop.t], boxes[hop.f]);
  const t = ease(clamp(progress));
  const y = lerp(start[1], end[1], t);
  const horizontal = Math.abs(end[0] - start[0]) > Math.abs(end[1] - start[1]);
  const lift = horizontal ? (y - PUCK_LIFT < PUCK_TOP_MARGIN ? PUCK_LIFT : -PUCK_LIFT) : 0;
  return [lerp(start[0], end[0], t), y + lift];
}

/** @param {string} label */
export const puckWidth = (label) =>
  Math.max(PUCK_MIN_WIDTH, label.length * PUCK_CHAR_WIDTH + PUCK_PADDING);

/**
 * How long a hop's caption stays up after the puck arrives, ms.
 * @param {FlowHop} hop
 */
export const hopHoldMs = (hop) =>
  Math.max(HOLD_MIN_MS, HOLD_BASE_MS + HOLD_PER_CHAR_MS * captionLength(hop.cap));

/**
 * Whether an edge joins the two nodes of a hop, in either direction.
 * @param {{ from: string, to: string }} edge
 * @param {FlowHop} hop
 */
export const edgeOnHop = (edge, hop) =>
  (edge.from === hop.f && edge.to === hop.t) || (edge.from === hop.t && edge.to === hop.f);
