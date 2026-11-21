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
    chartKey: "serviceAccount.*.annotations",
    required: true,
    placeholder: "arn:aws:iam::123456789012:role/poiesis",
    hintHtml: "EKS IRSA. For GCS through its S3 API, use an access key Secret with HMAC keys.",
    help:
      "Written as eks.amazonaws.com/role-arn on the API and TaskPod service accounts, so tif " +
      "and tof get S3 access through IRSA.",
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
