// The home page's interactive pieces, mounted together. Each module owns one piece and returns
// its own cleanup; see lib/home/ for the parts.
import { reducedMotion } from "./core.js";
import { mountEngines } from "./home/engines.js";
import { mountHeroBackground } from "./home/heroBackground.js";
import { mountSectionStack } from "./home/stack.js";
import { createWheelSpin, mountWheel } from "./home/wheel.js";
import { mountWorldMap } from "./home/worldMap.js";

/**
 * Mount the home page behaviour on its root element (PoiesisHome's <main>).
 * @param {HTMLElement} root
 * @returns {() => void} cleanup
 */
export function mountHome(root) {
  const reduce = reducedMotion();
  // the wheel's speed, which the hero background reacts to
  const spin = createWheelSpin();
  const stage = root.querySelector("#stage");
  const cleanups = [
    mountWheel(root.querySelector("#wheel"), { spin, stage, reduce }),
    mountHeroBackground(root, { spin, reduce }),
    mountWorldMap(root, { reduce }),
    mountEngines(root, { reduce }),
  ];
  // last, so its resize handler runs after the canvases have resized
  const stack = mountSectionStack(root, { reduce });
  cleanups.push(stack.cleanup);
  // measure once layout has settled, and let every canvas size itself
  const settleFrame = requestAnimationFrame(() => {
    stack.refresh();
    window.dispatchEvent(new Event("resize"));
  });
  return () => {
    cancelAnimationFrame(settleFrame);
    while (cleanups.length) cleanups.pop()();
  };
}
