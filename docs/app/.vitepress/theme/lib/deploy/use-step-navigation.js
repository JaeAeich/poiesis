import { nextTick } from "vue";
import { scrollBehavior } from "./browser.js";
import { LAST_STEP } from "./steps.js";

// A step header closer than this to the top of the viewport is scrolled into view.
const STEP_TOP_MARGIN_PX = 70;
const FIRST_FIELD_SELECTOR =
  ".bd input:not([disabled]):not([type=checkbox]),.bd select,.bd summary";

/**
 * Moving between steps: which step is open, where focus goes and what scrolls.
 * @param {import("./store.js").DeployStore} store
 * @param {{ stepsElement: () => HTMLElement | null, keyboard: { active: boolean } }} options
 */
export function useStepNavigation(store, { stepsElement, keyboard }) {
  const { wizard, ui } = store;

  const stepElement = (index) => stepsElement()?.children[index] ?? null;

  /** Scroll to a field, focus its input and flash it so the eye finds it. */
  function revealField(field) {
    field.scrollIntoView({ behavior: scrollBehavior(ui.reducedMotion), block: "center" });
    const input = field.querySelector("input,select");
    if (input) input.focus({ preventScroll: true });
    field.classList.remove("flash");
    void field.offsetWidth; // restart the animation
    field.classList.add("flash");
  }

  /**
   * Open a step. With focusId, scroll to and focus that field instead of the step.
   * @param {number} index
   * @param {string | null} [focusId]
   */
  async function goToStep(index, focusId) {
    const target = Math.min(LAST_STEP, Math.max(0, index));
    const moved = wizard.step !== target;
    wizard.step = target;
    store.closePopover();
    if (ui.panelOpen) store.openExplain();
    await nextTick();

    const step = stepElement(target);
    if (moved && !focusId && keyboard.active && step) {
      const first = step.querySelector(FIRST_FIELD_SELECTOR) || step.querySelector(".hd");
      if (first) first.focus({ preventScroll: true });
    }
    if (focusId) {
      const field = document.getElementById(focusId);
      if (field) {
        revealField(field);
        return;
      }
    }
    if (step && step.getBoundingClientRect().top < STEP_TOP_MARGIN_PX) {
      step.scrollIntoView({ behavior: scrollBehavior(ui.reducedMotion), block: "start" });
    }
  }

  /** Mark the current step done and open the next. */
  function advance() {
    wizard.completed.add(wizard.step);
    return goToStep(wizard.step + 1);
  }

  /** Fill every step with example values and jump to the review. */
  function fillAll() {
    for (let step = 0; step < LAST_STEP; step++) {
      store.fillStepExample(step);
      wizard.completed.add(step);
    }
    return goToStep(LAST_STEP);
  }

  return { goToStep, advance, fillAll };
}
