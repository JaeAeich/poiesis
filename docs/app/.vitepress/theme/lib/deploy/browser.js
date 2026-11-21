// Small browser helpers; call only from event handlers or onMounted.

/** @returns {boolean} */
export function prefersReducedMotion() {
  return typeof window !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Copy text to the clipboard.
 * @returns {Promise<boolean>} Whether it worked.
 */
export function copyText(text) {
  if (!navigator.clipboard) return Promise.resolve(false);
  return navigator.clipboard.writeText(text).then(
    () => true,
    () => false,
  );
}

/** Save text as a file through a temporary download link. */
export function downloadText(text, filename, type = "text/yaml") {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type }));
  link.download = filename;
  link.click();
}

/** "smooth" unless the user asked for reduced motion. */
export function scrollBehavior(reducedMotion) {
  return reducedMotion ? "auto" : "smooth";
}
