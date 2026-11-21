import { describe, expect, it } from "vitest";
import { taskLayout } from "../taskLayout.js";
import { STEP_MS, advanceTimeline, taskFrame } from "../taskTimeline.js";

const wide = taskLayout(900);
const narrow = taskLayout(390);

describe("taskLayout", () => {
  it("picks portrait only for laid-out hosts under 600px", () => {
    expect(taskLayout(0).narrow).toBe(false);
    expect(taskLayout(599).narrow).toBe(true);
    expect(taskLayout(600).narrow).toBe(false);
  });
});

describe("advanceTimeline", () => {
  it("finishes a step even when paused, then holds", () => {
    const state = { step: 0, progress: 0.9, playing: false };
    advanceTimeline(state, STEP_MS);
    expect(state).toEqual({ step: 0, progress: 1, playing: false });
    advanceTimeline(state, STEP_MS);
    expect(state.progress).toBe(1);
  });

  it("moves to the next step after the hold while playing, wrapping at the end", () => {
    const state = { step: 5, progress: 1, playing: true };
    advanceTimeline(state, 500);
    expect(state.step).toBe(5);
    advanceTimeline(state, 500);
    expect(state).toEqual({ step: 0, progress: 0, playing: true });
  });
});

describe("taskFrame", () => {
  it("starts queued, with the volume faint and nothing on it", () => {
    const frame = taskFrame(0, 0, wide);
    expect(frame.phase).toBe("Pending");
    expect(frame.volumeOpacity).toBe("0.15");
    expect(frame.filesShown).toEqual([false, false, false]);
    expect(frame.containers.map((c) => c.state)).toEqual(["idle", "idle", "idle", "idle"]);
    expect(frame.mover).toBeNull();
    expect(frame.segments[0]).toEqual({ current: true, past: false, fill: "scaleX(0.000)" });
  });

  it("runs a container, then marks it done", () => {
    expect(taskFrame(2, 0.5, wide).containers[1]).toEqual({ state: "run", barWidth: "53.3" });
    expect(taskFrame(2, 0.9, wide).containers[1]).toEqual({ state: "done", barWidth: "74.0" });
    expect(taskFrame(2, 0.9, wide).containers[0].state).toBe("done");
  });

  it("carries the input file in an arc on wide layouts and straight on narrow ones", () => {
    const wideFrame = taskFrame(1, 0.45, wide);
    expect(wideFrame.mover.label).toBe("reads.fq");
    expect(wideFrame.mover.y).toBeLessThan(150);
    expect(wideFrame.inputActive).toBe(true);
    const narrowFrame = taskFrame(1, 0.45, narrow);
    // halfway from the bucket to the first file, no arc
    expect(narrowFrame.mover.x).toBeCloseTo(132);
    expect(narrowFrame.mover.y).toBeCloseTo(215.5);
  });

  it("lands the output, then deletes the volume", () => {
    expect(taskFrame(4, 0.9, wide).outputBucketFile).toBe("sorted.bam");
    const cleanUp = taskFrame(5, 1, wide);
    expect(cleanUp.phase).toBe("Succeeded");
    expect(cleanUp.volumeNote).toBe("deleted");
    expect(cleanUp.volumeOpacity).toBe("0.20");
  });
});
