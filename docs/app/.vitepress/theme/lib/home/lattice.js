// The hero's hexagon lattice, drawn once to an offscreen layer and faded out from the wheel.
import { createLayer } from "./shared.js";
import { HEX_SIZE, HEX_WIDTH, ROW_HEIGHT, hexCenter, traceHex } from "./hex.js";

const LINE_ALPHA = 0.65;
const FADE_INNER_RADIUS = 30;
const FADE_OUTER_SCALE = 0.6; // of the larger viewport side
const FADE_STOPS = [
  [0, "rgba(0,0,0,1)"],
  [0.5, "rgba(0,0,0,.4)"],
  [1, "rgba(0,0,0,0)"],
];

/**
 * Draw the lattice for a `width` x `height` stage, fading radially out from (focusX, focusY).
 * @param {{ width: number, height: number, dpr: number, focusX: number, focusY: number, color: string }} options
 * @returns {HTMLCanvasElement}
 */
export function buildLatticeLayer({ width, height, dpr, focusX, focusY, color }) {
  const { canvas, ctx } = createLayer(width, height, dpr);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.globalAlpha = LINE_ALPHA;
  for (let r = 0; r * ROW_HEIGHT < height + HEX_SIZE; r++) {
    for (let c = -1; c * HEX_WIDTH < width + HEX_WIDTH; c++) {
      const [x, y] = hexCenter(r, c);
      traceHex(ctx, x, y);
      ctx.stroke();
    }
  }

  // keep the lines only where the radial mask is opaque
  ctx.globalCompositeOperation = "destination-in";
  ctx.globalAlpha = 1;
  const outerRadius = Math.max(width, height) * FADE_OUTER_SCALE;
  const mask = ctx.createRadialGradient(
    focusX,
    focusY,
    FADE_INNER_RADIUS,
    focusX,
    focusY,
    outerRadius,
  );
  for (const [offset, stop] of FADE_STOPS) mask.addColorStop(offset, stop);
  ctx.fillStyle = mask;
  ctx.fillRect(0, 0, width, height);
  return canvas;
}
