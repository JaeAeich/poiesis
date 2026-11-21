// Draws TaskFrames onto the task figure's DOM.
import { createWriter, showPlayState } from "./dom.js";

/**
 * Returns a function that draws a TaskFrame onto the view, touching only what changed.
 * @param {import("./taskFigureView.js").TaskFigureView} view
 */
export function createTaskPainter(view) {
  const write = createWriter();
  let shownStep = -1;
  let shownPlaying = null;

  /**
   * @param {import("./taskTimeline.js").TaskFrame} frame
   * @param {number} step
   * @param {boolean} playing
   */
  return function paint(frame, step, playing) {
    frame.containers.forEach(({ state, barWidth }, i) => {
      write.attr(view.containers[i].group, "class", state);
      write.attr(view.containers[i].bar, "width", barWidth);
      write.toggle(view.containerWires[i], "on", state === "run");
    });

    write.attr(view.badge, "class", "badge " + frame.phase);
    write.text(view.badgeText, frame.state);
    write.style(view.volume, "opacity", frame.volumeOpacity);
    write.text(view.volumeNote, frame.volumeNote);
    view.files.forEach((file, i) => write.style(file, "opacity", frame.filesShown[i] ? "1" : "0"));
    write.text(view.inputBucket.fileName, frame.inputBucketFile);
    write.text(view.outputBucket.fileName, frame.outputBucketFile);

    if (frame.mover) {
      const { label, x, y } = frame.mover;
      write.style(view.mover, "opacity", "1");
      view.mover.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
      write.text(view.moverText, label);
    } else {
      write.style(view.mover, "opacity", "0");
    }

    write.toggle(view.inputBucket.group, "on", frame.inputActive);
    write.toggle(view.outputBucket.group, "on", frame.outputBucketActive);
    write.toggle(view.wireIn, "on", frame.inputActive);
    write.toggle(view.wireOut, "on", frame.outputWireActive);

    frame.segments.forEach(({ current, past, fill }, i) => {
      write.toggle(view.segments[i], "cur", current);
      write.toggle(view.segments[i], "past", past);
      write.style(view.segmentBars[i], "transform", fill);
    });

    if (shownStep !== step) {
      shownStep = step;
      view.captions.forEach((caption, i) => write.toggle(caption, "on", i === step));
    }
    if (shownPlaying !== playing) {
      shownPlaying = playing;
      showPlayState(view.playButton, playing);
      // announce captions only when the visitor steps through by hand
      view.captionBox.setAttribute("aria-live", playing ? "off" : "polite");
    }
  };
}
