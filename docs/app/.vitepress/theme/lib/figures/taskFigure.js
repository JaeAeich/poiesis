// The animated "how a task runs" figure: a Pod's containers, its volume and the buckets it reads
// and writes, stepped through on a timeline that plays while on screen.
import { reducedMotion, whileVisible } from "../core.js";
import { createDeltaClock } from "./clock.js";
import { taskLayout } from "./taskLayout.js";
import { advanceTimeline, taskFrame } from "./taskTimeline.js";
import { buildTaskFigure } from "./taskFigureView.js";
import { createTaskPainter } from "./taskPainter.js";

/**
 * Render the task figure into `host`, replacing its content.
 * @param {HTMLElement} host its width picks the landscape or portrait layout
 * @param {{ compact?: boolean }} [options] compact hides the step labels
 * @returns {() => void} cleanup; the drawing stays, frozen
 */
export function mountTaskFigure(host, { compact = false } = {}) {
  const reduce = reducedMotion();
  const layout = taskLayout(host.clientWidth);
  const view = buildTaskFigure(layout, { compact });
  const paint = createTaskPainter(view);
  /** @type {import("./taskTimeline.js").TimelineState} */
  const state = { step: 0, progress: 0, playing: !reduce };
  const draw = () =>
    paint(taskFrame(state.step, state.progress, layout), state.step, state.playing);

  host.replaceChildren(view.root);
  if (reduce) view.playButton.hidden = true;

  // with reduced motion a chosen step shows its end state at once, and nothing plays
  const onSegment = (index) => {
    state.step = index;
    state.progress = reduce ? 1 : 0;
    if (reduce) state.playing = false;
    draw();
  };
  const onPlay = () => {
    state.playing = !state.playing;
    draw();
  };
  const segmentListeners = view.segments.map((segment, index) => {
    const listener = () => onSegment(index);
    segment.addEventListener("click", listener);
    return listener;
  });
  view.playButton.addEventListener("click", onPlay);
  const removeListeners = () => {
    view.segments.forEach((segment, i) =>
      segment.removeEventListener("click", segmentListeners[i]),
    );
    view.playButton.removeEventListener("click", onPlay);
  };

  if (reduce) {
    state.progress = 1;
    draw();
    return removeListeners;
  }

  draw();
  const elapsed = createDeltaClock();
  const stopLoop = whileVisible(host, (now) => {
    advanceTimeline(state, elapsed(now));
    draw();
  });
  return () => {
    stopLoop();
    removeListeners();
  };
}
