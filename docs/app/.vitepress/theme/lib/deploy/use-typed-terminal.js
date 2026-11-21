import { onUnmounted, ref, watch } from "vue";
import { SESSION_TIMING } from "./agent-session.js";

/**
 * @typedef {object} TerminalLine
 * @property {number} key
 * @property {string} kind
 * @property {string} text
 */

/**
 * Plays a scripted terminal session line by line while `isActive()` is true, typing the
 * user's lines character by character, then loops. With reduced motion it shows every
 * line at once.
 * @param {[string, string][]} script
 * @param {{ isActive: () => boolean, reducedMotion: () => boolean }} options
 */
export function useTypedTerminal(script, { isActive, reducedMotion }) {
  /** @type {import("vue").Ref<TerminalLine[]>} */
  const lines = ref([]);
  const showAll = ref(false);
  let timer = 0;
  let run = 0;
  let nextKey = 0;

  const schedule = (callback, delay) => {
    timer = setTimeout(callback, delay);
  };

  function stop() {
    run++;
    clearTimeout(timer);
  }

  function start() {
    stop();
    const thisRun = run;
    lines.value = [];
    showAll.value = reducedMotion();
    if (showAll.value) {
      lines.value = script.map(([kind, text]) => ({ key: nextKey++, kind, text }));
      return;
    }

    let index = 0;
    const playNext = () => {
      if (thisRun !== run) return;
      if (index >= script.length) {
        schedule(() => {
          lines.value = [];
          index = 0;
          playNext();
        }, SESSION_TIMING.beforeRestart);
        return;
      }
      const [kind, text] = script[index++];
      lines.value.push({ key: nextKey++, kind, text: kind === "u" ? "" : text });
      const line = lines.value[lines.value.length - 1];
      if (kind !== "u") {
        schedule(playNext, SESSION_TIMING.afterLine[kind] ?? SESSION_TIMING.afterOtherLine);
        return;
      }
      let typed = 0;
      const typeNext = () => {
        if (thisRun !== run) return;
        line.text = text.slice(0, ++typed);
        if (typed < text.length) schedule(typeNext, SESSION_TIMING.perCharacter);
        else schedule(playNext, SESSION_TIMING.afterTyped);
      };
      typeNext();
    };
    playNext();
  }

  watch(isActive, (active) => (active ? start() : stop()));
  onUnmounted(stop);

  return { lines, showAll, start, stop };
}
