// The hero wheel: the logo as SVG, turned by dragging or the arrow keys, coasting to a stop.
import { bag, clamp, lerp, logoParts, whileVisible } from "../core.js";
import { FRAME_MS, createFrameClock, isCovered } from "./shared.js";

const MAX_SPIN = 18; // degrees per frame
const NUDGE_DELAY_MS = 2400;
const NUDGE_SPIN = 4;
const KEY_SPIN = 4; // added per arrow key press
const FRICTION = 0.968; // velocity kept per frame
const STOP_BELOW = 0.01;
const DRAG_SMOOTHING = 0.5;
const MIN_DRAG_DT = 8; // ms; ignore faster pointer events when measuring speed
const HOLD_STILL_MS = 60; // released after holding still this long: no throw
const SPIRAL_DRIFT = 0.12; // degrees per frame the spiral turns on its own
const SPIRAL_COUNTER = 0.55; // the spiral turns against the wheel by this ratio
const NODE_SWELL = 0.35; // hex nodes grow by up to this much while spinning
const NODE_SWELL_SPIN = 10; // spin at which they are fully grown
const KEY_STEPS = new Map([
  ["ArrowRight", KEY_SPIN],
  ["ArrowUp", KEY_SPIN],
  ["ArrowLeft", -KEY_SPIN],
  ["ArrowDown", -KEY_SPIN],
]);

/**
 * Shared with the hero background, which reacts to the wheel turning.
 * @typedef {object} WheelSpin
 * @property {number} velocity degrees per 60 fps frame
 * @property {boolean} calm a gentle automatic spin, which the background ignores
 */

/** @returns {WheelSpin} */
export const createWheelSpin = () => ({ velocity: 0, calm: false });

/** Angle change from `from` to `to` in degrees, the short way round (-180..180). */
export function angleDelta(from, to) {
  let delta = to - from;
  if (delta > 180) delta -= 360;
  if (delta < -180) delta += 360;
  return delta;
}

/**
 * Let a free wheel coast for `frames` frames; returns the new angle.
 * @param {WheelSpin} spin
 * @param {number} angle
 * @param {number} frames
 */
export function coast(spin, angle, frames) {
  const next = angle + spin.velocity * frames;
  spin.velocity *= Math.pow(FRICTION, frames);
  if (Math.abs(spin.velocity) < STOP_BELOW) {
    spin.velocity = 0;
    spin.calm = false;
  }
  return next;
}

/** Static SVG for the wheel; logoParts() holds no user data. */
function wheelMarkup() {
  const parts = logoParts();
  return `<svg viewBox="0 0 512 512" aria-hidden="true">
    <g id="w-rot">
      <g class="in h">${parts.handles}</g>
      <g class="in" style="animation-delay:.05s">${parts.ring}</g>
      <g class="in" style="animation-delay:.18s">${parts.hex}${parts.inner}</g>
      <g class="in" style="animation-delay:.3s">${parts.nodes}</g>
    </g>
    <g id="w-sp">${parts.spiral}</g></svg>`;
}

/**
 * @param {HTMLElement} el the `role="slider"` wheel element
 * @param {{ spin: WheelSpin, stage: HTMLElement, reduce: boolean }} options
 * @returns {() => void} cleanup
 */
export function mountWheel(el, { spin, stage, reduce }) {
  const cleanup = bag();
  el.innerHTML = wheelMarkup();
  const spiralPath = el.querySelector(".sp");
  spiralPath.style.setProperty("--len", spiralPath.getTotalLength());
  const rotor = el.querySelector("#w-rot");
  const spiral = el.querySelector("#w-sp");
  const nodes = [...el.querySelectorAll(".hn")];
  const nodeRadii = nodes.map((node) => +node.getAttribute("r"));
  const frameClock = createFrameClock();
  let angle = 0;
  let spiralAngle = 0;
  let dragging = false;
  let touched = false;
  let lastPointerAngle = 0;
  let lastPointerTime = 0;
  let lastSwell = 0;
  let lastDegrees = -1;

  // a gentle nudge on load; it doesn't count as spinning, so no burst of rings
  if (!reduce) {
    cleanup.timeout(() => {
      if (touched) return;
      spin.velocity = NUDGE_SPIN;
      spin.calm = true;
    }, NUDGE_DELAY_MS);
  }

  const pointerAngle = (event) => {
    const rect = el.getBoundingClientRect();
    const dy = event.clientY - (rect.top + rect.height / 2);
    const dx = event.clientX - (rect.left + rect.width / 2);
    return (Math.atan2(dy, dx) * 180) / Math.PI;
  };

  cleanup.on(el, "pointerdown", (event) => {
    dragging = true;
    touched = true;
    lastPointerAngle = pointerAngle(event);
    lastPointerTime = performance.now();
    el.setPointerCapture(event.pointerId);
    el.classList.add("grab");
    spin.velocity = 0;
    spin.calm = false;
  });
  cleanup.on(el, "pointermove", (event) => {
    if (!dragging) return;
    const current = pointerAngle(event);
    const now = performance.now();
    const delta = angleDelta(lastPointerAngle, current);
    angle += delta;
    const dt = Math.max(MIN_DRAG_DT, now - lastPointerTime);
    const velocity = lerp(spin.velocity, (delta / dt) * FRAME_MS, DRAG_SMOOTHING);
    spin.velocity = clamp(velocity, -MAX_SPIN, MAX_SPIN);
    lastPointerAngle = current;
    lastPointerTime = now;
  });
  // let go after holding still: it stays still
  const release = () => {
    if (dragging && performance.now() - lastPointerTime > HOLD_STILL_MS) spin.velocity = 0;
    dragging = false;
    el.classList.remove("grab");
  };
  cleanup.on(el, "pointerup", release);
  cleanup.on(el, "pointercancel", release);
  cleanup.on(el, "keydown", (event) => {
    const step = KEY_STEPS.get(event.key) || 0;
    if (!step) return;
    touched = true;
    spin.calm = false;
    spin.velocity = clamp(spin.velocity + step, -MAX_SPIN, MAX_SPIN);
    event.preventDefault();
  });

  function frame(now) {
    const frames = frameClock(now);
    if (isCovered(stage)) return;
    if (!dragging) angle = coast(spin, angle, frames);
    spiralAngle += reduce ? 0 : (-spin.velocity * SPIRAL_COUNTER - SPIRAL_DRIFT) * frames;
    rotor.setAttribute("transform", `rotate(${angle.toFixed(2)} 256 256)`);
    spiral.setAttribute("transform", `rotate(${spiralAngle.toFixed(2)} 256 256)`);

    const swell = clamp(Math.abs(spin.velocity) / NODE_SWELL_SPIN);
    if (swell || lastSwell) {
      nodes.forEach((node, i) => {
        const scale = 1 + swell * NODE_SWELL * (0.6 + 0.4 * Math.sin(angle / 20 + i));
        node.setAttribute("r", (nodeRadii[i] * scale).toFixed(2));
      });
    }
    lastSwell = swell;

    const degrees = Math.round(((angle % 360) + 360) % 360) % 360;
    if (degrees !== lastDegrees) {
      lastDegrees = degrees;
      el.setAttribute("aria-valuenow", String(degrees));
      el.setAttribute("aria-valuetext", degrees + " degrees");
    }
  }
  cleanup.add(whileVisible(el, frame));
  return () => cleanup.dispose();
}
