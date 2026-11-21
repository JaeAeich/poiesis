// Home sections stack: each layer stays put (sticky) while the next one slides over it, and
// fades back slightly as it is covered.
import { bag, clamp } from "../core.js";

const LAYERS = ["#stage", "#s-eng", "#s-task"];
const NAV_HEIGHT = 64; // px; the sticky top bar on wide screens
const NAV_MIN_WIDTH = 960; // px viewport where the top bar is sticky
const LAYER_OVERLAP = 24; // px each layer's rounded top overlaps the previous one
const URL_BAR_SLACK = 120; // px of height change ignored (mobile URL bar)
const COVERED_OPACITY = 0.55; // opacity lost by a fully covered layer's content
const COVERED_CANVAS_OPACITY = 0.5;
const COVERED_DROP = 24; // px a fully covered layer's content sinks
const COVERED_SHRINK = 0.04;

/**
 * How far layer `index` is covered by the next one, 0..1.
 * @param {number} nextTop viewport top of the next layer
 * @param {number} nextStart where the next layer starts covering (its natural offset, capped at the viewport height)
 * @param {number} nextStick the next layer's sticky top
 */
export function coverAmount(nextTop, nextStart, nextStick) {
  return nextStart > nextStick ? clamp((nextStart - nextTop) / (nextStart - nextStick)) : 0;
}

/**
 * @param {HTMLElement} root the home page root
 * @param {{ reduce: boolean }} options
 * @returns {{ refresh: () => void, cleanup: () => void }} `refresh` re-measures the layers
 */
export function mountSectionStack(root, { reduce }) {
  const cleanup = bag();
  const layers = LAYERS.map((selector) => root.querySelector(selector));
  const layerItems = layers.map((layer) => [...layer.querySelectorAll(".li")]);
  const stickTops = [];
  const naturalTops = [];
  let viewportWidth = 0;
  let viewportHeight = 0;
  let ticking = false;

  function measure() {
    viewportWidth = innerWidth;
    viewportHeight = innerHeight;
    const navHeight = innerWidth >= NAV_MIN_WIDTH ? NAV_HEIGHT : 0;
    let offset = NAV_HEIGHT;
    layers.forEach((layer, i) => {
      // a layer taller than the viewport sticks once its bottom reaches the viewport's
      stickTops[i] = Math.min(navHeight, innerHeight - layer.offsetHeight);
      layer.style.top = stickTops[i] + "px";
      naturalTops[i] = offset;
      offset += layer.offsetHeight - LAYER_OVERLAP;
    });
  }

  function styleItems(items, cover) {
    for (const item of items) {
      item.style.willChange = cover > 0 && cover < 1 ? "transform,opacity" : "";
      if (item.tagName === "CANVAS") {
        item.style.opacity = cover ? (1 - cover * COVERED_CANVAS_OPACITY).toFixed(3) : "";
        continue;
      }
      item.style.opacity = cover ? (1 - cover * COVERED_OPACITY).toFixed(3) : "";
      item.style.transform = cover
        ? `translateY(${(cover * COVERED_DROP).toFixed(1)}px) scale(${(1 - cover * COVERED_SHRINK).toFixed(4)})`
        : "";
    }
  }

  // read every top first, then write
  function update() {
    ticking = false;
    const tops = layers.map((layer) => layer.getBoundingClientRect().top);
    layers.forEach((layer, i) => {
      let cover = 0;
      if (i + 1 < layers.length) {
        const nextStart = Math.min(innerHeight, naturalTops[i + 1]);
        cover = coverAmount(tops[i + 1], nextStart, stickTops[i + 1]);
      }
      layer.dataset.cover = cover.toFixed(3);
      if (!reduce) styleItems(layerItems[i], cover);
    });
  }

  cleanup.on(
    window,
    "scroll",
    () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(update);
    },
    { passive: true },
  );
  // the Android URL bar changes the height a little while scrolling; only a real resize moves the layers
  cleanup.on(window, "resize", () => {
    if (innerWidth !== viewportWidth || Math.abs(innerHeight - viewportHeight) > URL_BAR_SLACK)
      measure();
    update();
  });
  // keyboard focus inside a covered layer: scroll back until that layer is uncovered
  cleanup.on(root, "focusin", (event) => {
    const i = layers.findIndex((layer) => layer.contains(event.target));
    if (i < 0 || i + 1 >= layers.length || !(+layers[i].dataset.cover > 0)) return;
    requestAnimationFrame(() => {
      const nextTop = layers[i + 1].getBoundingClientRect().top;
      const nextStart = Math.min(innerHeight, naturalTops[i + 1]);
      if (nextTop < nextStart)
        scrollBy({ top: nextTop - nextStart, behavior: reduce ? "auto" : "smooth" });
    });
  });
  // undo the inline styles so nothing lingers after unmount
  cleanup.add(() => {
    for (const items of layerItems) {
      for (const item of items) {
        item.style.opacity = "";
        item.style.transform = "";
      }
    }
  });

  return {
    refresh() {
      measure();
      update();
    },
    cleanup: () => cleanup.dispose(),
  };
}
