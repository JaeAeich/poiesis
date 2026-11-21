// install.sh: the Secrets the chart expects, then helm install.
import { DEFAULT_NAMESPACE } from "./config.js";
import { LINE_OWNER, createLineWriter } from "./file-lines.js";
import { STEP } from "./steps.js";

const CHART_PATH = "./deployment/helm/poiesis";
const DEFAULT_DATABASE_SECRET = "poiesis-db";
const DEFAULT_S3_SECRET = "poiesis-s3";
const SSL_VERIFY_FULL = "sslmode=verify-full&sslrootcert=/etc/ssl/poiesis/ca.crt";
const SSL_REQUIRE = "sslmode=require";

/** @param {import("./config.js").DeployConfig} config */
export function releaseNamespace(config) {
  return config.namespace || DEFAULT_NAMESPACE;
}

/** The one-line install command shown in the review. */
export function helmInstallCommand(namespace) {
  return `helm install poiesis ${CHART_PATH} -n ${namespace} -f values.yaml`;
}

/** Secrets the user creates before installing: the database one, plus S3 keys if used. */
export function secretCount(config) {
  return config.s3Credentials === "secret" ? 2 : 1;
}

/**
 * @param {import("./config.js").DeployConfig} config
 * @returns {import("./file-lines.js").FileLine[]}
 */
export function installShLines(config) {
  const out = createLineWriter();
  const namespace = releaseNamespace(config);
  const taskNamespace = config.advanced["taskpods.namespace"];

  out.add("# 1. Secrets. The chart references them; it never creates them.", LINE_OWNER.NONE);
  out.add(`kubectl create namespace ${namespace}`, LINE_OWNER.NONE);
  if (taskNamespace && taskNamespace !== namespace) {
    out.add(`kubectl create namespace ${taskNamespace}`, STEP.ADVANCED);
  }
  out.blank(LINE_OWNER.NONE);

  const databaseSecret = config.databaseSecret || DEFAULT_DATABASE_SECRET;
  const sslMode = config.databaseCaConfigMap ? SSL_VERIFY_FULL : SSL_REQUIRE;
  out.add(`kubectl -n ${namespace} create secret generic ${databaseSecret} \\`, STEP.DATABASE);
  out.add(
    `  --from-literal=DATABASE_URL='postgresql://poiesis:…@db:5432/poiesis?${sslMode}'`,
    STEP.DATABASE,
  );
  out.blank(STEP.DATABASE);

  if (config.s3Credentials === "secret") {
    const s3Secret = config.s3Secret || DEFAULT_S3_SECRET;
    out.add(`kubectl -n ${namespace} create secret generic ${s3Secret} \\`, STEP.STORAGE);
    out.add("  --from-literal=AWS_ACCESS_KEY_ID=… \\", STEP.STORAGE);
    out.add("  --from-literal=AWS_SECRET_ACCESS_KEY=…", STEP.STORAGE);
    out.blank(STEP.STORAGE);
  }

  out.add("# 2. Install (from a checkout until the chart is published, #53)", LINE_OWNER.NONE);
  out.add(`helm install poiesis ${CHART_PATH} \\`, LINE_OWNER.NONE);
  out.add(`  -n ${namespace} -f values.yaml`, LINE_OWNER.NONE);
  return out.lines;
}
