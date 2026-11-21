// Figure captions are authored strings that may mark identifiers with <code>…</code>. They are
// parsed into segments and rendered as DOM nodes, never as HTML.

const CODE_SPAN = /<code>(.*?)<\/code>/g;

/**
 * @typedef {{ text: string, code: boolean }} CaptionSegment
 */

/**
 * Split a caption into plain and code segments. Other markup is kept as literal text.
 * @param {string} caption
 * @returns {CaptionSegment[]}
 */
export function parseCaption(caption) {
  const segments = [];
  let last = 0;
  for (const match of caption.matchAll(CODE_SPAN)) {
    if (match.index > last) segments.push({ text: caption.slice(last, match.index), code: false });
    segments.push({ text: match[1], code: true });
    last = match.index + match[0].length;
  }
  if (last < caption.length) segments.push({ text: caption.slice(last), code: false });
  return segments;
}

/**
 * Length of the caption as read, without markup.
 * @param {string} caption
 */
export const captionLength = (caption) => caption.replace(/<[^>]+>/g, "").length;
