// install.sh: the Secrets the chart expects, then helm install.
import { DEFAULT_NAMESPACE, storageSecret } from "./config.js";
import { LINE_OWNER, createLineWriter } from "./file-lines.js";
import { STEP } from "./steps.js";

const CHART_PATH = "./deployment/helm/poiesis";
const DEFAULT_DATABASE_SECRET = "poiesis-db";
// Per store: the Secret's default name and the kubectl arguments that fill it.
const STORAGE_SECRETS = {
  s3: {
    name: "poiesis-s3",
    args: ["--from-literal=AWS_ACCESS_KEY_ID=…", "--from-literal=AWS_SECRET_ACCESS_KEY=…"],
  },
  gcs: { name: "poiesis-gcs", args: ["--from-file=GOOGLE_SERVICE_ACCOUNT_KEY=key.json"] },
  azure: { name: "poiesis-azure", args: ["--from-literal=AZURE_STORAGE_ACCOUNT_KEY=…"] },
};
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

/** Secrets the user creates before installing: the database one, plus storage keys if used. */
export function secretCount(config) {
  return storageSecret(config) ? 2 : 1;
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

  const secret = storageSecret(config);
  if (secret) {
    const { name, args } = STORAGE_SECRETS[config.storage];
    out.add(
      `kubectl -n ${namespace} create secret generic ${secret.name || name} \\`,
      STEP.STORAGE,
    );
    args.forEach((arg, index) => {
      out.add(`  ${arg}${index < args.length - 1 ? " \\" : ""}`, STEP.STORAGE);
    });
    out.blank(STEP.STORAGE);
  }

  out.add("# 2. Install (from a checkout until the chart is published, #53)", LINE_OWNER.NONE);
  out.add(`helm install poiesis ${CHART_PATH} \\`, LINE_OWNER.NONE);
  out.add(`  -n ${namespace} -f values.yaml`, LINE_OWNER.NONE);
  return out.lines;
}
