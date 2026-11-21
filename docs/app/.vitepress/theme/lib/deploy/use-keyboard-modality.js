import { onMounted, onUnmounted } from "vue";

/**
 * Tracks whether the user is driving the page with the keyboard, so focus is only moved
 * for keyboard users. Listens in the capture phase to see events before handlers run.
 * @returns {{ readonly active: boolean }}
 */
export function useKeyboardModality() {
  const state = { active: false };
  const onKeyDown = () => {
    state.active = true;
  };
  const onPointerDown = () => {
    state.active = false;
  };
  onMounted(() => {
    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("pointerdown", onPointerDown, true);
  });
  onUnmounted(() => {
    window.removeEventListener("keydown", onKeyDown, true);
    window.removeEventListener("pointerdown", onPointerDown, true);
  });
  return state;
}
