// Input sets whose outputs were captured from the original configurator (legacy-outputs.json).
import { createConfig, createIssuer } from "../../config.js";
import { fillAllExamples, fillStepExample } from "../../examples.js";
import { STEP } from "../../steps.js";

/** @type {Record<string, (config: import("../../config.js").DeployConfig) => void>} */
export const SCENARIOS = {
  defaults() {},
  allExamples(config) {
    fillAllExamples(config);
  },
  allExamplesIrsaDecisionService(config) {
    config.s3Credentials = "irsa";
    config.authzMode = "decision-service";
    config.tlsMode = "secret";
    fillAllExamples(config);
  },
  basicsExampleOnly(config) {
    fillStepExample(config, STEP.BASICS);
  },
  tlsSecret(config) {
    config.publicUrl = "https://poiesis.lab.example.org/api/v1";
    config.tlsMode = "secret";
    config.tlsSecret = "lab-tls";
    config.ingressClass = "nginx";
    config.namespace = "lab";
  },
  tlsSecretEmpty(config) {
    config.publicUrl = "http://p.example.org";
    config.tlsMode = "secret";
  },
  tlsNone(config) {
    config.publicUrl = "https://p.example.org";
    config.tlsMode = "none";
    config.ingressClass = "traefik internal";
  },
  certManagerSet(config) {
    config.publicUrl = "https://p.example.org";
    config.clusterIssuer = "letsencrypt-prod";
  },
  irsaRole(config) {
    config.s3Credentials = "irsa";
    config.s3RoleArn = "arn:aws:iam::999:role/x";
    config.s3Endpoint = "https://minio.local:9000";
    config.s3Region = "us-east-1";
    config.databaseSecret = "pg";
    config.databaseCaConfigMap = "pg-ca";
  },
  irsaRoleMissing(config) {
    config.s3Credentials = "irsa";
  },
  quotingEdgeCases(config) {
    config.databaseSecret = "1password";
    config.s3Region = "yes";
    config.s3Secret = "has space";
    config.storageClass = "null";
    config.databaseCaConfigMap = 'quo"te';
  },
  volumes(config) {
    config.defaultSizeGi = "20";
    config.maxSizeGi = "1.50";
    config.storageClass = "fast-ssd";
    config.retainSeconds = "60";
  },
  volumesEmptyInputs(config) {
    config.defaultSizeGi = "";
    config.maxSizeGi = "100";
    config.retainSeconds = "3600";
  },
  issuersWithGateway(config) {
    config.issuers[0].issuer = "https://kc.example.org/realms/poiesis";
    config.issuers[0].clients = "cli,web";
    config.issuers.push(
      createIssuer("gateway", {
        issuer: "https://gw.example.org",
        audience: "",
        jwksUri: "http://gw/jwks",
      }),
      createIssuer("gateway"),
      createIssuer("oidc", { issuer: "https://login.example.com", clients: "" }),
    );
    config.userGroup = "/users";
    config.adminGroup = "/admins";
  },
  gatewayFirstWithApiKeys(config) {
    config.issuers = [
      createIssuer("gateway", { issuer: "https://gw.example.org" }),
      createIssuer("oidc", { issuer: "https://idp.example.org", clients: "" }),
      createIssuer("oidc", { issuer: "https://idp2.example.org" }),
    ];
    config.apiKeys = true;
  },
  apiKeysWithOverrides(config) {
    config.issuers[0].issuer = "https://idp.example.org";
    config.apiKeys = true;
    config.advanced["auth.apiKeys.defaultTtl"] = "1d";
    config.advanced["auth.apiKeys.maxTtl"] = "90d";
    config.advanced["auth.apiKeys.maxPerOwner"] = 5;
    config.advanced["auth.swaggerUi.clientId"] = "poiesis-swagger";
  },
  apiKeysHiddenOverrides(config) {
    config.advanced["auth.apiKeys.defaultTtl"] = "1d";
    config.advanced["auth.swaggerUi.clientId"] = "sw";
  },
  decisionService(config) {
    config.authzMode = "decision-service";
    config.decisionServiceUrl = "http://opa.policy.svc:8181/access/v1/evaluation";
    config.sharing = true;
    config.adminGroup = "/admins";
    config.advanced["authz.maxOwners"] = 50;
    config.advanced["authz.adminRead"] = true;
  },
  decisionServiceMissing(config) {
    config.authzMode = "decision-service";
  },
  ownerAdminRead(config) {
    config.adminGroup = "/admins";
    config.advanced["authz.adminRead"] = true;
  },
  advancedOverrides(config) {
    Object.assign(config.advanced, {
      "serviceInfo.id": "org.example.poiesis",
      "serviceInfo.name": "Poiesis Lab",
      "serviceInfo.environment": "prod",
      "api.replicas": 3,
      "api.pdb.enabled": true,
      logLevel: "DEBUG",
      "taskpods.namespace": "tasks",
      "taskpods.outputGlobFallback": true,
      "taskpods.persistence.rwx": true,
      "networkPolicy.enabled": true,
      "audit.enabled": false,
    });
  },
  advancedOnlyRwx(config) {
    config.advanced["taskpods.persistence.rwx"] = true;
    config.advanced["api.replicas"] = 1;
  },
  advancedTaskNamespaceSame(config) {
    config.namespace = "work";
    config.advanced["taskpods.namespace"] = "work";
    config.advanced["api.pdb.enabled"] = false;
  },
  editedExamples(config) {
    fillAllExamples(config);
    config.publicUrl = "https://real.example.org";
    config.exampleKeys.delete("publicUrl");
    config.issuers.push(createIssuer("oidc"));
  },
  everything(config) {
    config.publicUrl = "https://poiesis.example.org";
    config.namespace = "";
    config.ingressClass = "nginx";
    config.clusterIssuer = "le";
    config.databaseSecret = "db";
    config.databaseCaConfigMap = "ca";
    config.s3Region = "eu-west-1";
    config.s3Secret = "s3";
    config.issuers[0].issuer = "https://kc/realms/x";
    config.issuers.push(createIssuer("gateway", { issuer: "https://gw", jwksUri: "http://gw/j" }));
    config.apiKeys = true;
    config.userGroup = "/u";
    config.adminGroup = "/a";
    config.advanced["taskpods.namespace"] = "jobs";
    config.advanced["serviceInfo.name"] = "";
    fillAllExamples(config);
  },
};

/** Fresh config with a scenario applied. */
export function scenarioConfig(name) {
  const config = createConfig();
  SCENARIOS[name](config);
  return config;
}
