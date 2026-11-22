// values.yaml: only what differs from the chart defaults.
import { advancedOverrides } from "./advanced.js";
import {
  DEFAULT_AUDIENCE,
  DEFAULT_CLI_CLIENT,
  VOLUME_DEFAULTS,
  exampleKey,
  firstOidcIndex,
  hostOf,
} from "./config.js";
import { LINE_OWNER, createLineWriter } from "./file-lines.js";
import { STEP } from "./steps.js";

const VALUES_HEADER = "# Poiesis values.yaml (non-default values only)";
const EXAMPLE_MARKER = "  # example, replace";
const REQUIRED_PLACEHOLDER = '""  # required';
const DEFAULT_TLS_SECRET = "poiesis-tls";
const KEYCLOAK_TOKEN_TYPES =
  "tokenTypes: [JWT]  # Keycloak access tokens; other issuers default to at+jwt";
const KEY_MINTING_MAX_AUTH_AGE = 600;

const PLAIN_SCALAR = /^[\w./:@-]+$/;
const LEADING_DIGIT = /^\d/;
const YAML_KEYWORD = /^(true|false|null|yes|no|on|off)$/i;

/**
 * A value as a YAML scalar: bare when unambiguous, otherwise a JSON (double-quoted) string.
 * @param {string | number | boolean} value
 */
export function yamlScalar(value) {
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  const isPlain =
    PLAIN_SCALAR.test(value) && !LEADING_DIGIT.test(value) && !YAML_KEYWORD.test(value);
  return isPlain ? value : JSON.stringify(value);
}

/**
 * @param {import("./config.js").DeployConfig} config
 * @returns {import("./file-lines.js").FileLine[]}
 */
export function valuesYamlLines(config) {
  const out = createLineWriter();
  const overrides = advancedOverrides(config);
  const has = (key) => key in overrides;
  const marker = (key) => (config.exampleKeys.has(key) ? EXAMPLE_MARKER : "");
  // A required value: quoted with its example marker, or an empty string flagged as required.
  const requiredValue = (value, key) =>
    value ? yamlScalar(value) + marker(key) : REQUIRED_PLACEHOLDER;

  out.add(VALUES_HEADER, LINE_OWNER.NONE);
  out.blank(LINE_OWNER.NONE);

  if (has("logLevel")) {
    out.add(`logLevel: ${overrides.logLevel}`, STEP.ADVANCED);
    out.blank(STEP.ADVANCED);
  }

  writeApi(out, config, overrides, marker);

  out.add("database:", STEP.DATABASE);
  out.add(
    `  existingSecret: ${requiredValue(config.databaseSecret, "databaseSecret")}`,
    STEP.DATABASE,
  );
  if (config.databaseCaConfigMap) {
    out.add(`  caConfigmap: ${yamlScalar(config.databaseCaConfigMap)}`, STEP.DATABASE);
  }
  out.blank(STEP.DATABASE);

  writeStorage(out, config, marker, requiredValue);
  writeTaskPods(out, config, overrides);
  writeAuth(out, config, overrides, marker, requiredValue);
  writeAuthz(out, config, overrides, requiredValue);

  if (overrides["audit.enabled"] === false) {
    out.blank(STEP.ADVANCED);
    out.add("audit:", STEP.ADVANCED);
    out.add("  enabled: false", STEP.ADVANCED);
  }
  if (overrides["networkPolicy.enabled"]) {
    out.blank(STEP.ADVANCED);
    out.add("networkPolicy:", STEP.ADVANCED);
    out.add("  enabled: true", STEP.ADVANCED);
  }
  const serviceInfo = ["id", "name", "environment"].filter(
    (key) => overrides["serviceInfo." + key],
  );
  if (serviceInfo.length) {
    out.blank(STEP.ADVANCED);
    out.add("serviceInfo:", STEP.ADVANCED);
    for (const key of serviceInfo) {
      out.add(`  ${key}: ${yamlScalar(overrides["serviceInfo." + key])}`, STEP.ADVANCED);
    }
  }
  return out.lines;
}

function writeApi(out, config, overrides, marker) {
  const hasReplicas = "api.replicas" in overrides;
  const hasPdb = "api.pdb.enabled" in overrides;
  if (!config.publicUrl && !hasReplicas && !hasPdb) return;

  out.add("api:", config.publicUrl ? STEP.BASICS : STEP.ADVANCED);
  if (hasReplicas) out.add(`  replicas: ${overrides["api.replicas"]}`, STEP.ADVANCED);
  if (hasPdb) {
    out.add("  pdb:", STEP.ADVANCED);
    out.add(`    enabled: ${overrides["api.pdb.enabled"]}`, STEP.ADVANCED);
  }
  if (config.publicUrl) {
    const host = yamlScalar(hostOf(config.publicUrl));
    const step = STEP.BASICS;
    out.add("  ingress:", step);
    out.add("    enabled: true", step);
    if (config.ingressClass) out.add(`    className: ${yamlScalar(config.ingressClass)}`, step);
    out.add("    hosts:", step);
    out.add(`      - host: ${host}${marker("publicUrl")}`, step);
    out.add("        paths: [{path: /, pathType: Prefix}]", step);
    if (config.tlsMode === "cert-manager") {
      const issuer = config.clusterIssuer
        ? yamlScalar(config.clusterIssuer) + marker("clusterIssuer")
        : REQUIRED_PLACEHOLDER;
      out.add("    annotations:", step);
      out.add(`      cert-manager.io/cluster-issuer: ${issuer}`, step);
    }
    if (config.tlsMode !== "none") {
      const secretName =
        config.tlsMode === "secret" ? config.tlsSecret || DEFAULT_TLS_SECRET : DEFAULT_TLS_SECRET;
      out.add("    tls:", step);
      out.add(`      - secretName: ${yamlScalar(secretName)}`, step);
      out.add(`        hosts: [${host}]`, step);
    }
  }
  out.blank(STEP.BASICS);
}

function writeStorage(out, config, marker, requiredValue) {
  const step = STEP.STORAGE;
  if (config.storage === "gcs") {
    out.add("gcs:", step);
    out.add("  enabled: true", step);
    out.add(`  existingSecret: ${requiredValue(config.gcsSecret, "gcsSecret")}`, step);
  } else if (config.storage === "azure") {
    out.add("azure:", step);
    out.add("  enabled: true", step);
    out.add(`  accountName: ${requiredValue(config.azureAccount, "azureAccount")}`, step);
    if (config.azureCredentials === "secret") {
      out.add(`  existingSecret: ${requiredValue(config.azureSecret, "azureSecret")}`, step);
    } else {
      out.add(`  clientId: ${requiredValue(config.azureClientId, "azureClientId")}`, step);
      out.add(`  tenantId: ${requiredValue(config.azureTenantId, "azureTenantId")}`, step);
    }
  } else {
    writeS3(out, config, marker, requiredValue);
  }
  out.blank(step);
}

function writeS3(out, config, marker, requiredValue) {
  const step = STEP.STORAGE;
  out.add("s3:", step);
  if (config.s3Endpoint) {
    out.add(`  endpoint: ${yamlScalar(config.s3Endpoint)}${marker("s3Endpoint")}`, step);
  }
  out.add(`  region: ${requiredValue(config.s3Region, "s3Region")}`, step);
  if (config.s3Credentials === "secret") {
    out.add(`  existingSecret: ${requiredValue(config.s3Secret, "s3Secret")}`, step);
    return;
  }
  // tif and tof assume the role; role ARNs contain ":" sequences, so they are always quoted.
  const role = config.s3RoleArn
    ? JSON.stringify(config.s3RoleArn) + marker("s3RoleArn")
    : REQUIRED_PLACEHOLDER;
  out.add(`  roleArn: ${role}`, step);
}

function writeTaskPods(out, config, overrides) {
  /** @type {[string, number][]} */
  const persistence = [];
  const step = STEP.VOLUMES;
  if (Number(config.defaultSizeGi) !== VOLUME_DEFAULTS.defaultSizeGi) {
    persistence.push([`    defaultSizeGi: ${Number(config.defaultSizeGi)}`, step]);
  }
  if (Number(config.maxSizeGi) !== VOLUME_DEFAULTS.maxSizeGi) {
    persistence.push([`    maxSizeGi: ${Number(config.maxSizeGi)}`, step]);
  }
  if (config.storageClass) {
    persistence.push([`    storageClass: ${yamlScalar(config.storageClass)}`, step]);
  }
  if (Number(config.retainSeconds) !== VOLUME_DEFAULTS.retainSeconds) {
    persistence.push([`    retainAfterSeconds: ${Number(config.retainSeconds)}`, step]);
  }
  if (overrides["taskpods.persistence.rwx"]) {
    persistence.push(["    accessModes: [ReadWriteMany]", STEP.ADVANCED]);
  }

  const taskPods = [];
  if (overrides["taskpods.namespace"]) {
    taskPods.push(`  namespace: ${yamlScalar(overrides["taskpods.namespace"])}`);
  }
  if (overrides["taskpods.outputGlobFallback"]) taskPods.push("  outputGlobFallback: true");

  if (!persistence.length && !taskPods.length) return;
  out.add("taskpods:", persistence.length ? step : STEP.ADVANCED);
  for (const text of taskPods) out.add(text, STEP.ADVANCED);
  if (persistence.length) {
    out.add("  persistence:", step);
    for (const [text, owner] of persistence) out.add(text, owner);
  }
  out.blank(step);
}

function writeAuth(out, config, overrides, marker, requiredValue) {
  const step = STEP.AUTHENTICATION;
  out.add("auth:", step);
  if (config.publicUrl) {
    out.add(`  resource: ${yamlScalar(config.publicUrl)}${marker("publicUrl")}`, STEP.BASICS);
  }
  out.add("  issuers:", step);

  const firstOidc = firstOidcIndex(config);
  config.issuers.forEach((issuer, index) => {
    out.add(`    - issuer: ${requiredValue(issuer.issuer, exampleKey("issuer", index))}`, step);
    out.add(`      audience: ${yamlScalar(issuer.audience || DEFAULT_AUDIENCE)}`, step);
    if (issuer.type !== "oidc") {
      out.add(
        `      jwksUri: ${issuer.jwksUri ? yamlScalar(issuer.jwksUri) : REQUIRED_PLACEHOLDER}`,
        step,
      );
      return;
    }
    if (/\/realms\//.test(issuer.issuer || "")) out.add(`      ${KEYCLOAK_TOKEN_TYPES}`, step);
    if (issuer.clients) out.add(`      clients: [${issuer.clients}]`, step);
    if (config.userGroup) {
      out.add(
        `      requiredClaim: {name: groups, values: [${config.userGroup}]}`,
        STEP.AUTHORIZATION,
      );
    }
    if (config.adminGroup && config.authzMode === "owner") {
      out.add(`      admin: {name: groups, values: [${config.adminGroup}]}`, STEP.AUTHORIZATION);
    }
    if (config.apiKeys && index === firstOidc) {
      const clients = issuer.clients || DEFAULT_CLI_CLIENT;
      out.add(
        `      keyMinting: {clients: [${clients}], maxAuthAge: ${KEY_MINTING_MAX_AUTH_AGE}}`,
        step,
      );
    }
  });

  if (config.apiKeys) {
    out.add("  apiKeys:", step);
    out.add("    enabled: true", step);
    for (const key of ["defaultTtl", "maxTtl", "maxPerOwner"]) {
      const path = "auth.apiKeys." + key;
      if (path in overrides) out.add(`    ${key}: ${yamlScalar(overrides[path])}`, STEP.ADVANCED);
    }
  }
  if (overrides["auth.swaggerUi.clientId"] && firstOidc >= 0) {
    out.add("  swaggerUi:", STEP.ADVANCED);
    out.add(`    issuer: ${yamlScalar(config.issuers[firstOidc].issuer || "")}`, STEP.ADVANCED);
    out.add(`    clientId: ${yamlScalar(overrides["auth.swaggerUi.clientId"])}`, STEP.ADVANCED);
  }
}

function writeAuthz(out, config, overrides, requiredValue) {
  const usesService = config.authzMode === "decision-service";
  const adminRead = overrides["authz.adminRead"];
  if (!usesService && !adminRead) return;

  const step = STEP.AUTHORIZATION;
  out.blank(step);
  out.add("authz:", step);
  if (usesService) {
    out.add("  decisionService:", step);
    out.add(`    url: ${requiredValue(config.decisionServiceUrl, "decisionServiceUrl")}`, step);
    if (config.sharing) out.add("  sharing: true", step);
    if ("authz.maxOwners" in overrides) {
      out.add(`  maxOwners: ${overrides["authz.maxOwners"]}`, STEP.ADVANCED);
    }
  }
  if (adminRead) out.add("  adminRead: true", STEP.ADVANCED);
}
