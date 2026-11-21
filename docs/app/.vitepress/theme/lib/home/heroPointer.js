// Pointer play on the hero background: the empty lattice is a plaything, the amoeba eats, and
// the helix band reads out.
import { bag } from "../core.js";
import { amoebaContains, feedAmoeba } from "./amoeba.js";
import { isOnHelix } from "./helix.js";
import { hexCenter, nearestHex } from "./hex.js";
import { addRing } from "./rings.js";

const INTERACTIVE = "a,button,h1,p,.wheel"; // pointer over these is not on the lattice
const TAP_READOUT_MS = 5000; // a tap on the helix reads out for this long
// a click lights its cell and then, one after another, three neighbours
const NEIGHBOURS_FIRST_DELAY_MS = 300;
const NEIGHBOURS_STAGGER_MS = 220;
const REDUCED_CLICK_PREVIEW_MS = 400; // with reduced motion, show the click as it looks this much later

/**
 * @param {HTMLElement} stage
 * @param {import("./heroScene.js").HeroScene} scene
 * @param {{ reduce: boolean, redraw: (now: number) => void }} options
 *   `redraw` draws a frame; with reduced motion nothing else does
 * @returns {() => void} cleanup
 */
export function bindHeroPointer(stage, scene, { reduce, redraw }) {
  const cleanup = bag();
  const { amoeba, helix } = scene;
  const redrawIfStill = () => {
    if (reduce) redraw(performance.now());
  };
  const onLattice = (event) => !event.target.closest(INTERACTIVE);
  let readoutTimer = 0;
  cleanup.add(() => clearTimeout(readoutTimer));

  cleanup.on(stage, "pointermove", (event) => {
    if (!scene.width) return;
    const rect = stage.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    amoeba.on = onLattice(event) && amoebaContains(amoeba, x, y);
    if (amoeba.on) {
      amoeba.px = x;
      amoeba.py = y;
    }
    stage.classList.toggle("amoeba-hover", amoeba.on);
    const free = onLattice(event) && !amoeba.on;
    if (event.pointerType === "mouse") helix.hot = free && isOnHelix(helix, y, scene.helixY);
    scene.hover = free && !helix.hot ? nearestHex(x, y) : null;
    stage.classList.toggle("lat-hover", !!scene.hover);
    redrawIfStill();
  });

  // touch has no hover: a tap on the helix toggles the read-out
  cleanup.on(stage, "pointerdown", (event) => {
    if (event.pointerType === "mouse" || !scene.width) return;
    const y = event.clientY - stage.getBoundingClientRect().top;
    if (!onLattice(event) || !isOnHelix(helix, y, scene.helixY)) return;
    helix.hot = !helix.hot;
    clearTimeout(readoutTimer);
    if (helix.hot) {
      readoutTimer = setTimeout(() => {
        helix.hot = false;
        redrawIfStill();
      }, TAP_READOUT_MS);
    }
    redrawIfStill();
  });

  cleanup.on(stage, "pointerleave", (event) => {
    amoeba.on = false;
    stage.classList.remove("amoeba-hover");
    if (event.pointerType !== "mouse") return;
    scene.hover = null;
    helix.hot = false;
    stage.classList.remove("lat-hover");
    redrawIfStill();
  });

  cleanup.on(stage, "click", (event) => {
    if (!onLattice(event) || !scene.width || helix.hot) return;
    const rect = stage.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (amoebaContains(amoeba, x, y)) {
      feedAmoeba(amoeba, x, y, performance.now());
      redrawIfStill();
      return;
    }
    const cell = nearestHex(x, y);
    addRing(scene.tasks.rings, { x: cell.x, y: cell.y, strong: true }, scene.now);
    const neighbours = [
      [0, -1],
      [0, 1],
      [-1, cell.r % 2 ? 1 : -1],
    ];
    neighbours.forEach(([dr, dc], i) => {
      const [nx, ny] = hexCenter(cell.r + dr, cell.c + dc);
      const delay = NEIGHBOURS_FIRST_DELAY_MS + i * NEIGHBOURS_STAGGER_MS;
      addRing(scene.tasks.rings, { x: nx, y: ny, strong: false, delay }, scene.now);
    });
    if (reduce) redraw(performance.now() + REDUCED_CLICK_PREVIEW_MS);
  });

  return () => cleanup.dispose();
}
