import { describe, expect, it } from "vitest";
import { highlightShellLine, highlightYamlLine } from "../highlight.js";
import legacy from "./fixtures/legacy-outputs.json";
import { tokensToHtml } from "./helpers.js";

describe("highlightYamlLine", () => {
  it("marks keys, values and comments", () => {
    expect(highlightYamlLine("  region: eu-central-1")).toEqual([
      { text: "  " },
      { text: "region", className: "k" },
      { text: ": " },
      { text: "eu-central-1", className: "s" },
    ]);
  });

  it("flags example values and their marker", () => {
    expect(highlightYamlLine("  existingSecret: poiesis-db  # example, replace")).toEqual([
      { text: "  " },
      { text: "existingSecret", className: "k" },
      { text: ": " },
      { text: "poiesis-db", className: "s exv" },
      { text: "  # example, replace", className: "ex" },
    ]);
  });

  it("treats a leading # as a comment line", () => {
    expect(highlightYamlLine("# header")).toEqual([{ text: "# header", className: "c" }]);
  });

  it("returns no tokens for an empty line", () => {
    expect(highlightYamlLine("")).toEqual([]);
  });

  it("keeps text after a second trailing comment", () => {
    const tokens = highlightYamlLine("a: b  # one  # two");
    expect(tokens.map((token) => token.text).join("")).toBe("a: b  # one  # two");
  });

  it.each(Object.entries(legacy.manualHighlight))(
    "matches the original markup for %j",
    (line, html) => {
      expect(tokensToHtml(highlightYamlLine(line))).toBe(html);
    },
  );
});

describe("highlightShellLine", () => {
  it("marks the command name", () => {
    expect(highlightShellLine("kubectl create namespace poiesis")).toEqual([
      { text: "kubectl", className: "k" },
      { text: " create namespace poiesis" },
    ]);
  });

  it("marks comments", () => {
    expect(highlightShellLine("# 2. Install")).toEqual([{ text: "# 2. Install", className: "c" }]);
  });

  it("leaves other lines plain", () => {
    expect(highlightShellLine("  --from-literal=A=…")).toEqual([{ text: "  --from-literal=A=…" }]);
  });
});
