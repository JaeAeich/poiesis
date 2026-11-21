import { describe, expect, it } from "vitest";
import {
  clipToBox,
  edgeOnHop,
  hopHoldMs,
  layoutFlow,
  puckPosition,
  puckWidth,
} from "../flowGeometry.js";

const spec = {
  nodes: {
    a: { x: 0, y: 0, label: "A" },
    b: { x: 300, y: 0, w: 100, label: "B" },
    c: { x: 0, y: 150, label: "C" },
  },
  edges: [
    ["a", "b"],
    ["a", "c"],
  ],
  hops: [{ f: "a", t: "b", label: "go", cap: "x" }],
};

describe("layoutFlow", () => {
  it("keeps the design canvas for narrow hosts", () => {
    const layout = layoutFlow(spec, false);
    expect(layout).toMatchObject({ width: 420, height: 250 });
    expect(layout.boxes.a).toEqual({ x: 0, y: 0, w: 118, h: 44 });
  });

  it("spreads columns on wide hosts without stretching boxes", () => {
    const { width, boxes } = layoutFlow(spec, true);
    const scale = 600 / 420;
    expect(width).toBe(600);
    expect(boxes.b.w).toBe(100);
    expect(boxes.b.x).toBeCloseTo(300 * scale + (100 * (scale - 1)) / 2);
  });

  it("clips edges to the box borders", () => {
    const { edges } = layoutFlow(spec, false);
    expect(edges[0].start).toEqual([118, 22]);
    expect(edges[0].end).toEqual([300, 22]);
    expect(edges[1].start).toEqual([59, 44]);
  });
});

describe("clipToBox", () => {
  it("leaves through the top or bottom on steep lines", () => {
    const from = { x: 0, y: 0, w: 100, h: 40 };
    expect(clipToBox(from, { x: 0, y: 200, w: 100, h: 40 })).toEqual([50, 40]);
  });
});

describe("puck", () => {
  it("lifts above horizontal hops, or below them near the top", () => {
    const { boxes } = layoutFlow(spec, false);
    const [, y] = puckPosition(boxes, spec.hops[0], 0.5);
    expect(y).toBe(22 + 34);
    const lowered = { ...boxes, a: { ...boxes.a, y: 100 }, b: { ...boxes.b, y: 100 } };
    expect(puckPosition(lowered, spec.hops[0], 0.5)[1]).toBe(122 - 34);
  });

  it("sizes to the label with a minimum", () => {
    expect(puckWidth("ok")).toBe(44);
    expect(puckWidth("disk_gb: 500")).toBeCloseTo(12 * 6.7 + 18);
  });

  it("holds longer captions longer", () => {
    expect(hopHoldMs({ cap: "" })).toBe(1200);
    expect(hopHoldMs({ cap: "<code>abc</code>" })).toBe(1320);
  });

  it("matches edges in either direction", () => {
    expect(edgeOnHop({ from: "b", to: "a" }, spec.hops[0])).toBe(true);
    expect(edgeOnHop({ from: "a", to: "c" }, spec.hops[0])).toBe(false);
  });
});
