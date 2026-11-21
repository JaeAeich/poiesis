// A task's life as a sequence diagram, from POST /tasks to COMPLETE.
import { arrow, box, group, node } from "./shapes.js";

const LANE_START_X = 60;
const LANE_PITCH = 107;
const HEADER_WIDTH = 100;
const HEADER_HEIGHT = 34;
const TOP = 64;
const ROW_PITCH = 34;
const BOTTOM_MARGIN = 40;
const STEP_RADIUS = 8;

const ACTORS = [
  ["c", "Client"],
  ["api", "Poiesis API"],
  ["k", "Kubernetes"],
  ["pod", "TaskPod"],
  ["trec", "trec"],
  ["tctl", "TCtl"],
  ["pg", "PostgreSQL"],
];

/**
 * Messages in order: [from, to, label, reply?]. A "note" row spans TCtl and PostgreSQL.
 * @type {([string, string, string, boolean?] | "note")[]}
 */
const MESSAGES = [
  ["c", "api", "POST /tasks"],
  ["api", "api", "validate, assign id"],
  ["api", "pg", "INSERT task (QUEUED)"],
  ["api", "k", "create Job (TaskPod)"],
  ["api", "k", "create PVC, owned by the Job"],
  ["api", "c", "200 {id}", true],
  ["k", "pod", "schedule"],
  ["pod", "trec", "start native sidecar"],
  ["trec", "pg", "state INITIALIZING"],
  ["pod", "pod", "tif → exec-0"],
  ["trec", "pg", "state RUNNING"],
  ["pod", "pod", "exec-1…N → tof"],
  ["trec", "pg", "executor and system logs"],
  ["k", "pod", "phase Succeeded"],
  "note",
  ["tctl", "k", "list Pods, every 5 s"],
  ["tctl", "pg", "state COMPLETE"],
  ["c", "api", "GET /tasks/{id}"],
  ["api", "pg", "SELECT task"],
  ["api", "c", "200 {state}", true],
];

const laneX = Object.fromEntries(ACTORS.map(([id], i) => [id, LANE_START_X + i * LANE_PITCH]));
const height = TOP + MESSAGES.length * ROW_PITCH + BOTTOM_MARGIN;

const lanes = ACTORS.flatMap(([id, label]) => [
  node("line", { class: "lane", x1: laneX[id], y1: TOP - 14, x2: laneX[id], y2: height - 16 }),
  box({ x: laneX[id] - HEADER_WIDTH / 2, y: 10, w: HEADER_WIDTH, h: HEADER_HEIGHT, label }),
]);

const note = (y) =>
  group("note", [
    node("rect", {
      x: laneX.tctl - 52,
      y: y - 15,
      width: laneX.pg - laneX.tctl + 104,
      height: 24,
      rx: 6,
    }),
    node(
      "text",
      { class: "s", x: (laneX.tctl + laneX.pg) / 2, y: y + 1 },
      "sole writer of final states",
    ),
  ]);

function message([from, to, label, reply], y, number) {
  const x = laneX[from];
  let shapes;
  if (from === to) {
    shapes = [
      ...arrow(`M${x} ${y - 6}h34v14h-32`, { variant: "self" }),
      node("text", { class: "lb l", x: x + 42, y: y + 4 }, label),
    ];
  } else {
    // stop just short of the target lane so the arrowhead touches it
    const backoff = laneX[to] > x ? -1 : 1;
    shapes = [
      ...arrow(`M${x} ${y}H${laneX[to] + backoff * 2}`, { variant: reply ? "dash" : "" }),
      node("text", { class: "lb l", x: Math.min(x, laneX[to]) + 14, y: y - 7 }, label),
    ];
  }
  const badge = group("num", [
    node("circle", { cx: x, cy: y, r: STEP_RADIUS }),
    node("text", { x, y: y + 3.5 }, String(number)),
  ]);
  return [...shapes, badge];
}

function rows() {
  let stepNumber = 0;
  return MESSAGES.flatMap((entry, i) => {
    const y = TOP + 20 + i * ROW_PITCH;
    if (entry === "note") return [note(y)];
    stepNumber++;
    return message(entry, y, stepNumber);
  });
}

export default {
  viewBox: `0 0 760 ${height}`,
  label: "Task lifecycle, from POST /tasks to COMPLETE",
  nodes: [...lanes, ...rows()],
};
