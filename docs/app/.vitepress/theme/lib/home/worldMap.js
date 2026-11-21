// Behind "How a task runs": the world, with tasks arriving at Poiesis deployments in several regions.
import { bag, clamp, ease, onThemeChange, whileVisible } from "../core.js";
import {
  canvasDpr,
  createFrameClock,
  createLayer,
  fillCircle,
  readColors,
  sizeCanvas,
  strokeCircle,
} from "./shared.js";
import {
  arcPoint,
  landDotRadius,
  landDots,
  mapLayout,
  nearestSite,
  project,
} from "./worldGeometry.js";

const COLOR_TOKENS = { dot: "--line-strong", blue: "--blue", coral: "--coral", muted: "--muted" };
/** Deployments as [lon, lat]: Frankfurt, Virginia, Oregon, Mumbai, Singapore, São Paulo, Sydney. */
const SITES = [
  [8.7, 50.1],
  [-77, 39],
  [-122, 45.5],
  [72.9, 19],
  [103.8, 1.3],
  [-46.6, -23.5],
  [151, -33.9],
];
const LAUNCH_INTERVAL_MS = 1400;
const MAX_FLIGHTS = 4;
const MIN_FLIGHT_DISTANCE = 0.04; // of the map scale; tasks already at a site don't fly
const FLIGHT_MIN_MS = 2600;
const FLIGHT_JITTER_MS = 1200;
const FLIGHT_LINGER = 0.5; // the trail fades out over this fraction of the flight time after landing
const TRAIL_STEP = 0.025;
const TASK_RADIUS = 2.6;
const PULSE_MS = 1100;
const PULSE_GROWTH = 18; // px
const SITE_HALO_RADIUS = 8;
const SITE_RADIUS = 2.8;

/**
 * @typedef {{ xy: import("./worldGeometry.js").Point, pulse: number }} Site
 * @typedef {{ a: import("./worldGeometry.js").LandDot, s: Site, t0: number, dur: number, hit?: boolean }} Flight
 */

/**
 * @param {HTMLElement} root the home page root
 * @param {{ reduce: boolean }} options
 * @returns {() => void} cleanup
 */
export function mountWorldMap(root, { reduce }) {
  const section = root.querySelector("#s-task");
  const canvas = root.querySelector("#world");
  if (!canvas) return () => {};
  const ctx = canvas.getContext("2d");
  const cleanup = bag();
  const frameClock = createFrameClock();
  let width = 0;
  let height = 0;
  let canvasHeight = 0;
  let dpr = 1;
  let layout = null;
  let colors = {};
  let dots = [];
  let land = null;
  /** @type {Site[]} */
  let sites = [];
  /** @type {Flight[]} */
  let flights = [];
  let lastLaunch = 0;

  const refreshColors = () => {
    colors = readColors(COLOR_TOKENS);
  };

  // land dots drawn once, off screen; frames only copy them
  function buildLand() {
    const layer = createLayer(width, canvasHeight, dpr);
    const radius = landDotRadius(layout);
    layer.ctx.fillStyle = colors.dot;
    for (const [x, y, alpha] of dots) {
      layer.ctx.globalAlpha = alpha;
      fillCircle(layer.ctx, x, y, radius);
    }
    land = layer.canvas;
  }

  function resize() {
    const rect = section.getBoundingClientRect();
    if (!rect.width || (rect.width === width && rect.height === height)) return;
    dpr = canvasDpr();
    width = rect.width;
    height = rect.height;
    layout = mapLayout(width, height);
    canvasHeight = layout.canvasHeight;
    // phones: only the map band, not the whole section
    canvas.style.height = layout.phone ? canvasHeight + "px" : "";
    sizeCanvas(canvas, ctx, width, canvasHeight, dpr);
    dots = landDots(layout, width, height);
    sites = SITES.map(([lon, lat]) => ({ xy: project(layout, lon, lat), pulse: 0 }));
    refreshColors();
    buildLand();
  }

  function launchFlight(now) {
    lastLaunch = now;
    const from = dots[Math.floor(Math.random() * dots.length)];
    const site = nearestSite(sites, from[0], from[1]);
    if (
      Math.hypot(site.xy[0] - from[0], site.xy[1] - from[1]) >
      layout.scale * MIN_FLIGHT_DISTANCE
    ) {
      flights.push({
        a: from,
        s: site,
        t0: now,
        dur: FLIGHT_MIN_MS + Math.random() * FLIGHT_JITTER_MS,
      });
    }
  }

  /** Draws a flight; returns false once it has faded out. */
  function drawFlight(flight, now) {
    const progress = (now - flight.t0) / flight.dur;
    if (progress > 1 + FLIGHT_LINGER) return false;
    const eased = ease(clamp(progress));
    const fade = 1 - clamp((progress - 1) / FLIGHT_LINGER);
    const target = flight.s.xy;
    ctx.globalAlpha = 0.45 * fade;
    ctx.strokeStyle = colors.muted;
    ctx.lineWidth = 1;
    strokeCircle(ctx, flight.a[0], flight.a[1], TASK_RADIUS);

    ctx.globalAlpha = 0.32 * fade;
    ctx.strokeStyle = colors.coral;
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 4]);
    ctx.beginPath();
    for (let v = 0; v <= eased; v += TRAIL_STEP) {
      const [x, y] = arcPoint(flight.a, target, v);
      if (v) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    if (progress < 1) {
      const [x, y] = arcPoint(flight.a, target, eased);
      ctx.globalAlpha = 0.9;
      ctx.fillStyle = colors.coral;
      fillCircle(ctx, x, y, TASK_RADIUS);
    } else if (!flight.hit) {
      flight.hit = true;
      flight.s.pulse = now;
    }
    return true;
  }

  function drawSite(site, now) {
    const [x, y] = site.xy;
    const pulse = clamp((now - site.pulse) / PULSE_MS);
    if (site.pulse && pulse < 1) {
      ctx.globalAlpha = (1 - ease(pulse)) * 0.45;
      ctx.strokeStyle = colors.blue;
      ctx.lineWidth = 1.1;
      strokeCircle(ctx, x, y, 4 + ease(pulse) * PULSE_GROWTH);
    }
    ctx.globalAlpha = 0.16;
    ctx.fillStyle = colors.blue;
    fillCircle(ctx, x, y, SITE_HALO_RADIUS);
    ctx.globalAlpha = 0.9;
    fillCircle(ctx, x, y, SITE_RADIUS);
  }

  function frame(now) {
    if (!width) return;
    if (!frameClock(now, !reduce)) return;
    ctx.clearRect(0, 0, width, canvasHeight);
    ctx.globalAlpha = 1;
    ctx.drawImage(land, 0, 0, width, canvasHeight);
    if (!reduce && now - lastLaunch > LAUNCH_INTERVAL_MS && flights.length < MAX_FLIGHTS) {
      launchFlight(now);
    }
    flights = flights.filter((flight) => drawFlight(flight, now));
    for (const site of sites) drawSite(site, now);
    ctx.globalAlpha = 1;
  }

  const resizeObserver = new ResizeObserver(() => {
    resize();
    if (reduce) frame(performance.now());
  });
  resizeObserver.observe(section);
  cleanup.add(() => resizeObserver.disconnect());
  cleanup.add(
    onThemeChange(() => {
      refreshColors();
      if (width) buildLand();
      if (reduce) frame(performance.now());
    }),
  );
  resize();
  if (reduce) frame(performance.now());
  else cleanup.add(whileVisible(section, frame));
  return () => cleanup.dispose();
}
