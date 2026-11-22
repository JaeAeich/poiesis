import { describe, expect, it } from "vitest";
import { createConfig, createIssuer, exampleKey } from "../config.js";
import { fillAllExamples } from "../examples.js";
import { STEP } from "../steps.js";
import { exampleEntries, missingFields } from "../validation.js";

const labels = (config) => missingFields(config).map((entry) => entry.label);

describe("missingFields", () => {
  it("lists every required value of an untouched form, in review order", () => {
    expect(missingFields(createConfig())).toEqual([
      { label: "Public URL", step: STEP.BASICS, focusId: "w-url" },
      { label: "Database Secret", step: STEP.DATABASE, focusId: "w-dbSecret" },
      { label: "S3 region", step: STEP.STORAGE, focusId: "w-s3Region" },
      { label: "S3 Secret", step: STEP.STORAGE, focusId: "w-s3Secret" },
      { label: "ClusterIssuer", step: STEP.BASICS, focusId: "w-cmIssuer" },
      { label: "An issuer URL", step: STEP.AUTHENTICATION, focusId: null },
    ]);
  });

  it("asks for the chosen store's values only", () => {
    const config = createConfig();
    config.storage = "gcs";
    expect(labels(config)).toContain("GCS Secret");
    expect(labels(config)).not.toContain("S3 region");
    config.storage = "azure";
    expect(labels(config)).toEqual(expect.arrayContaining(["Storage account", "Azure Secret"]));
    config.azureCredentials = "identity";
    expect(labels(config)).toEqual(expect.arrayContaining(["Client ID", "Tenant ID"]));
    expect(labels(config)).not.toContain("Azure Secret");
    fillAllExamples(config);
    expect(labels(config)).toEqual([]);
  });

  it("follows the chosen modes", () => {
    const config = createConfig();
    config.tlsMode = "secret";
    config.s3Credentials = "irsa";
    config.authzMode = "decision-service";
    expect(labels(config)).toEqual([
      "Public URL",
      "Database Secret",
      "S3 region",
      "IAM role",
      "TLS Secret",
      "An issuer URL",
      "Decision service URL",
    ]);
  });

  it("is satisfied by any issuer with a URL", () => {
    const config = createConfig();
    config.issuers.push(createIssuer("gateway", { issuer: "https://gw" }));
    expect(labels(config)).not.toContain("An issuer URL");
  });

  it("is empty once every step has example values", () => {
    const config = createConfig();
    config.tlsMode = "none";
    fillAllExamples(config);
    expect(missingFields(config)).toEqual([]);
  });
});

describe("exampleEntries", () => {
  it("lists example values in the order they were filled", () => {
    const config = createConfig();
    fillAllExamples(config);
    expect(exampleEntries(config).map((entry) => [entry.label, entry.value])).toEqual([
      ["Public URL", "https://poiesis.example.org"],
      ["ClusterIssuer", "letsencrypt"],
      ["Database Secret", "poiesis-db"],
      ["S3 region", "eu-central-1"],
      ["S3 Secret", "poiesis-s3"],
      ["Issuer URL", "https://keycloak.example.org/realms/poiesis"],
    ]);
  });

  it("drops a value once the user edits it", () => {
    const config = createConfig();
    fillAllExamples(config);
    config.exampleKeys.delete("databaseSecret");
    config.exampleKeys.delete(exampleKey("issuer", 0));
    expect(exampleEntries(config).map((entry) => entry.label)).toEqual([
      "Public URL",
      "ClusterIssuer",
      "S3 region",
      "S3 Secret",
    ]);
  });

  it("points issuer examples at the authentication step", () => {
    const config = createConfig();
    fillAllExamples(config);
    expect(exampleEntries(config).at(-1)).toEqual({
      label: "Issuer URL",
      step: STEP.AUTHENTICATION,
      focusId: null,
      value: "https://keycloak.example.org/realms/poiesis",
    });
  });
});
