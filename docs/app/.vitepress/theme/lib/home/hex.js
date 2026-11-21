// Geometry of the hero's benzene lattice: pointy-top hexagons in offset rows (odd rows shift right).

/** Hexagon circumradius, px. */
export const HEX_SIZE = 26;
/** Horizontal distance between neighbouring centres in a row. */
export const HEX_WIDTH = Math.sqrt(3) * HEX_SIZE;
/** Vertical distance between rows. */
export const ROW_HEIGHT = 1.5 * HEX_SIZE;

const DEG = Math.PI / 180;

/**
 * @typedef {object} HexCell
 * @property {number} r row
 * @property {number} c column
 * @property {number} x centre x, px
 * @property {number} y centre y, px
 */

/**
 * Corner `i` (0..5) of the hexagon centred at (x, y).
 * @returns {[number, number]}
 */
export function hexVertex(x, y, i) {
  const angle = DEG * (60 * i - 30);
  return [x + HEX_SIZE * Math.cos(angle), y + HEX_SIZE * Math.sin(angle)];
}

/**
 * Begin a path tracing the hexagon centred at (x, y); the caller fills or strokes it.
 * @param {CanvasRenderingContext2D} ctx
 */
export function traceHex(ctx, x, y, radius = HEX_SIZE) {
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const angle = DEG * (60 * i - 30);
    ctx.lineTo(x + radius * Math.cos(angle), y + radius * Math.sin(angle));
  }
  ctx.closePath();
}

/**
 * Centre of the cell at (row, col).
 * @returns {[number, number]}
 */
export const hexCenter = (row, col) => [
  col * HEX_WIDTH + (row % 2 ? HEX_WIDTH / 2 : 0),
  row * ROW_HEIGHT,
];

/**
 * The cell whose centre is nearest to (x, y).
 * @returns {HexCell}
 */
export function nearestHex(x, y) {
  let best = null;
  let bestDistance = 1e9;
  const middleRow = Math.round(y / ROW_HEIGHT);
  for (let r = middleRow - 1; r <= middleRow + 1; r++) {
    const c = Math.round((x - (r % 2 ? HEX_WIDTH / 2 : 0)) / HEX_WIDTH);
    const [cx, cy] = hexCenter(r, c);
    const distance = (cx - x) ** 2 + (cy - y) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = { r, c, x: cx, y: cy };
    }
  }
  return best;
}
