// State of the hero background, shared by its renderer and its pointer handlers.
import { amoebaGeometry, createAmoeba } from "./amoeba.js";
import { createHelix } from "./helix.js";
import { HEX_SIZE } from "./hex.js";
import { createTaskRings } from "./rings.js";

const FIRST_FLOW_AT = -4500; // ms; so the first workflow starts 2.5 s in
const COPY_PADDING = 10;
const OBSTACLE_MARGIN = HEX_SIZE * 0.6;
const WHEEL_CLEARANCE = 0.47; // of the wheel's width, as a radius
const AMOEBA_CLEARANCE = 1.2; // of the amoeba's radius

/**
 * @typedef {object} HeroScene
 * @property {number} width stage size, CSS px (0 until measured)
 * @property {number} height
 * @property {number} dpr
 * @property {{ line: string, blue: string, coral: string, muted: string, bg: string }} colors
 * @property {HTMLCanvasElement | null} lattice prerendered lattice layer
 * @property {{ x: number, y: number }} hub wheel centre, where tasks are thrown from
 * @property {number} helixY
 * @property {[number, number, number, number]} copyBox [left, right, top, bottom] around the copy
 * @property {import("./workflows.js").FlowSlot[]} slots
 * @property {import("./workflows.js").Flow[]} flows
 * @property {number} lastFlow
 * @property {import("./rings.js").TaskRings} tasks
 * @property {import("./amoeba.js").Amoeba} amoeba
 * @property {import("./helix.js").Helix} helix
 * @property {import("./hex.js").HexCell | null} hover hovered lattice cell
 * @property {number} now time of the latest frame
 */

/** @returns {HeroScene} */
export function createHeroScene() {
  return {
    width: 0,
    height: 0,
    dpr: 1,
    colors: {},
    lattice: null,
    hub: { x: 0, y: 0 },
    helixY: 0,
    copyBox: [0, 0, 0, 0],
    slots: [],
    flows: [],
    lastFlow: FIRST_FLOW_AT,
    tasks: createTaskRings(),
    amoeba: createAmoeba(),
    helix: createHelix(),
    hover: null,
    now: 0,
  };
}

/**
 * Whether (x, y) is over the hero copy (plus a margin).
 * @param {HeroScene} scene
 */
export function inCopy(scene, x, y) {
  const [left, right, top, bottom] = scene.copyBox;
  return x > left && x < right && y > top && y < bottom;
}

/**
 * Measure the copy box and return a test for points workflows must avoid: the amoeba, the
 * wheel and the copy. All rects are viewport rects.
 * @param {HeroScene} scene
 * @param {{ stage: DOMRect, copy: DOMRect, wheel: DOMRect }} rects
 * @returns {(x: number, y: number) => boolean}
 */
export function measureObstacles(scene, { stage, copy, wheel }) {
  const left = copy.left - stage.left - COPY_PADDING;
  const right = copy.right - stage.left + COPY_PADDING;
  const top = copy.top - stage.top - COPY_PADDING;
  const bottom = copy.bottom - stage.top + COPY_PADDING;
  scene.copyBox = [
    left - OBSTACLE_MARGIN,
    right + OBSTACLE_MARGIN,
    top - OBSTACLE_MARGIN,
    bottom + OBSTACLE_MARGIN,
  ];
  const wheelX = wheel.left - stage.left + wheel.width / 2;
  const wheelY = wheel.top - stage.top + wheel.height / 2;
  const wheelRadius = wheel.width * WHEEL_CLEARANCE + OBSTACLE_MARGIN;
  const amoeba = amoebaGeometry(scene.width, scene.height);
  return (x, y) =>
    Math.hypot(x - amoeba.cx, y - amoeba.cy) < amoeba.R * AMOEBA_CLEARANCE + HEX_SIZE ||
    Math.hypot(x - wheelX, y - wheelY) < wheelRadius ||
    inCopy(scene, x, y);
}
