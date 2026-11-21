// Element descriptions for the hand-drawn docs diagrams. Each is { tag, attrs, text?, children? }
// and PoiDiagram.vue renders them as SVG elements; class names map to its styles.

/**
 * @typedef {object} SvgNode
 * @property {string} tag
 * @property {Record<string, string | number>} [attrs]
 * @property {string} [text]
 * @property {SvgNode[]} [children]
 */

const BOX_RADIUS = 8;
/** Arrows end in the <marker> PoiDiagram.vue defines. */
const ARROW_MARKER = "url(#pd-arrow)";

/**
 * @param {string} tag
 * @param {Record<string, string | number>} attrs
 * @param {string} [text]
 * @returns {SvgNode}
 */
export const node = (tag, attrs, text) =>
  text === undefined ? { tag, attrs } : { tag, attrs, text };

/**
 * @param {string} className
 * @param {SvgNode[]} children
 * @returns {SvgNode}
 */
export const group = (className, children) => ({ tag: "g", attrs: { class: className }, children });

/**
 * A labelled box; with `sub`, two lines centred on it.
 * @param {{ x: number, y: number, w: number, h: number, label: string, sub?: string, variant?: string, rx?: number }} box
 *   variant: "hot" (your code), "side" (sidecar), "pill"
 */
export function box({ x, y, w, h, label, sub, variant = "", rx = BOX_RADIUS }) {
  const centerX = x + w / 2;
  const children = [
    node("rect", { x, y, width: w, height: h, rx }),
    node("text", { class: "t", x: centerX, y: y + (sub ? h / 2 - 3 : h / 2 + 4) }, label),
  ];
  if (sub) children.push(node("text", { class: "s", x: centerX, y: y + h / 2 + 13 }, sub));
  return group(`bx ${variant}`, children);
}

/**
 * A database cylinder.
 * @param {{ x: number, y: number, w: number, h: number, label: string }} cylinder
 */
export function database({ x, y, w, h, label }) {
  const lip = 8;
  return group("bx db", [
    node("path", {
      d: `M${x} ${y + lip}v${h - 2 * lip}a${w / 2} ${lip} 0 0 0 ${w} 0v-${h - 2 * lip}`,
    }),
    node("ellipse", { cx: x + w / 2, cy: y + lip, rx: w / 2, ry: lip }),
    node("text", { class: "t", x: x + w / 2, y: y + h / 2 + 8 }, label),
  ]);
}

/**
 * A dashed frame with a label near its top-left corner.
 * @param {{ x: number, y: number, w: number, h: number, rx: number, label: string, labelAt: [number, number] }} frame
 */
export const frame = ({ x, y, w, h, rx, label, labelAt }) =>
  group("grp", [
    node("rect", { x, y, width: w, height: h, rx }),
    node("text", { class: "gl", x: labelAt[0], y: labelAt[1] }, label),
  ]);

/**
 * An arrow along a path, with an optional label.
 * @param {string} d
 * @param {{ variant?: string, label?: string, at?: [number, number] }} [options]
 *   variant: "tiny" (between adjacent boxes), "dash" (a reply), "self"
 * @returns {SvgNode[]}
 */
export function arrow(d, { variant = "", label, at } = {}) {
  const path = node("path", { class: `ar ${variant}`, d, "marker-end": ARROW_MARKER });
  if (!label) return [path];
  return [path, node("text", { class: "lb", x: at[0], y: at[1] }, label)];
}
