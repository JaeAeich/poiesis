// The docs diagrams by name, for <PoiDiagram name="…" />.
import lifecycle from "./lifecycle.js";
import overview from "./overview.js";
import taskpod from "./taskpod.js";

/**
 * @typedef {object} Diagram
 * @property {string} viewBox
 * @property {string} label accessible name
 * @property {import("./shapes.js").SvgNode[]} nodes
 */

/** @type {Record<string, Diagram>} */
export const DIAGRAMS = { overview, taskpod, lifecycle };
