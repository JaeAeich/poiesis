import { describe, expect, it } from "vitest";
import { createConfig, createIssuer, exampleKey } from "../config.js";
import { fillAllExamples } from "../examples.js";
import { linesToText } from "../file-lines.js";
import { STEP } from "../steps.js";
import { valuesYamlLines, yamlScalar } from "../values-yaml.js";

const valuesYaml = (mutate = () => {}) => {
  const config = createConfig();
  mutate(config);
  return linesToText(valuesYamlLines(config));
};

describe("yamlScalar", () => {
  it.each([
    ["poiesis-db", "poiesis-db"],
    ["https://x.example.org/a", "https://x.example.org/a"],
    ["1password", '"1password"'],
    ["yes", '"yes"'],
    ["Null", '"Null"'],
    ["has space", '"has space"'],
    ["", '""'],
    [3, "3"],
    [false, "false"],
  ])("%j becomes %s", (value, expected) => {
    expect(yamlScalar(value)).toBe(expected);
  });
});

describe("valuesYamlLines", () => {
  it("writes only the required stubs for an untouched form", () => {
    expect(valuesYaml()).toBe(
      [
        "# Poiesis values.yaml (non-default values only)",
        "",
        "database:",
        '  existingSecret: ""  # required',
        "",
        "s3:",
        '  region: ""  # required',
        '  existingSecret: ""  # required',
        "",
        "auth:",
        "  issuers:",
        '    - issuer: ""  # required',
        "      audience: poiesis",
        "      clients: [poiesis-cli]",
        "",
      ].join("\n"),
    );
  });

  it("ends with exactly one newline", () => {
    expect(valuesYaml()).toMatch(/[^\n]\n$/);
  });

  describe("TLS", () => {
    const withUrl = (tlsMode, extra = {}) =>
      valuesYaml((config) =>
        Object.assign(config, { publicUrl: "https://p.example.org/x", tlsMode }, extra),
      );

    it("cert-manager adds the issuer annotation and the default TLS Secret", () => {
      const yaml = withUrl("cert-manager", { clusterIssuer: "letsencrypt" });
      expect(yaml).toContain(
        "    annotations:\n      cert-manager.io/cluster-issuer: letsencrypt\n",
      );
      expect(yaml).toContain("      - secretName: poiesis-tls\n        hosts: [p.example.org]\n");
    });

    it("cert-manager without an issuer flags it as required", () => {
      expect(withUrl("cert-manager")).toContain('cert-manager.io/cluster-issuer: ""  # required');
    });

    it("an existing Secret is named, with no annotation", () => {
      const yaml = withUrl("secret", { tlsSecret: "my-tls" });
      expect(yaml).toContain("      - secretName: my-tls\n");
      expect(yaml).not.toContain("annotations:");
    });

    it("TLS terminated upstream writes no tls block", () => {
      const yaml = withUrl("none");
      expect(yaml).not.toContain("tls:");
      expect(yaml).toContain("      - host: p.example.org\n");
      expect(yaml).toContain("  resource: https://p.example.org/x\n");
    });
  });

  it("IRSA sets s3.roleArn, not service account annotations, and drops the S3 Secret", () => {
    const yaml = valuesYaml((config) => {
      config.s3Credentials = "irsa";
      config.s3RoleArn = "arn:aws:iam::1:role/x";
    });
    expect(yaml).toContain('s3:\n  region: ""  # required\n  roleArn: "arn:aws:iam::1:role/x"\n');
    expect(yaml).not.toContain("serviceAccount:");
    expect(yaml).not.toContain("existingSecret: poiesis-s3");
  });

  it("Google Cloud Storage writes gcs, not s3", () => {
    const yaml = valuesYaml((config) => {
      config.storage = "gcs";
      config.gcsSecret = "gcs-key";
    });
    expect(yaml).toContain("gcs:\n  enabled: true\n  existingSecret: gcs-key\n\n");
    expect(yaml).not.toContain("s3:");
  });

  it("GCS writes a pool provider with workload identity", () => {
    const yaml = valuesYaml((config) => {
      config.storage = "gcs";
      config.gcsCredentials = "identity";
      config.gcsWorkloadIdentityProvider = "//iam.googleapis.com/p";
      config.gcsServiceAccount = "filer@p.iam.gserviceaccount.com";
    });
    expect(yaml).toContain(
      "gcs:\n  enabled: true\n  workloadIdentityProvider: //iam.googleapis.com/p\n" +
        "  serviceAccount: filer@p.iam.gserviceaccount.com\n\n",
    );
    expect(yaml).not.toMatch(/gcs:\n(  .*\n)*  existingSecret/);
    const noAccount = valuesYaml((config) => {
      config.storage = "gcs";
      config.gcsCredentials = "identity";
      config.gcsWorkloadIdentityProvider = "//iam.googleapis.com/p";
    });
    expect(noAccount).toContain("  workloadIdentityProvider: //iam.googleapis.com/p\n\n");
  });

  it("Azure writes the account with a Secret or a workload identity", () => {
    const withSecret = valuesYaml((config) => {
      config.storage = "azure";
      config.azureAccount = "data";
    });
    expect(withSecret).toContain(
      'azure:\n  enabled: true\n  accountName: data\n  existingSecret: ""  # required\n\n',
    );
    const withIdentity = valuesYaml((config) => {
      config.storage = "azure";
      config.azureAccount = "data";
      config.azureCredentials = "identity";
      config.azureClientId = "c-1";
      config.azureTenantId = "t-1";
    });
    expect(withIdentity).toContain("  accountName: data\n  clientId: c-1\n  tenantId: t-1\n\n");
    expect(withIdentity).not.toContain('existingSecret: ""  # required\n\nauth');
  });

  it("marks every example value and only those", () => {
    const config = createConfig();
    fillAllExamples(config);
    config.publicUrl = "https://real.example.org";
    config.exampleKeys.delete("publicUrl");
    const yaml = linesToText(valuesYamlLines(config));
    const marked = yaml.split("\n").filter((line) => line.endsWith("# example, replace"));
    expect(marked).toEqual([
      "      cert-manager.io/cluster-issuer: letsencrypt  # example, replace",
      "  existingSecret: poiesis-db  # example, replace",
      "  region: eu-central-1  # example, replace",
      "  existingSecret: poiesis-s3  # example, replace",
      "    - issuer: https://keycloak.example.org/realms/poiesis  # example, replace",
    ]);
  });

  it("writes each issuer, including gateways with their JWKS URL", () => {
    const yaml = valuesYaml((config) => {
      config.issuers[0].issuer = "https://kc.example.org/realms/poiesis";
      config.issuers.push(
        createIssuer("gateway", { issuer: "https://gw.example.org", jwksUri: "http://gw/jwks" }),
        createIssuer("gateway"),
      );
    });
    expect(yaml).toContain(
      [
        "    - issuer: https://kc.example.org/realms/poiesis",
        "      audience: poiesis",
        "      tokenTypes: [JWT]  # Keycloak access tokens; other issuers default to at+jwt",
        "      clients: [poiesis-cli]",
        "    - issuer: https://gw.example.org",
        "      audience: poiesis",
        "      jwksUri: http://gw/jwks",
        '    - issuer: ""  # required',
        "      audience: poiesis",
        '      jwksUri: ""  # required',
      ].join("\n"),
    );
  });

  it("API keys mint from the first OIDC issuer and carry their overrides", () => {
    const yaml = valuesYaml((config) => {
      config.issuers = [
        createIssuer("gateway", { issuer: "https://gw" }),
        createIssuer("oidc", { issuer: "https://idp", clients: "" }),
      ];
      config.apiKeys = true;
      config.advanced["auth.apiKeys.maxTtl"] = "30d";
    });
    expect(yaml).toContain("      keyMinting: {clients: [poiesis-cli], maxAuthAge: 600}\n");
    expect(yaml.match(/keyMinting/g)).toHaveLength(1);
    expect(yaml).toContain('  apiKeys:\n    enabled: true\n    maxTtl: "30d"\n');
  });

  it("API key overrides are dropped while API keys are off", () => {
    const yaml = valuesYaml((config) => {
      config.advanced["auth.apiKeys.maxTtl"] = "30d";
    });
    expect(yaml).not.toContain("apiKeys");
  });

  it("a decision service writes the authz block", () => {
    const yaml = valuesYaml((config) => {
      config.authzMode = "decision-service";
      config.decisionServiceUrl = "http://opa:8181/eval";
      config.sharing = true;
      config.advanced["authz.maxOwners"] = 50;
    });
    expect(yaml).toContain(
      "\nauthz:\n  decisionService:\n    url: http://opa:8181/eval\n  sharing: true\n  maxOwners: 50\n",
    );
  });

  it("advanced overrides land in their sections, defaults stay out", () => {
    const yaml = valuesYaml((config) => {
      Object.assign(config.advanced, {
        logLevel: "DEBUG",
        "api.replicas": 2,
        "api.pdb.enabled": false,
        "taskpods.persistence.rwx": true,
        "audit.enabled": false,
        "networkPolicy.enabled": true,
        "serviceInfo.environment": "prod",
      });
    });
    expect(yaml).toContain("\nlogLevel: DEBUG\n\napi:\n  replicas: 2\n\n");
    expect(yaml).not.toContain("pdb");
    expect(yaml).toContain("taskpods:\n  persistence:\n    accessModes: [ReadWriteMany]\n");
    expect(yaml).toContain("\naudit:\n  enabled: false\n");
    expect(yaml).toContain("\nnetworkPolicy:\n  enabled: true\n");
    expect(yaml).toMatch(/\nserviceInfo:\n {2}environment: prod\n$/);
  });

  it("tags each line with the step that wrote it", () => {
    const config = createConfig();
    config.publicUrl = "https://p";
    config.userGroup = "/u";
    const lines = valuesYamlLines(config);
    const ownerOf = (text) => lines.find((line) => line.text === text).step;
    expect(ownerOf("  resource: https://p")).toBe(STEP.BASICS);
    expect(ownerOf("database:")).toBe(STEP.DATABASE);
    expect(ownerOf("      requiredClaim: {name: groups, values: [/u]}")).toBe(STEP.AUTHORIZATION);
  });

  it("issuer example markers follow the issuer's position", () => {
    const config = createConfig();
    config.issuers[0].issuer = "https://keycloak.example.org/realms/poiesis";
    config.exampleKeys.add(exampleKey("issuer", 0));
    expect(linesToText(valuesYamlLines(config))).toContain(
      "    - issuer: https://keycloak.example.org/realms/poiesis  # example, replace\n",
    );
  });
});
