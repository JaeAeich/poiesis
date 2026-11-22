import { describe, expect, it } from "vitest";
import { createConfig } from "../config.js";
import { linesToText } from "../file-lines.js";
import { helmInstallCommand, installShLines, secretCount } from "../install-sh.js";

const installSh = (mutate = () => {}) => {
  const config = createConfig();
  mutate(config);
  return linesToText(installShLines(config));
};

describe("installShLines", () => {
  it("creates the namespace, both Secrets and installs with defaults", () => {
    expect(installSh()).toBe(
      [
        "# 1. Secrets. The chart references them; it never creates them.",
        "kubectl create namespace poiesis",
        "",
        "kubectl -n poiesis create secret generic poiesis-db \\",
        "  --from-literal=DATABASE_URL='postgresql://poiesis:…@db:5432/poiesis?sslmode=require'",
        "",
        "kubectl -n poiesis create secret generic poiesis-s3 \\",
        "  --from-literal=AWS_ACCESS_KEY_ID=… \\",
        "  --from-literal=AWS_SECRET_ACCESS_KEY=…",
        "",
        "# 2. Install (from a checkout until the chart is published, #53)",
        "helm install poiesis ./deployment/helm/poiesis \\",
        "  -n poiesis -f values.yaml",
        "",
      ].join("\n"),
    );
  });

  it("uses the chosen names and verify-full with a CA ConfigMap", () => {
    const script = installSh((config) => {
      config.namespace = "lab";
      config.databaseSecret = "pg";
      config.databaseCaConfigMap = "pg-ca";
      config.s3Secret = "keys";
    });
    expect(script).toContain("kubectl -n lab create secret generic pg \\\n");
    expect(script).toContain("?sslmode=verify-full&sslrootcert=/etc/ssl/poiesis/ca.crt'\n");
    expect(script).toContain("kubectl -n lab create secret generic keys \\\n");
    expect(script).toContain("  -n lab -f values.yaml\n");
  });

  it("skips the S3 Secret with workload identity", () => {
    expect(installSh((config) => (config.s3Credentials = "irsa"))).not.toContain(
      "AWS_ACCESS_KEY_ID",
    );
  });

  it("creates the chosen store's Secret", () => {
    const gcs = installSh((config) => (config.storage = "gcs"));
    expect(gcs).toContain(
      "kubectl -n poiesis create secret generic poiesis-gcs \\\n" +
        "  --from-file=GOOGLE_SERVICE_ACCOUNT_KEY=key.json\n",
    );
    expect(gcs).not.toContain("AWS_ACCESS_KEY_ID");
    const azure = installSh((config) => {
      config.storage = "azure";
      config.azureSecret = "blob";
    });
    expect(azure).toContain(
      "kubectl -n poiesis create secret generic blob \\\n" +
        "  --from-literal=AZURE_STORAGE_ACCOUNT_KEY=…\n",
    );
    const identity = installSh((config) => {
      config.storage = "azure";
      config.azureCredentials = "identity";
    });
    expect(identity).not.toContain("AZURE_STORAGE_ACCOUNT_KEY");
    const gcsIdentity = installSh((config) => {
      config.storage = "gcs";
      config.gcsCredentials = "identity";
    });
    expect(gcsIdentity).not.toContain("GOOGLE_SERVICE_ACCOUNT_KEY");
  });

  it("creates a separate task namespace only when it differs", () => {
    expect(installSh((config) => (config.advanced["taskpods.namespace"] = "jobs"))).toContain(
      "kubectl create namespace poiesis\nkubectl create namespace jobs\n",
    );
    expect(installSh((config) => (config.advanced["taskpods.namespace"] = "poiesis"))).not.toMatch(
      /namespace poiesis\nkubectl create namespace/,
    );
  });

  it("falls back to the default namespace when it is cleared", () => {
    expect(installSh((config) => (config.namespace = ""))).toContain(
      "kubectl create namespace poiesis\n",
    );
  });
});

describe("helpers", () => {
  it("helmInstallCommand", () => {
    expect(helmInstallCommand("lab")).toBe(
      "helm install poiesis ./deployment/helm/poiesis -n lab -f values.yaml",
    );
  });

  it("secretCount", () => {
    const config = createConfig();
    expect(secretCount(config)).toBe(2);
    config.s3Credentials = "irsa";
    expect(secretCount(config)).toBe(1);
  });
});
