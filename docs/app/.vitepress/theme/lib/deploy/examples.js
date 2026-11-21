import { STEP, STEPS, LAST_STEP } from "./steps.js";
import { exampleKey } from "./config.js";

// Values "Use example values" fills in; each stays marked until the user edits it.
export const EXAMPLE_VALUES = Object.freeze({
  publicUrl: "https://poiesis.example.org",
  clusterIssuer: "letsencrypt",
  databaseSecret: "poiesis-db",
  s3Region: "eu-central-1",
  s3Secret: "poiesis-s3",
  s3RoleArn: "arn:aws:iam::123456789012:role/poiesis",
  issuer: "https://keycloak.example.org/realms/poiesis",
  decisionServiceUrl: "http://opa.policy.svc:8181/access/v1/evaluation",
});

/** Fill a field with its example only when the user left it empty. */
function setExample(config, key) {
  if (config[key]) return;
  config[key] = EXAMPLE_VALUES[key];
  config.exampleKeys.add(key);
}

/**
 * Fill the empty required fields of one step with example values.
 * @param {import("./config.js").DeployConfig} config Mutated in place.
 * @param {number} step
 */
export function fillStepExample(config, step) {
  if (step === STEP.BASICS) {
    setExample(config, "publicUrl");
    if (config.tlsMode === "cert-manager") setExample(config, "clusterIssuer");
  }
  if (step === STEP.DATABASE) setExample(config, "databaseSecret");
  if (step === STEP.STORAGE) {
    setExample(config, "s3Region");
    setExample(config, config.s3Credentials === "secret" ? "s3Secret" : "s3RoleArn");
  }
  if (step === STEP.AUTHENTICATION) {
    config.issuers.forEach((issuer, index) => {
      if (issuer.issuer || issuer.type !== "oidc") return;
      issuer.issuer = EXAMPLE_VALUES.issuer;
      config.exampleKeys.add(exampleKey("issuer", index));
    });
  }
  if (step === STEP.AUTHORIZATION && config.authzMode === "decision-service") {
    setExample(config, "decisionServiceUrl");
  }
}

/** Fill every step before Review. */
export function fillAllExamples(config) {
  for (let step = 0; step < LAST_STEP; step++) fillStepExample(config, step);
}

/** Whether a step offers "Use example values". */
export function stepHasExamples(step) {
  return step < LAST_STEP && !STEPS[step].optional;
}
