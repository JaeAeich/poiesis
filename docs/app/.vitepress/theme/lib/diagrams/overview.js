// Poiesis at a glance: the API, one TaskPod per task, TCtl and Postgres.
import { arrow, box, database, frame } from "./shapes.js";

const POD_ROW_Y = 56;
const POD_BOX_HEIGHT = 40;

export default {
  viewBox: "0 0 760 320",
  label: "Poiesis overview: the API, one TaskPod per task, TCtl and Postgres",
  nodes: [
    box({ x: 10, y: 62, w: 110, h: 40, label: "TES client", variant: "pill", rx: 20 }),
    box({ x: 170, y: 62, w: 130, h: 40, label: "Poiesis API" }),
    frame({
      x: 360,
      y: 16,
      w: 390,
      h: 172,
      rx: 12,
      label: "TaskPod · one per task",
      labelAt: [376, 38],
    }),
    box({ x: 376, y: POD_ROW_Y, w: 78, h: POD_BOX_HEIGHT, label: "tif", sub: "stage in" }),
    box({
      x: 464,
      y: POD_ROW_Y,
      w: 104,
      h: POD_BOX_HEIGHT,
      label: "exec-0…N",
      sub: "your images",
      variant: "hot",
    }),
    box({ x: 578, y: POD_ROW_Y, w: 72, h: POD_BOX_HEIGHT, label: "tof", sub: "stage out" }),
    box({ x: 660, y: POD_ROW_Y, w: 74, h: POD_BOX_HEIGHT, label: "ack", sub: "main" }),
    ...arrow("M454 76H462", { variant: "tiny" }),
    ...arrow("M568 76H576", { variant: "tiny" }),
    ...arrow("M650 76H658", { variant: "tiny" }),
    box({
      x: 376,
      y: 126,
      w: 358,
      h: 44,
      label: "trec · native sidecar",
      sub: "marks RUNNING, writes logs as the Pod runs",
      variant: "side",
    }),
    database({ x: 175, y: 236, w: 120, h: 64, label: "PostgreSQL" }),
    box({ x: 600, y: 262, w: 150, h: 40, label: "TCtl", sub: "leader-elected" }),
    ...arrow("M120 82H168", { label: "HTTP", at: [144, 74] }),
    ...arrow("M300 82H358", { label: "submits Job", at: [329, 74] }),
    ...arrow("M235 102V234", { label: "reads / writes", at: [241, 172] }),
    ...arrow("M440 170C440 228 350 258 297 262", { label: "RUNNING + logs", at: [400, 236] }),
    ...arrow("M675 262V190", { label: "polls Pods", at: [681, 230] }),
    ...arrow("M600 284H297", { label: "terminal state", at: [450, 300] }),
  ],
};
