// Shared shape of generated files: each line remembers which step wrote it.

/**
 * @typedef {object} FileLine
 * @property {string} text
 * @property {number} step Step index, or one of the LINE_OWNER values.
 */

export const LINE_OWNER = Object.freeze({
  /** Header and footer lines no step owns. */
  NONE: -1,
  /** Lines typed by hand in the editor. */
  MANUAL: -2,
});

/** Collects lines in order; `blank` adds an empty separator line. */
export function createLineWriter() {
  /** @type {FileLine[]} */
  const lines = [];
  return {
    lines,
    /** @param {string} text @param {number} step */
    add(text, step) {
      lines.push({ text, step });
    },
    /** @param {number} step */
    blank(step) {
      lines.push({ text: "", step });
    },
  };
}

/** File contents with exactly one trailing newline. */
export function linesToText(lines) {
  return lines
    .map((line) => line.text)
    .join("\n")
    .replace(/\n*$/, "\n");
}

/** Lines of a hand-edited file; no step owns them. */
export function manualLines(text) {
  return text.split("\n").map((line) => ({ text: line, step: LINE_OWNER.MANUAL }));
}
