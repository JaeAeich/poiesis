// Pure geometry for the world map behind "How a task runs".
import { clamp } from "../core.js";
import { LAND } from "./landData.js";

const PHONE_WIDTH = 760; // px; at or below this the map is zoomed in on Europe and Africa
const DESKTOP_SCALE = 1.02; // map width as a fraction of the section width
const PHONE_SCALE = 2.6;
const PHONE_CENTER_LON = 12;
const PHONE_TOP = 8; // px
const PHONE_BOTTOM_PAD = 40; // px of canvas below the map on phones
const OFFSCREEN_SLACK = 4; // px; dots this far outside the canvas are dropped
const ARC_LIFT = 0.22; // flight arcs rise by this fraction of their length

/**
 * @typedef {object} MapLayout
 * @property {boolean} phone
 * @property {number} scale px per 360 degrees of longitude
 * @property {number} originX px
 * @property {number} originY px
 * @property {number} canvasHeight px; on phones only the map band is drawn
 *
 * @typedef {[number, number]} Point
 * @typedef {[number, number, number]} LandDot [x, y, alpha]
 */

/** Degrees of latitude the grid spans. */
const LAT_SPAN = LAND.lat0 - LAND.lat1;

/**
 * Lay the map out in a `width` x `height` section.
 * @returns {MapLayout}
 */
export function mapLayout(width, height) {
  const phone = width <= PHONE_WIDTH;
  const scale = width * (phone ? PHONE_SCALE : DESKTOP_SCALE);
  const mapHeight = (scale * LAT_SPAN) / 360;
  const originX = phone
    ? width / 2 - ((PHONE_CENTER_LON + 180) / 360) * scale
    : (width - scale) / 2;
  const originY = phone ? PHONE_TOP : Math.max(0, (height - mapHeight) / 2);
  const canvasHeight = phone ? Math.min(height, originY + mapHeight + PHONE_BOTTOM_PAD) : height;
  return { phone, scale, originX, originY, canvasHeight };
}

/**
 * Equirectangular projection of (lon, lat) into the layout.
 * @param {MapLayout} layout
 * @returns {Point}
 */
export function project({ originX, originY, scale }, lon, lat) {
  return [
    originX + ((lon + 180) / 360) * scale,
    originY + (((LAND.lat0 - lat) / LAT_SPAN) * scale * LAT_SPAN) / 360,
  ];
}

/**
 * A dot per land cell that falls on the canvas. On desktop the dots fade towards the middle,
 * behind the copy; on phones they are even.
 * @param {MapLayout} layout
 * @param {number} width
 * @param {number} height section height
 * @returns {LandDot[]}
 */
export function landDots(layout, width, height) {
  const bits = atob(LAND.b64);
  const isLand = (i) => (bits.charCodeAt(i >> 3) >> (7 - (i & 7))) & 1;
  const cell = layout.scale / LAND.cols;
  const dots = [];
  for (let r = 0; r < LAND.rows; r++) {
    for (let c = 0; c < LAND.cols; c++) {
      if (!isLand(r * LAND.cols + c)) continue;
      const x = layout.originX + (c + 0.5) * cell;
      const y = layout.originY + (r + 0.5) * cell;
      if (
        x < -OFFSCREEN_SLACK ||
        x > width + OFFSCREEN_SLACK ||
        y < -OFFSCREEN_SLACK ||
        y > layout.canvasHeight + OFFSCREEN_SLACK
      ) {
        continue;
      }
      const fromMiddle = Math.hypot(
        (x - width / 2) / (width * 0.42),
        (y - height * 0.42) / (height * 0.5),
      );
      const alpha = width <= PHONE_WIDTH ? 0.28 : 0.12 + 0.3 * clamp((fromMiddle - 0.3) / 0.55);
      dots.push([x, y, alpha]);
    }
  }
  return dots;
}

/** Radius of a land dot for the layout. */
export const landDotRadius = (layout) => Math.max(0.8, (layout.scale / LAND.cols) * 0.16);

/**
 * Point `u` (0..1) along an arc from `from` to `to` that bows upwards.
 * @param {Point} from
 * @param {Point} to
 * @returns {Point}
 */
export function arcPoint(from, to, u) {
  const controlX = (from[0] + to[0]) / 2;
  const controlY = (from[1] + to[1]) / 2 - Math.hypot(to[0] - from[0], to[1] - from[1]) * ARC_LIFT;
  const v = 1 - u;
  return [
    v * v * from[0] + 2 * v * u * controlX + u * u * to[0],
    v * v * from[1] + 2 * v * u * controlY + u * u * to[1],
  ];
}

/**
 * The site nearest to (x, y).
 * @template {{ xy: Point }} S
 * @param {S[]} sites
 * @returns {S}
 */
export const nearestSite = (sites, x, y) =>
  sites.reduce((best, site) =>
    Math.hypot(site.xy[0] - x, site.xy[1] - y) < Math.hypot(best.xy[0] - x, best.xy[1] - y)
      ? site
      : best,
  );
