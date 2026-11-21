import { describe, expect, it } from "vitest";
import { captionLength, parseCaption } from "../caption.js";

describe("parseCaption", () => {
  it("splits code spans from text", () => {
    expect(parseCaption("The engine sends <code>POST /tasks</code>. Done.")).toEqual([
      { text: "The engine sends ", code: false },
      { text: "POST /tasks", code: true },
      { text: ". Done.", code: false },
    ]);
  });

  it("handles adjacent and edge code spans", () => {
    expect(parseCaption("<code>a</code><code>b</code>")).toEqual([
      { text: "a", code: true },
      { text: "b", code: true },
    ]);
  });

  it("keeps other markup as literal text", () => {
    expect(parseCaption("<b>bold</b>")).toEqual([{ text: "<b>bold</b>", code: false }]);
  });
});

describe("captionLength", () => {
  it("counts characters without tags", () => {
    expect(captionLength("<code>tof</code> uploads")).toBe("tof uploads".length);
  });
});
