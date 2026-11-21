// Hero background: a benzene lattice whose rings light up with circulating electrons (click
// one), workflows running on it, an amoeba in the corner and a DNA helix under the buttons.
import { bag, onThemeChange, whileVisible } from "../core.js";
import { drawAmoeba } from "./amoeba.js";
import { advanceHelix, drawHelix } from "./helix.js";
import { createHeroScene, inCopy, measureObstacles } from "./heroScene.js";
import { bindHeroPointer } from "./heroPointer.js";
import { traceHex } from "./hex.js";
import { buildLatticeLayer } from "./lattice.js";
import { drawFliers, drawRing, maybeThrowTask } from "./rings.js";
import { canvasDpr, createFrameClock, isCovered, readColors, sizeCanvas } from "./shared.js";
import { drawFlows, findFlowSlots, spawnFlow } from "./workflows.js";

const COLOR_TOKENS = {
  line: "--line-strong",
  blue: "--blue",
  coral: "--coral",
  muted: "--muted",
  bg: "--bg",
};
const WIDE_STAGE = 760; // px; on wider stages the helix sits below the wheel too
const HELIX_GAP = 72; // px below the buttons (or the wheel)
const WHEEL_OVERLAP = 30; // the helix may start this far above the wheel's bottom
const BUSY_SPIN = 0.5; // wheel speed above which the background reacts to it
const FLOW_INTERVAL_MS = 7000;
const MAX_FLOWS = 2;

/**
 * @typedef {import("./wheel.js").WheelSpin} WheelSpin
 * @param {HTMLElement} root the home page root
 * @param {{ spin: WheelSpin, reduce: boolean }} options
 * @returns {() => void} cleanup
 */
export function mountHeroBackground(root, { spin, reduce }) {
  const stage = root.querySelector("#stage");
  const canvas = root.querySelector("#bg");
  const wheelEl = root.querySelector("#wheel");
  const actionsEl = root.querySelector("#hero-actions");
  const copyEl = root.querySelector("#copy");
  const ctx = canvas.getContext("2d");
  const scene = createHeroScene();
  const frameClock = createFrameClock();
  const cleanup = bag();

  function refreshColors() {
    scene.colors = readColors(COLOR_TOKENS);
  }

  function rebuildLattice() {
    scene.lattice = buildLatticeLayer({
      width: scene.width,
      height: scene.height,
      dpr: scene.dpr,
      focusX: scene.hub.x,
      focusY: scene.hub.y,
      color: scene.colors.line,
    });
  }

  // every place each workflow shape fits, recomputed on resize; spawning picks from these
  function computeSlots() {
    scene.slots = [];
    if (!scene.width) return;
    const isBlocked = measureObstacles(scene, {
      stage: stage.getBoundingClientRect(),
      copy: copyEl.getBoundingClientRect(),
      wheel: wheelEl.getBoundingClientRect(),
    });
    scene.slots = findFlowSlots({ width: scene.width, bottom: scene.helixY, isBlocked });
    stage.dataset.slots = String(scene.slots.length);
  }

  function resize() {
    const rect = stage.getBoundingClientRect();
    if (!rect.width || (rect.width === scene.width && rect.height === scene.height)) return;
    scene.dpr = canvasDpr();
    scene.width = rect.width;
    scene.height = rect.height;
    sizeCanvas(canvas, ctx, scene.width, scene.height, scene.dpr);
    const wheel = wheelEl.getBoundingClientRect();
    const actions = actionsEl.getBoundingClientRect();
    scene.hub = {
      x: wheel.left - rect.left + wheel.width / 2,
      y: wheel.top - rect.top + wheel.height / 2,
    };
    const helixTop = Math.max(
      actions.bottom,
      scene.width > WIDE_STAGE ? wheel.bottom - WHEEL_OVERLAP : 0,
    );
    scene.helixY = helixTop - rect.top + HELIX_GAP;
    refreshColors();
    rebuildLattice();
    computeSlots();
    if (reduce) frame(performance.now());
  }

  function frame(now) {
    scene.now = now;
    if (!scene.width) return;
    const { tasks, helix, colors } = scene;
    const spinSpeed = Math.abs(spin.velocity);
    const busy = spinSpeed > BUSY_SPIN && !spin.calm;
    // idle: draw at ~30 fps; scaling by elapsed frames keeps speeds the same
    const idle =
      !reduce &&
      !busy &&
      !scene.hover &&
      !scene.amoeba.on &&
      !helix.hot &&
      helix.hotAlpha < 0.02 &&
      !tasks.rings.some((ring) => ring.strong);
    const frames = frameClock(now, idle);
    if (!frames) return;
    if (isCovered(stage)) return;

    ctx.clearRect(0, 0, scene.width, scene.height);
    ctx.globalAlpha = 1;
    ctx.drawImage(scene.lattice, 0, 0, scene.width, scene.height);
    drawAmoeba(ctx, scene.amoeba, now, {
      width: scene.width,
      height: scene.height,
      reduce,
      colors,
    });
    if (scene.hover) {
      ctx.globalAlpha = 0.55;
      ctx.strokeStyle = colors.blue;
      ctx.lineWidth = 1.2;
      traceHex(ctx, scene.hover.x, scene.hover.y);
      ctx.stroke();
    }

    if (!reduce && (busy || !scene.flows.length)) {
      maybeThrowTask(tasks, {
        now,
        busy,
        spin: spinSpeed,
        velocity: spin.velocity,
        hub: scene.hub,
        stageSize: Math.min(scene.width, scene.height),
        isBlocked: (x, y) => inCopy(scene, x, y),
      });
    }
    tasks.rings = tasks.rings.filter((ring) => now - ring.t0 < ring.dur);
    for (const ring of tasks.rings) drawRing(ctx, ring, now, colors);

    if (!reduce && now - scene.lastFlow > FLOW_INTERVAL_MS && scene.flows.length < MAX_FLOWS) {
      scene.lastFlow = now;
      spawnFlow(scene.flows, scene.slots, now);
    }
    scene.flows = drawFlows(ctx, scene.flows, now, colors);

    tasks.fliers = tasks.fliers.filter((flier) => now - flier.t0 < flier.dur);
    drawFliers(ctx, tasks.fliers, scene.hub, now, colors.coral);

    advanceHelix(helix, frames, spinSpeed, reduce);
    drawHelix(ctx, helix, { width: scene.width, y: scene.helixY, colors });
  }

  cleanup.add(bindHeroPointer(stage, scene, { reduce, redraw: frame }));
  cleanup.on(window, "resize", resize);
  cleanup.add(
    onThemeChange(() => {
      refreshColors();
      rebuildLattice();
      if (reduce) frame(performance.now());
    }),
  );
  resize();
  if (reduce) frame(performance.now());
  else cleanup.add(whileVisible(stage, frame));
  return () => cleanup.dispose();
}
