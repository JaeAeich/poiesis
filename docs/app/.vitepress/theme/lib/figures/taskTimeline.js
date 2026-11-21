// The task figure as a pure function of time: which step it is on, how far into it, and what
// every part of the drawing looks like at that moment.
import { clamp, ease, lerp } from "../core.js";
import { CONTAINER_PADDING, rectCenter } from "./taskLayout.js";
import { CONTAINERS, FILES, INPUT_FILE, OUTPUT_FILE, STEP, TASK_STEPS } from "./taskSteps.js";

/** Length of one step, ms. */
export const STEP_MS = 2600;
/** Pause at the end of a step before the next one starts, ms. */
const HOLD_MS = 700;

/** A container's progress bar fills over this much of its step, then it shows done. */
const RUN_END = 0.85;
/** During submit the Pod is pending, then running from this point. */
const POD_STARTS_AT = 0.5;
/** The volume fades in from this opacity during submit. */
const VOLUME_START_OPACITY = 0.15;
/** During clean up the volume fades to VOLUME_END_OPACITY over this window. */
const VOLUME_FADE_START = 0.45;
const VOLUME_FADE_LENGTH = 0.4;
const VOLUME_END_OPACITY = 0.2;
/** During clean up the volume's note reads "deleted" from this point. */
const VOLUME_DELETED_AT = 0.6;
/** When, within its writer's step, each file appears on the volume. */
const FILE_WRITTEN_AT = [0.8, 0.6, 0.6];
/** The output file lands in the output bucket at this point of stage out. */
const OUTPUT_LANDS_AT = 0.82;
/** Windows in which a file travels between bucket and volume. */
const STAGE_IN_TRIP = { start: 0.1, end: 0.8 };
const STAGE_OUT_TRIP = { start: 0.1, end: 0.82 };
/** The input bucket and wire light up until this point of stage in. */
const STAGE_IN_ACTIVE_UNTIL = 0.8;
/** The output bucket and wire light up from these points of stage out. */
const OUTPUT_BUCKET_ACTIVE_FROM = 0.5;
const OUTPUT_WIRE_ACTIVE_FROM = 0.4;
/** In the wide layout, a travelling file arcs up by this much at mid-trip. */
const TRIP_ARC = 36;

/**
 * @typedef {object} TimelineState
 * @property {number} step index into TASK_STEPS
 * @property {number} progress 0..1 through the step; above 1 while holding
 * @property {boolean} playing
 */

/**
 * Advance the timeline by `elapsed` ms. A step always finishes; only playing moves on to the next.
 * @param {TimelineState} state mutated
 * @param {number} elapsed
 */
export function advanceTimeline(state, elapsed) {
  if (state.progress < 1) {
    state.progress = Math.min(1, state.progress + elapsed / STEP_MS);
  } else if (state.playing) {
    state.progress += elapsed / STEP_MS;
    if (state.progress > 1 + HOLD_MS / STEP_MS) {
      state.step = (state.step + 1) % TASK_STEPS.length;
      state.progress = 0;
    }
  }
}

/**
 * @typedef {object} TaskFrame
 * @property {{ state: "idle" | "run" | "done", barWidth: string }[]} containers
 * @property {"Pending" | "Running" | "Succeeded"} phase
 * @property {string} volumeOpacity
 * @property {string} volumeNote
 * @property {boolean[]} filesShown
 * @property {string} inputBucketFile
 * @property {string} outputBucketFile
 * @property {{ label: string, x: number, y: number } | null} mover the file in transit
 * @property {boolean} inputActive input bucket and wire
 * @property {boolean} outputBucketActive
 * @property {boolean} outputWireActive
 * @property {{ current: boolean, past: boolean, fill: string }[]} segments timeline bar
 */

function containerState(step, index, progress) {
  const runStep = index + 1;
  if (step > runStep) return "done";
  if (step === runStep) return progress < RUN_END ? "run" : "done";
  return "idle";
}

function phaseAt(step, progress) {
  if (step === STEP.SUBMIT) return progress < POD_STARTS_AT ? "Pending" : "Running";
  return step < STEP.CLEAN_UP ? "Running" : "Succeeded";
}

function volumeOpacity(step, progress) {
  if (step === STEP.SUBMIT) {
    return (VOLUME_START_OPACITY + (1 - VOLUME_START_OPACITY) * ease(progress)).toFixed(2);
  }
  if (step === STEP.CLEAN_UP) {
    const opacity =
      progress < VOLUME_FADE_START
        ? 1
        : lerp(
            1,
            VOLUME_END_OPACITY,
            ease(clamp((progress - VOLUME_FADE_START) / VOLUME_FADE_LENGTH)),
          );
    return opacity.toFixed(2);
  }
  return "1";
}

function trip(step, progress, layout) {
  const within = ({ start, end }) => progress > start && progress < end;
  if (step === STEP.STAGE_IN && within(STAGE_IN_TRIP)) {
    const { start, end } = STAGE_IN_TRIP;
    const to = rectCenter(layout.file(0));
    return { label: INPUT_FILE, from: layout.moverFrom, to, t: (progress - start) / (end - start) };
  }
  if (step === STEP.STAGE_OUT && within(STAGE_OUT_TRIP)) {
    const { start, end } = STAGE_OUT_TRIP;
    const from = rectCenter(layout.file(FILES.length - 1));
    return { label: OUTPUT_FILE, from, to: layout.moverTo, t: (progress - start) / (end - start) };
  }
  return null;
}

/**
 * Everything the drawing needs for one moment of the timeline.
 * @param {number} step
 * @param {number} rawProgress may exceed 1 while holding
 * @param {import("./taskLayout.js").TaskLayout} layout
 * @returns {TaskFrame}
 */
export function taskFrame(step, rawProgress, layout) {
  const progress = clamp(rawProgress);

  const containers = CONTAINERS.map((_, index) => {
    const state = containerState(step, index, progress);
    const fullWidth = layout.container(index)[2] - 2 * CONTAINER_PADDING;
    const width =
      state === "run"
        ? fullWidth * ease(clamp(progress / RUN_END))
        : state === "done"
          ? fullWidth
          : 0;
    return { state, barWidth: width.toFixed(1) };
  });

  // file i is written during step i + 1 (stage in, exec-0, exec-1)
  const filesShown = FILE_WRITTEN_AT.map(
    (at, index) => step > index + 1 || (step === index + 1 && progress > at),
  );

  const travel = trip(step, progress, layout);
  let mover = null;
  if (travel) {
    const t = ease(clamp(travel.t));
    const arc = layout.narrow ? 0 : Math.sin(Math.PI * t) * TRIP_ARC;
    mover = {
      label: travel.label,
      x: lerp(travel.from[0], travel.to[0], t),
      y: lerp(travel.from[1], travel.to[1], t) - arc,
    };
  }

  const outputLanded =
    step > STEP.STAGE_OUT || (step === STEP.STAGE_OUT && progress > OUTPUT_LANDS_AT);

  return {
    containers,
    phase: phaseAt(step, progress),
    volumeOpacity: volumeOpacity(step, progress),
    volumeNote:
      step === STEP.CLEAN_UP && progress > VOLUME_DELETED_AT ? "deleted" : layout.volumeText,
    filesShown,
    inputBucketFile: INPUT_FILE,
    outputBucketFile: outputLanded ? OUTPUT_FILE : "",
    mover,
    inputActive: step === STEP.STAGE_IN && progress < STAGE_IN_ACTIVE_UNTIL,
    outputBucketActive: step === STEP.STAGE_OUT && progress > OUTPUT_BUCKET_ACTIVE_FROM,
    outputWireActive: step === STEP.STAGE_OUT && progress > OUTPUT_WIRE_ACTIVE_FROM,
    segments: TASK_STEPS.map((_, index) => ({
      current: index === step,
      past: index < step,
      fill: `scaleX(${index === step ? progress.toFixed(3) : index < step ? 1 : 0})`,
    })),
  };
}
