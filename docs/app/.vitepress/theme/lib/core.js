// Shared helpers for the Poiesis theme.
// Browser-only code runs inside mount functions (onMounted), never at module top level.

/**
 * Linear interpolation from `from` to `to`.
 * @param {number} from
 * @param {number} to
 * @param {number} t 0..1
 */
export const lerp = (from, to, t) => from + (to - from) * t;

/**
 * Clamp `value` into [min, max] (0..1 by default).
 * @param {number} value
 */
export const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));

/**
 * Cubic ease-in-out.
 * @param {number} t 0..1
 */
export const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/**
 * Read a CSS custom property from the root element.
 * @param {string} name e.g. "--blue"
 */
export const css = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Whether the visitor asked for reduced motion. Safe to call during SSR (returns false). */
export const reducedMotion = () =>
  typeof window !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * @typedef {object} Bag
 * @property {(fn: () => void) => () => void} add Register a teardown function.
 * @property {(target: EventTarget, type: string, fn: EventListener, opts?: AddEventListenerOptions | boolean) => void} on
 *   Add an event listener that is removed on dispose.
 * @property {(fn: () => void, ms: number) => number} timeout setTimeout that is cleared on dispose.
 * @property {() => void} dispose Run every teardown, newest first.
 */

/**
 * Collects teardown work so a component can undo everything on unmount.
 * @returns {Bag}
 */
export function bag() {
  const teardowns = [];
  return {
    add(fn) {
      teardowns.push(fn);
      return fn;
    },
    on(target, type, fn, opts) {
      target.addEventListener(type, fn, opts);
      teardowns.push(() => target.removeEventListener(type, fn, opts));
    },
    timeout(fn, ms) {
      const id = setTimeout(fn, ms);
      teardowns.push(() => clearTimeout(id));
      return id;
    },
    dispose() {
      while (teardowns.length) {
        try {
          teardowns.pop()();
        } catch {
          // keep tearing down the rest
        }
      }
    },
  };
}

/**
 * Run `onFrame` every animation frame while `el` is on screen.
 * @param {Element} el
 * @param {(now: number) => void} onFrame
 * @returns {() => void} stop
 */
export function whileVisible(el, onFrame) {
  let running = false;
  let frameId = 0;
  let stopped = false;
  const loop = (now) => {
    if (stopped) return;
    onFrame(now);
    if (running) frameId = requestAnimationFrame(loop);
  };
  const observer = new IntersectionObserver((entries) => {
    const visible = entries[0].isIntersecting;
    if (visible && !running) {
      running = true;
      frameId = requestAnimationFrame(loop);
    } else if (!visible) {
      running = false;
      cancelAnimationFrame(frameId);
    }
  });
  observer.observe(el);
  return () => {
    stopped = true;
    running = false;
    cancelAnimationFrame(frameId);
    observer.disconnect();
  };
}

/**
 * Call `fn` whenever VitePress toggles dark mode (a class change on <html>).
 * @param {() => void} fn
 * @returns {() => void} stop
 */
export function onThemeChange(fn) {
  const observer = new MutationObserver(() => fn());
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

/* ---------- the logo as SVG, so it can turn; geometry traced from logo.png (512 px) ---------- */

const LOGO_CENTER = 256;
const LOGO_BLUE = "#1f6aae";
const LOGO_CORAL = "#f0684c";
const LOGO_HANDLE_COUNT = 8;
const LOGO_HANDLE_PATH =
  "M-18 -136Q-7.5 -146 -7.5 -164L-9 -195A9 9 0 0 1 9 -195L7.5 -164Q7.5 -146 18 -136Z";
const LOGO_HEX_RADIUS = 122;
const LOGO_HEX_ANGLES = [-90, -30, 30, 90, 150, 210];
const LOGO_CHAIN_LINKS = 10;
const LOGO_CHAIN_RADIUS = 90;
const LOGO_CHAIN_SHRINK = 1.2; // radius lost per link, so the chain spirals inward
const LOGO_CHAIN_STEP_DEG = 36;
const LOGO_CHAIN_END_RADIUS = 85;
const LOGO_SPIRAL_TURNS = 5.6 * Math.PI;
const LOGO_SPIRAL_STEP = 0.05;
const LOGO_SPIRAL_START_RADIUS = 3;
const LOGO_SPIRAL_GROWTH = 3.05;
const LOGO_SPIRAL_PHASE = Math.PI - 0.84;

/** Point on a circle around the logo centre, angle in degrees. */
const logoPoint = (radius, degrees) => [
  LOGO_CENTER + Math.cos((degrees * Math.PI) / 180) * radius,
  LOGO_CENTER + Math.sin((degrees * Math.PI) / 180) * radius,
];

const pointList = (points) => points.map((point) => point.join(",")).join(" ");

function spiralPathData() {
  let path = "";
  for (let t = 0; t <= LOGO_SPIRAL_TURNS; t += LOGO_SPIRAL_STEP) {
    const radius = LOGO_SPIRAL_START_RADIUS + t * LOGO_SPIRAL_GROWTH;
    const x = (LOGO_CENTER + Math.cos(t + LOGO_SPIRAL_PHASE) * radius).toFixed(1);
    const y = (LOGO_CENTER + Math.sin(t + LOGO_SPIRAL_PHASE) * radius).toFixed(1);
    path += (path ? "L" : "M") + x + " " + y;
  }
  return path;
}

/**
 * Static SVG fragments of the logo (no user data), for a 512x512 viewBox.
 * @returns {{handles: string, ring: string, hex: string, inner: string, nodes: string, spiral: string}}
 */
export function logoParts() {
  let handles = "";
  for (let i = 0; i < LOGO_HANDLE_COUNT; i++) {
    const rotation = i * (360 / LOGO_HANDLE_COUNT);
    handles += `<path transform="translate(256 256) rotate(${rotation})" d="${LOGO_HANDLE_PATH}" fill="${LOGO_BLUE}"/>`;
  }

  const ring =
    `<circle cx="256" cy="256" r="140" fill="none" stroke="${LOGO_BLUE}" stroke-width="24"/>` +
    `<circle class="halo" cx="256" cy="256" r="125" fill="none" stroke-width="6"/>`;

  const hexPoints = LOGO_HEX_ANGLES.map((angle) => logoPoint(LOGO_HEX_RADIUS, angle));
  const hex = `<polygon points="${pointList(hexPoints)}" fill="none" stroke="${LOGO_BLUE}" stroke-width="5.5" stroke-linejoin="round"/>`;

  const chain = Array.from({ length: LOGO_CHAIN_LINKS }, (_, i) =>
    logoPoint(LOGO_CHAIN_RADIUS - i * LOGO_CHAIN_SHRINK, -90 + i * LOGO_CHAIN_STEP_DEG),
  );
  const chainEnd = logoPoint(LOGO_CHAIN_END_RADIUS, 90);
  const inner =
    `<line x1="${hexPoints[0][0]}" y1="${hexPoints[0][1]}" x2="${chain[0][0]}" y2="${chain[0][1]}" stroke="${LOGO_BLUE}" stroke-width="4"/>` +
    `<line x1="${hexPoints[3][0]}" y1="${hexPoints[3][1]}" x2="${chainEnd[0]}" y2="${chainEnd[1]}" stroke="${LOGO_BLUE}" stroke-width="4"/>` +
    `<polyline points="${pointList(chain)}" fill="none" stroke="${LOGO_BLUE}" stroke-width="5" stroke-linejoin="round"/>` +
    chain
      .map(
        ([x, y]) =>
          `<circle class="halo" cx="${x}" cy="${y}" r="8.5" fill="${LOGO_BLUE}" stroke-width="2.5"/>`,
      )
      .join("");

  const nodes = hexPoints
    .map(
      ([x, y], i) =>
        `<circle class="halo hn" cx="${x}" cy="${y}" r="${i % 3 === 0 ? 14 : 12}" fill="${LOGO_CORAL}" stroke-width="4"/>`,
    )
    .join("");

  const spiral = `<path class="sp" d="${spiralPathData()}" fill="none" stroke="${LOGO_CORAL}" stroke-width="10" stroke-linecap="round"/>`;

  return { handles, ring, hex, inner, nodes, spiral };
}
