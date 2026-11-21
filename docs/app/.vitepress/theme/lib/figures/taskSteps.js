// What the task figure shows: the steps of one task, its containers and the files they pass on.

/**
 * @typedef {object} TaskStep
 * @property {string} label timeline label
 * @property {string} caption may mark identifiers with <code>
 */

/** @type {TaskStep[]} */
export const TASK_STEPS = [
  {
    label: "Submit",
    caption:
      "The engine sends <code>POST /tasks</code>. Poiesis stores it as <code>QUEUED</code> and creates one Pod and a volume of the size it asked for. <code>trec</code> starts first and marks it <code>RUNNING</code>.",
  },
  {
    label: "Stage in",
    caption: "<code>tif</code> copies the inputs from object storage onto the volume.",
  },
  { label: "exec-0", caption: "Executors run in order, in your image, with your command." },
  { label: "exec-1", caption: "Each executor reads what the one before it wrote." },
  { label: "Stage out", caption: "<code>tof</code> uploads the outputs." },
  {
    label: "Clean up",
    caption:
      "The Pod succeeds and <code>tctl</code> writes <code>COMPLETE</code>. After <code>retainAfterSeconds</code> the Job and volume are deleted.",
  },
];

/** Index of each step in TASK_STEPS; container `i` runs during step `i + 1`. */
export const STEP = { SUBMIT: 0, STAGE_IN: 1, EXEC_0: 2, EXEC_1: 3, STAGE_OUT: 4, CLEAN_UP: 5 };

/** The Pod's containers in run order: name and what it does. */
export const CONTAINERS = [
  { name: "tif", role: "stage in" },
  { name: "exec-0", role: "bwa mem" },
  { name: "exec-1", role: "samtools" },
  { name: "tof", role: "stage out" },
];

/** Files on the volume, written by stage in, exec-0 and exec-1 in turn. */
export const FILES = ["reads.fq", "aligned.sam", "sorted.bam"];

/** The input and output files carried between the buckets and the volume. */
export const INPUT_FILE = FILES[0];
export const OUTPUT_FILE = FILES[2];

/** Pod phase shown on the badge, and the TES state it maps to. */
export const PHASE_STATE = { Pending: "QUEUED", Running: "RUNNING", Succeeded: "COMPLETE" };

export const POD_NAME = "pod/task-7f3a";
