// Form fields: labels, chart keys, placeholders and the help shown behind each "?".

/**
 * @typedef {object} FieldDefinition
 * @property {string} key Config key the field edits.
 * @property {string} domId Base of the element ids: w-<domId>, f-<domId>, p-<domId>.
 * @property {string} label
 * @property {string} [chartKey] values.yaml path shown beside the label.
 * @property {boolean} [required]
 * @property {string} [placeholder]
 * @property {string} [hintHtml] Static markup under the input.
 * @property {"text" | "number"} [type]
 * @property {string} [help] Text of the "?" popover.
 */

/** @type {Record<string, FieldDefinition>} */
export const FIELDS = {
  publicUrl: {
    key: "publicUrl",
    domId: "url",
    label: "Public URL",
    chartKey: "auth.resource",
    required: true,
    placeholder: "https://poiesis.example.org",
    hintHtml: "Also the ingress host.",
    help:
      "The address clients use, such as https://poiesis.example.org. It is also the OAuth " +
      "resource identifier, so a client that only knows this URL can find your issuers.",
  },
  clusterIssuer: {
    key: "clusterIssuer",
    domId: "cmIssuer",
    label: "ClusterIssuer",
    chartKey: "cert-manager.io/cluster-issuer",
    required: true,
    placeholder: "letsencrypt",
    help: "The cert-manager ClusterIssuer that signs the certificate, such as letsencrypt.",
  },
  tlsSecret: {
    key: "tlsSecret",
    domId: "tlsSecret",
    label: "TLS Secret",
    chartKey: "api.ingress.tls[].secretName",
    required: true,
    placeholder: "poiesis-tls",
    help: "A kubernetes.io/tls Secret holding the certificate for the host.",
  },
  namespace: {
    key: "namespace",
    domId: "ns",
    label: "Namespace",
    required: true,
    help:
      "The Kubernetes namespace the chart installs into. Tasks run here too, unless you set a " +
      "task namespace under Advanced.",
  },
  ingressClass: {
    key: "ingressClass",
    domId: "ingress",
    label: "Ingress class",
    chartKey: "api.ingress.className",
    placeholder: "cluster default",
    help:
      "Which ingress controller serves the API, such as nginx or traefik. Leave empty for the " +
      "cluster default.",
  },
  databaseSecret: {
    key: "databaseSecret",
    domId: "dbSecret",
    label: "Secret with DATABASE_URL",
    chartKey: "database.existingSecret",
    required: true,
    placeholder: "poiesis-db",
    help:
      "A Secret in the namespace with one key, DATABASE_URL, for example " +
      "postgresql://user:pass@host:5432/poiesis. The chart reads it; it never creates it.",
  },
  databaseCaConfigMap: {
    key: "databaseCaConfigMap",
    domId: "dbCa",
    label: "CA ConfigMap",
    chartKey: "database.caConfigmap",
    placeholder: "optional",
    hintHtml: "For <code>sslmode=verify-full</code>.",
    help: "A ConfigMap with a ca.crt key, used to verify Postgres's TLS certificate.",
  },
  s3Endpoint: {
    key: "s3Endpoint",
    domId: "s3Endpoint",
    label: "Endpoint",
    chartKey: "s3.endpoint",
    placeholder: "empty for AWS",
    help: "Only for S3-compatible stores such as MinIO, Ceph or SeaweedFS. Leave empty for AWS.",
  },
  s3Region: {
    key: "s3Region",
    domId: "s3Region",
    label: "Region",
    chartKey: "s3.region",
    required: true,
    placeholder: "eu-central-1",
  },
  s3Secret: {
    key: "s3Secret",
    domId: "s3Secret",
    label: "Secret name",
    chartKey: "s3.existingSecret",
    required: true,
    placeholder: "poiesis-s3",
    help: "A Secret with AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.",
  },
  s3RoleArn: {
    key: "s3RoleArn",
    domId: "s3Role",
    label: "IAM role ARN",
    chartKey: "s3.roleArn",
    required: true,
    placeholder: "arn:aws:iam::123456789012:role/poiesis",
    hintHtml: "EKS IRSA. The role must trust the TaskPod service account.",
    help:
      "tif and tof get a service account token and trade it for this role's credentials. " +
      "Executors never see the token.",
  },
  gcsSecret: {
    key: "gcsSecret",
    domId: "gcsSecret",
    label: "Secret name",
    chartKey: "gcs.existingSecret",
    required: true,
    placeholder: "poiesis-gcs",
    help: "A Secret with a service account's JSON key under GOOGLE_SERVICE_ACCOUNT_KEY.",
  },
  gcsWorkloadIdentityProvider: {
    key: "gcsWorkloadIdentityProvider",
    domId: "gcsProvider",
    label: "Pool provider",
    chartKey: "gcs.workloadIdentityProvider",
    required: true,
    placeholder:
      "//iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/poiesis/providers/cluster",
    hintHtml: "Workload Identity Federation. The provider must trust the cluster's OIDC issuer.",
    help:
      "tif and tof get a service account token and trade it at Google STS. " +
      "Executors never see the token.",
  },
  gcsServiceAccount: {
    key: "gcsServiceAccount",
    domId: "gcsServiceAccount",
    label: "Service account",
    chartKey: "gcs.serviceAccount",
    placeholder: "poiesis-filer@my-project.iam.gserviceaccount.com",
    help: "Optional. Empty uses the federated principal directly.",
  },
  azureAccount: {
    key: "azureAccount",
    domId: "azureAccount",
    label: "Storage account",
    chartKey: "azure.accountName",
    required: true,
    placeholder: "poiesisdata",
    help: "The storage account whose containers az:// URLs name.",
  },
  azureSecret: {
    key: "azureSecret",
    domId: "azureSecret",
    label: "Secret name",
    chartKey: "azure.existingSecret",
    required: true,
    placeholder: "poiesis-azure",
    help: "A Secret with the account key under AZURE_STORAGE_ACCOUNT_KEY.",
  },
  azureClientId: {
    key: "azureClientId",
    domId: "azureClientId",
    label: "Client ID",
    chartKey: "azure.clientId",
    required: true,
    placeholder: "00000000-0000-0000-0000-000000000000",
    hintHtml: "The managed identity, with a federated credential for the TaskPod service account.",
    help:
      "tif and tof get a service account token and trade it for this identity's access. " +
      "Executors never see the token.",
  },
  azureTenantId: {
    key: "azureTenantId",
    domId: "azureTenantId",
    label: "Tenant ID",
    chartKey: "azure.tenantId",
    required: true,
    placeholder: "00000000-0000-0000-0000-000000000000",
  },
  defaultSizeGi: {
    key: "defaultSizeGi",
    domId: "defSize",
    label: "Default size (Gi)",
    chartKey: "taskpods.persistence.defaultSizeGi",
    type: "number",
  },
  maxSizeGi: {
    key: "maxSizeGi",
    domId: "maxSize",
    label: "Largest allowed (Gi)",
    chartKey: "taskpods.persistence.maxSizeGi",
    type: "number",
  },
  storageClass: {
    key: "storageClass",
    domId: "sc",
    label: "StorageClass",
    chartKey: "taskpods.persistence.storageClass",
    placeholder: "cluster default",
    help: "Which StorageClass provisions task volumes. Empty uses the cluster default.",
  },
  retainSeconds: {
    key: "retainSeconds",
    domId: "retain",
    label: "Keep finished tasks (s)",
    chartKey: "taskpods.persistence.retainAfterSeconds",
    type: "number",
    help:
      "How long a finished task's Job and volume are kept for debugging before Kubernetes " +
      "deletes them.",
  },
  decisionServiceUrl: {
    key: "decisionServiceUrl",
    domId: "pdp",
    label: "AuthZEN evaluation URL",
    chartKey: "authz.decisionService.url",
    required: true,
    placeholder: "http://opa.policy.svc:8181/access/v1/evaluation",
    hintHtml: "Asked once per decision. Errors and timeouts deny.",
    help:
      "An OpenID AuthZEN 1.0 evaluation endpoint, from OPA, Cerbos or your own service. " +
      "Poiesis asks it about every action.",
  },
  userGroup: {
    key: "userGroup",
    domId: "userGroup",
    label: "Only admit group",
    chartKey: "auth.issuers[].requiredClaim",
    placeholder: "/poiesis-users",
    hintHtml: "Optional. Others get 403.",
    help: "Callers must have this value in their groups claim, or they get 403.",
  },
  adminGroup: {
    key: "adminGroup",
    domId: "adminGroup",
    label: "Admin group",
    chartKey: "auth.issuers[].admin",
    placeholder: "/poiesis-admins",
    hintHtml: "Can revoke anyone's keys.",
    help: "Members of this group can list and revoke anyone's API keys.",
  },
};

/**
 * @typedef {object} IssuerFieldDefinition
 * @property {"issuer" | "audience" | "clients" | "jwksUri"} key
 * @property {string} domKey Used in ids: c-<index>-<domKey>, p-c<index><domKey>.
 * @property {string} label
 * @property {string} placeholder
 * @property {string} [help]
 */

const ISSUER_HELP = {
  oidcIssuer:
    "Exactly the iss of the tokens. Poiesis finds the keys through its " +
    "/.well-known/openid-configuration.",
  audience:
    "The aud value tokens must carry for this Poiesis. Usually set as an audience mapper in " +
    "your identity provider.",
  clients:
    "OAuth clients whose tokens are accepted, comma-separated. Empty accepts any client of the " +
    "issuer.",
  jwksUri: "Where the gateway publishes its signing keys. Used instead of OIDC discovery.",
};

const AUDIENCE_FIELD = {
  key: "audience",
  domKey: "aud",
  label: "Audience",
  placeholder: "poiesis",
  help: ISSUER_HELP.audience,
};

/** Fields per issuer type: the first spans the row, the rest share one row. */
/** @type {Record<import("./config.js").IssuerType, IssuerFieldDefinition[]>} */
export const ISSUER_FIELDS = {
  oidc: [
    {
      key: "issuer",
      domKey: "issuer",
      label: "Issuer URL",
      placeholder: "https://keycloak.example.org/realms/poiesis",
      help: ISSUER_HELP.oidcIssuer,
    },
    AUDIENCE_FIELD,
    {
      key: "clients",
      domKey: "clients",
      label: "Clients",
      placeholder: "poiesis-cli",
      help: ISSUER_HELP.clients,
    },
  ],
  gateway: [
    {
      key: "issuer",
      domKey: "issuer",
      label: "Issuer",
      placeholder: "https://gateway.example.org",
      help: ISSUER_HELP.oidcIssuer,
    },
    AUDIENCE_FIELD,
    {
      key: "jwksUri",
      domKey: "jwks",
      label: "JWKS URL",
      placeholder: "http://gateway.mesh.svc/.well-known/jwks.json",
      help: ISSUER_HELP.jwksUri,
    },
  ],
};
