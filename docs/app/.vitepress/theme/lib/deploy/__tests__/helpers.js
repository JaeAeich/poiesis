// Test-only helpers that turn new data shapes back into the original configurator's formats.

const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
const escapeHtml = (text) => String(text).replace(/[&<>"]/g, (char) => ENTITIES[char]);

/** Highlight tokens as the HTML the original string-based highlighter produced. */
export function tokensToHtml(tokens) {
  return tokens
    .map((token) =>
      token.className
        ? `<span class="${token.className}">${escapeHtml(token.text)}</span>`
        : escapeHtml(token.text),
    )
    .join("");
}

/** A trial step as the original [html, tone] pair. */
export function trialStepToLegacy(step) {
  const html = (step.strong ? `<b>${step.strong}</b>` : "") + step.text;
  return step.tone ? [html, step.tone] : [html];
}

/** An explain spec with the original key names. */
export function explainToLegacy(spec) {
  const { points, taskFigure, ...rest } = spec;
  return { ...rest, pts: points, ...(taskFigure ? { fig: true } : {}) };
}
