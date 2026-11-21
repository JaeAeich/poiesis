// Every generator must reproduce, byte for byte, what the original configurator produced.
import { describe, expect, it } from "vitest";
import { explainSpec } from "../explain.js";
import { linesToText } from "../file-lines.js";
import { highlightShellLine, highlightYamlLine } from "../highlight.js";
import { installShLines } from "../install-sh.js";
import { STEPS } from "../steps.js";
import { runTrial } from "../trials.js";
import { exampleEntries, missingFields } from "../validation.js";
import { valuesYamlLines } from "../values-yaml.js";
import legacy from "./fixtures/legacy-outputs.json";
import { SCENARIOS, scenarioConfig } from "./fixtures/scenarios.js";
import { explainToLegacy, tokensToHtml, trialStepToLegacy } from "./helpers.js";

describe.each(Object.keys(SCENARIOS))("scenario %s", (name) => {
  const expected = legacy.scenarios[name];
  const config = scenarioConfig(name);

  it("values.yaml text and step ownership", () => {
    const lines = valuesYamlLines(config);
    expect(linesToText(lines)).toBe(expected.values);
    expect(lines.map((line) => line.step)).toEqual(expected.valuesSteps);
  });

  it("install.sh text and step ownership", () => {
    const lines = installShLines(config);
    expect(linesToText(lines)).toBe(expected.install);
    expect(lines.map((line) => line.step)).toEqual(expected.installSteps);
  });

  it("missing fields and example values", () => {
    expect(
      missingFields(config).map((entry) => [entry.label, entry.step, entry.focusId ?? undefined]),
    ).toEqual(expected.missing.map(([label, step, focusId]) => [label, step, focusId]));
    expect(
      exampleEntries(config).map((entry) => [entry.label, entry.step, entry.focusId, entry.value]),
    ).toEqual(expected.examples);
  });

  it("step summaries", () => {
    expect(STEPS.map((step) => step.summary(config))).toEqual(expected.summaries);
  });

  it("request trials", () => {
    for (const [kind, result] of Object.entries(expected.trials)) {
      const trial = runTrial(config, kind);
      expect(trial.hit).toEqual(result.hit);
      expect(trial.steps.map(trialStepToLegacy)).toEqual(result.steps);
    }
  });

  if (expected.valuesHtml) {
    it("highlighting", () => {
      const values = valuesYamlLines(config).map((line) =>
        tokensToHtml(highlightYamlLine(line.text)),
      );
      const install = installShLines(config).map((line) =>
        tokensToHtml(highlightShellLine(line.text)),
      );
      expect(values).toEqual(expected.valuesHtml);
      expect(install).toEqual(expected.installHtml);
    });
  }

  if (expected.explain) {
    it("how-it-works specs", () => {
      for (const step of STEPS) {
        const spec = JSON.parse(JSON.stringify(explainToLegacy(explainSpec(config, step.id))));
        const legacyId =
          {
            database: "db",
            volumes: "vol",
            authentication: "authn",
            authorization: "authz",
            advanced: "adv",
          }[step.id] ?? step.id;
        expect(spec).toEqual(expected.explain[legacyId]);
      }
    });
  }
});
