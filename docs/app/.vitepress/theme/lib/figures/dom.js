// Small DOM helpers for the figures: build elements from descriptions, write only what changed.

const SVG_NS = "http://www.w3.org/2000/svg";

const PLAY_PATH = "M8 5v14l11-7z";
const PAUSE_PATH = "M7 5h4v14H7zM13 5h4v14h-4z";

/**
 * @typedef {Record<string, string | number | boolean | undefined>} Attrs
 * `false` and `undefined` skip the attribute; `true` writes it empty.
 * @typedef {Node | string} Child
 */

function build(element, attrs, children) {
  for (const [name, value] of Object.entries(attrs)) {
    if (value === false || value === undefined) continue;
    element.setAttribute(name, value === true ? "" : String(value));
  }
  element.append(...children);
  return element;
}

/**
 * Create an SVG element.
 * @param {string} tag
 * @param {Attrs} [attrs]
 * @param {Child[]} [children] strings become text nodes
 * @returns {SVGElement}
 */
export const svgEl = (tag, attrs = {}, children = []) =>
  build(document.createElementNS(SVG_NS, tag), attrs, children);

/**
 * Create an HTML element.
 * @param {string} tag
 * @param {Attrs} [attrs]
 * @param {Child[]} [children] strings become text nodes
 * @returns {HTMLElement}
 */
export const htmlEl = (tag, attrs = {}, children = []) =>
  build(document.createElement(tag), attrs, children);

/**
 * Nodes for a caption: text, with `code` segments as <code> elements.
 * @param {import("./caption.js").CaptionSegment[]} segments
 * @returns {Child[]}
 */
export const captionNodes = (segments) =>
  segments.map((segment) => (segment.code ? htmlEl("code", {}, [segment.text]) : segment.text));

/**
 * Show the play or pause icon on a toggle button and label it with the action it will take.
 * @param {HTMLButtonElement} button
 * @param {boolean} playing
 */
export function showPlayState(button, playing) {
  const icon = svgEl("svg", { viewBox: "0 0 24 24", fill: "currentColor", "aria-hidden": "true" }, [
    svgEl("path", { d: playing ? PAUSE_PATH : PLAY_PATH }),
  ]);
  button.replaceChildren(icon);
  button.setAttribute("aria-label", playing ? "Pause" : "Play");
}

/**
 * A writer that touches the DOM only when a value changed since its last write. The figures
 * redraw every frame, and most frames change nothing.
 * @returns {{
 *   attr: (el: Element, name: string, value: string) => void,
 *   text: (el: Element, value: string) => void,
 *   style: (el: HTMLElement | SVGElement, property: "opacity" | "transform", value: string) => void,
 *   toggle: (el: Element, className: string, on: boolean) => void,
 * }}
 */
export function createWriter() {
  /** @type {WeakMap<Element, Map<string, string>>} */
  const written = new WeakMap();
  const changed = (el, key, value) => {
    let cache = written.get(el);
    if (!cache) written.set(el, (cache = new Map()));
    if (cache.get(key) === value) return false;
    cache.set(key, value);
    return true;
  };
  return {
    attr(el, name, value) {
      if (changed(el, name, value)) el.setAttribute(name, value);
    },
    text(el, value) {
      if (changed(el, "#text", value)) el.textContent = value;
    },
    style(el, property, value) {
      if (changed(el, "style:" + property, value)) el.style[property] = value;
    },
    toggle(el, className, on) {
      if (el.classList.contains(className) !== on) el.classList.toggle(className, on);
    },
  };
}
