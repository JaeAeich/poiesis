// Inside a TaskPod: init containers in order, the trec sidecar, and the shared volume.
import { arrow, box, frame, group, node } from "./shapes.js";

const COLUMN_X = 34;
const COLUMN_WIDTH = 250;
const FIRST_ROW_Y = 78;
const ROW_PITCH = 52;
const ROW_HEIGHT = 40;
const SIDE_X = 306;
const SIDE_WIDTH = 180;
const SIDE_CENTER = SIDE_X + SIDE_WIDTH / 2;

const INIT_CONTAINERS = [
  ["tif", "stage inputs, if any"],
  ["exec-0", "your first command"],
  ["exec-…", "each reads what the last wrote"],
  ["exec-N", "your last command"],
  ["tof", "upload outputs, if any"],
];

const initRows = INIT_CONTAINERS.flatMap(([label, sub], i) => {
  const y = FIRST_ROW_Y + i * ROW_PITCH;
  const row = box({
    x: COLUMN_X,
    y,
    w: COLUMN_WIDTH,
    h: ROW_HEIGHT,
    label,
    sub,
    variant: label.startsWith("exec") ? "hot" : "",
  });
  const isLast = i === INIT_CONTAINERS.length - 1;
  const centerX = COLUMN_X + COLUMN_WIDTH / 2;
  return isLast
    ? [row]
    : [row, ...arrow(`M${centerX} ${y + ROW_HEIGHT}V${y + ROW_HEIGHT + 10}`, { variant: "tiny" })];
});

const sideLine = (y, text, className = "s") =>
  node("text", { class: className, x: SIDE_CENTER, y }, text);

export default {
  viewBox: "0 0 520 404",
  label: "TaskPod layout: init containers in order, a native sidecar, a shared volume",
  nodes: [
    frame({ x: 16, y: 16, w: 488, h: 372, rx: 14, label: "TaskPod", labelAt: [34, 40] }),
    node("text", { class: "gl sm", x: COLUMN_X, y: 66 }, "init containers, in order"),
    ...initRows,
    box({
      x: COLUMN_X,
      y: FIRST_ROW_Y + INIT_CONTAINERS.length * ROW_PITCH + 4,
      w: COLUMN_WIDTH,
      h: 36,
      label: "ack",
      sub: "main container, exits 0",
    }),
    group("bx side tall", [
      node("rect", { x: SIDE_X, y: 78, width: SIDE_WIDTH, height: 222, rx: 8 }),
      sideLine(176, "trec", "t"),
      sideLine(194, "native sidecar"),
      sideLine(210, "restartPolicy: Always"),
      sideLine(232, "marks INITIALIZING,"),
      sideLine(248, "RUNNING, writes logs"),
    ]),
    group("vol", [
      node("rect", { x: SIDE_X, y: 314, width: SIDE_WIDTH, height: 62, rx: 8 }),
      sideLine(340, "volume", "t"),
      sideLine(358, "shared by all but ack"),
    ]),
  ],
};
