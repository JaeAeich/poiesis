import { STEP } from "./steps.js";

/**
 * A row in the review that sends the user back to a field.
 * @typedef {object} ReviewTarget
 * @property {string} label
 * @property {number} step
 * @property {string | null} focusId Wrapper id to scroll to and flash, if any.
 */

/**
 * Required values that are still empty, in review order.
 * @param {import("./config.js").DeployConfig} config
 * @returns {ReviewTarget[]}
 */
export function missingFields(config) {
  /** @type {[boolean, string, number, string | null][]} */
  const checks = [
    [!config.publicUrl, "Public URL", STEP.BASICS, "w-url"],
    [!config.databaseSecret, "Database Secret", STEP.DATABASE, "w-dbSecret"],
    ...storageChecks(config),
    [config.tlsMode === "secret" && !config.tlsSecret, "TLS Secret", STEP.BASICS, "w-tlsSecret"],
    [
      config.tlsMode === "cert-manager" && !config.clusterIssuer,
      "ClusterIssuer",
      STEP.BASICS,
      "w-cmIssuer",
    ],
    [!config.issuers.some((issuer) => issuer.issuer), "An issuer URL", STEP.AUTHENTICATION, null],
    [
      config.authzMode === "decision-service" && !config.decisionServiceUrl,
      "Decision service URL",
      STEP.AUTHORIZATION,
      "w-pdp",
    ],
  ];
  return checks
    .filter(([isMissing]) => isMissing)
    .map(([, label, step, focusId]) => ({ label, step, focusId }));
}

/** @returns {[boolean, string, number, string][]} */
function storageChecks(config) {
  const step = STEP.STORAGE;
  if (config.storage === "gcs") {
    const withSecret = config.gcsCredentials === "secret";
    return [
      [withSecret && !config.gcsSecret, "GCS Secret", step, "w-gcsSecret"],
      [!withSecret && !config.gcsWorkloadIdentityProvider, "Pool provider", step, "w-gcsProvider"],
    ];
  }
  if (config.storage === "azure") {
    const withSecret = config.azureCredentials === "secret";
    return [
      [!config.azureAccount, "Storage account", step, "w-azureAccount"],
      [withSecret && !config.azureSecret, "Azure Secret", step, "w-azureSecret"],
      [!withSecret && !config.azureClientId, "Client ID", step, "w-azureClientId"],
      [!withSecret && !config.azureTenantId, "Tenant ID", step, "w-azureTenantId"],
    ];
  }
  const withSecret = config.s3Credentials === "secret";
  return [
    [!config.s3Region, "S3 region", step, "w-s3Region"],
    [withSecret && !config.s3Secret, "S3 Secret", step, "w-s3Secret"],
    [!withSecret && !config.s3RoleArn, "IAM role", step, "w-s3Role"],
  ];
}

// Where each example-valued field lives, for the "Example values to replace" list.
const EXAMPLE_TARGETS = {
  clusterIssuer: { label: "ClusterIssuer", step: STEP.BASICS, focusId: "w-cmIssuer" },
  s3RoleArn: { label: "IAM role", step: STEP.STORAGE, focusId: "w-s3Role" },
  publicUrl: { label: "Public URL", step: STEP.BASICS, focusId: "w-url" },
  databaseSecret: { label: "Database Secret", step: STEP.DATABASE, focusId: "w-dbSecret" },
  s3Endpoint: { label: "S3 endpoint", step: STEP.STORAGE, focusId: "w-s3Endpoint" },
  s3Region: { label: "S3 region", step: STEP.STORAGE, focusId: "w-s3Region" },
  s3Secret: { label: "S3 Secret", step: STEP.STORAGE, focusId: "w-s3Secret" },
  gcsSecret: { label: "GCS Secret", step: STEP.STORAGE, focusId: "w-gcsSecret" },
  gcsWorkloadIdentityProvider: {
    label: "Pool provider",
    step: STEP.STORAGE,
    focusId: "w-gcsProvider",
  },
  azureAccount: { label: "Storage account", step: STEP.STORAGE, focusId: "w-azureAccount" },
  azureSecret: { label: "Azure Secret", step: STEP.STORAGE, focusId: "w-azureSecret" },
  azureClientId: { label: "Client ID", step: STEP.STORAGE, focusId: "w-azureClientId" },
  azureTenantId: { label: "Tenant ID", step: STEP.STORAGE, focusId: "w-azureTenantId" },
  decisionServiceUrl: { label: "Decision service URL", step: STEP.AUTHORIZATION, focusId: "w-pdp" },
};

const ISSUER_EXAMPLE_KEY = /^issuers\.(\d+)\./;

/**
 * Fields still holding an example value, in the order they were filled.
 * @param {import("./config.js").DeployConfig} config
 * @returns {(ReviewTarget & { value: string | undefined })[]}
 */
export function exampleEntries(config) {
  return [...config.exampleKeys]
    .map((key) => {
      if (EXAMPLE_TARGETS[key]) return { ...EXAMPLE_TARGETS[key], value: config[key] };
      const issuerMatch = ISSUER_EXAMPLE_KEY.exec(key);
      if (!issuerMatch) return null;
      const issuer = config.issuers[Number(issuerMatch[1])];
      return {
        label: "Issuer URL",
        step: STEP.AUTHENTICATION,
        focusId: null,
        value: issuer ? issuer.issuer : undefined,
      };
    })
    .filter(Boolean);
}
