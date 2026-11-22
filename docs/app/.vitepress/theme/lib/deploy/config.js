// The configurator's inputs: everything the values.yaml and install.sh generators read.

/** @typedef {"cert-manager" | "secret" | "none"} TlsMode */
/** @typedef {"s3" | "gcs" | "azure"} StorageProvider */
/** @typedef {"secret" | "irsa"} S3Credentials */
/** @typedef {"secret" | "identity"} AzureCredentials */
/** @typedef {"owner" | "decision-service"} AuthzMode */
/** @typedef {"oidc" | "gateway"} IssuerType */

/**
 * One trusted token issuer in the authentication chain.
 * @typedef {object} Issuer
 * @property {number} id Stable identity for list rendering; never written to a file.
 * @property {IssuerType} type
 * @property {string} issuer
 * @property {string} audience
 * @property {string} clients Comma-separated OIDC client ids.
 * @property {string} jwksUri Gateway signing keys; unused for OIDC.
 */

/**
 * @typedef {object} DeployConfig
 * @property {string} publicUrl
 * @property {string} namespace
 * @property {string} ingressClass
 * @property {TlsMode} tlsMode
 * @property {string} clusterIssuer
 * @property {string} tlsSecret
 * @property {string} databaseSecret
 * @property {string} databaseCaConfigMap
 * @property {StorageProvider} storage
 * @property {string} s3Endpoint
 * @property {string} s3Region
 * @property {S3Credentials} s3Credentials
 * @property {string} s3Secret
 * @property {string} s3RoleArn
 * @property {string} gcsSecret
 * @property {string} azureAccount
 * @property {AzureCredentials} azureCredentials
 * @property {string} azureSecret
 * @property {string} azureClientId
 * @property {string} azureTenantId
 * @property {number | string} defaultSizeGi Raw input text once edited.
 * @property {number | string} maxSizeGi
 * @property {string} storageClass
 * @property {number | string} retainSeconds
 * @property {Issuer[]} issuers
 * @property {boolean} apiKeys
 * @property {AuthzMode} authzMode
 * @property {string} userGroup
 * @property {string} adminGroup
 * @property {string} decisionServiceUrl
 * @property {boolean} sharing
 * @property {Record<string, string | number | boolean>} advanced Overrides keyed by chart path.
 * @property {Set<string>} exampleKeys Fields still holding an example value (see exampleKey).
 */

export const TLS_MODES = /** @type {const} */ ([
  ["cert-manager", "cert-manager"],
  ["secret", "Existing Secret"],
  ["none", "Terminated upstream"],
]);

export const S3_CREDENTIAL_MODES = /** @type {const} */ ([
  ["secret", "Access key Secret"],
  ["irsa", "Workload identity"],
]);

export const AZURE_CREDENTIAL_MODES = /** @type {const} */ ([
  ["secret", "Account key Secret"],
  ["identity", "Workload identity"],
]);

export const AUTHZ_MODES = /** @type {const} */ ([
  ["owner", "Owner only"],
  ["decision-service", "Decision service"],
]);

// Chart defaults for task volumes; values equal to these are left out of values.yaml.
export const VOLUME_DEFAULTS = Object.freeze({
  defaultSizeGi: 10,
  maxSizeGi: 100,
  retainSeconds: 3600,
});

export const DEFAULT_NAMESPACE = "poiesis";
export const DEFAULT_AUDIENCE = "poiesis";
export const DEFAULT_CLI_CLIENT = "poiesis-cli";

let nextIssuerId = 1;

/**
 * @param {IssuerType} type
 * @param {Partial<Issuer>} [overrides]
 * @returns {Issuer}
 */
export function createIssuer(type, overrides = {}) {
  return {
    id: nextIssuerId++,
    type,
    issuer: "",
    audience: DEFAULT_AUDIENCE,
    clients: type === "oidc" ? DEFAULT_CLI_CLIENT : "",
    jwksUri: "",
    ...overrides,
  };
}

/** @returns {DeployConfig} */
export function createConfig() {
  return {
    publicUrl: "",
    namespace: DEFAULT_NAMESPACE,
    ingressClass: "",
    tlsMode: "cert-manager",
    clusterIssuer: "",
    tlsSecret: "",
    databaseSecret: "",
    databaseCaConfigMap: "",
    storage: "s3",
    s3Endpoint: "",
    s3Region: "",
    s3Credentials: "secret",
    s3Secret: "",
    s3RoleArn: "",
    gcsSecret: "",
    azureAccount: "",
    azureCredentials: "secret",
    azureSecret: "",
    azureClientId: "",
    azureTenantId: "",
    defaultSizeGi: VOLUME_DEFAULTS.defaultSizeGi,
    maxSizeGi: VOLUME_DEFAULTS.maxSizeGi,
    storageClass: "",
    retainSeconds: VOLUME_DEFAULTS.retainSeconds,
    issuers: [createIssuer("oidc")],
    apiKeys: false,
    authzMode: "owner",
    userGroup: "",
    adminGroup: "",
    decisionServiceUrl: "",
    sharing: false,
    advanced: {},
    exampleKeys: new Set(),
  };
}

/**
 * Key under which a field's "example value" marker is stored in exampleKeys.
 * Issuer fields are keyed by position, so the marker follows the slot, not the issuer.
 * @param {string} field Config key, or an issuer field when index is given.
 * @param {number} [index] Issuer position.
 */
export function exampleKey(field, index) {
  return index === undefined ? field : `issuers.${index}.${field}`;
}

/** Host part of a URL, as the ingress needs it. */
export function hostOf(url) {
  return url.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
}

/** URL without its scheme, for compact labels. */
export function withoutScheme(url) {
  return url.replace(/^https?:\/\//, "");
}

/** First OIDC issuer's position, or -1. */
export function firstOidcIndex(config) {
  return config.issuers.findIndex((issuer) => issuer.type === "oidc");
}

/**
 * Name of the Secret holding the chosen store's credentials, or null with workload identity.
 * @param {DeployConfig} config
 * @returns {{ name: string, key: string } | null} `key` is the config key of the name field.
 */
export function storageSecret(config) {
  if (config.storage === "gcs") return { name: config.gcsSecret, key: "gcsSecret" };
  if (config.storage === "azure") {
    return config.azureCredentials === "secret"
      ? { name: config.azureSecret, key: "azureSecret" }
      : null;
  }
  return config.s3Credentials === "secret" ? { name: config.s3Secret, key: "s3Secret" } : null;
}
