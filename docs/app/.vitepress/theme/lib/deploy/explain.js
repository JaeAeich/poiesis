// "How it works" panel: talking points and the flow diagram for each step.
// Points and captions are static markup; node labels come from the config and are escaped by flow().
import { withoutScheme } from "./config.js";

// Authentication diagram layout, in the 420-wide flow() coordinate space.
const ISSUER_ROW_PITCH = 58;
const ISSUER_TOP = 16;
const NODE_HALF_HEIGHT = 22;
const MAX_ISSUERS_DRAWN = 3;
const ISSUER_LABEL_CHARS = 18;
const HOST_LABEL_CHARS = 16;
const MIN_AUTHN_HEIGHT = 120;
const AUTHN_PADDING = 32;

/**
 * @typedef {object} ExplainSpec
 * @property {string} title
 * @property {string[]} points Static HTML.
 * @property {boolean} [taskFigure] Show the animated task figure.
 * @property {Record<string, object>} [nodes] flow() diagram, when present.
 * @property {[string, string][]} [edges]
 * @property {object[]} [hops]
 * @property {number} [h] Diagram height.
 */

function authenticationSpec(config) {
  const drawn = config.issuers.slice(0, MAX_ISSUERS_DRAWN);
  const rows = drawn.length + (config.apiKeys ? 1 : 0);
  const blockHeight = rows * ISSUER_ROW_PITCH - 14;
  const middleY = ISSUER_TOP + blockHeight / 2 - NODE_HALF_HEIGHT;
  const issuerNodes = drawn.map((issuer, index) => [
    `e${index}`,
    {
      x: 150,
      y: ISSUER_TOP + index * ISSUER_ROW_PITCH,
      w: 132,
      label: issuer.type === "oidc" ? "OIDC issuer" : "Gateway JWT",
      sub: withoutScheme(issuer.issuer || "not set").slice(0, ISSUER_LABEL_CHARS),
    },
  ]);
  const ids = issuerNodes.map(([id]) => id);
  return {
    title: "Authentication",
    points: [
      "The token's <code>iss</code> must match one trusted issuer exactly. Order doesn't matter.",
      "Signature, audience, token type and client are checked.",
      "The owner is <code>issuer|subject</code>, stamped on every task.",
    ],
    nodes: Object.assign(
      {
        rq: { x: 10, y: middleY, w: 100, label: "Request", sub: "Bearer …" },
        ow: { x: 318, y: middleY, w: 94, label: "Owner", sub: "issuer|sub" },
      },
      Object.fromEntries(issuerNodes),
      config.apiKeys
        ? {
            k: {
              x: 150,
              y: ISSUER_TOP + issuerNodes.length * ISSUER_ROW_PITCH,
              w: 132,
              label: "API keys",
              sub: "poi_…",
            },
          }
        : {},
    ),
    edges: [
      ...ids.map((id) => ["rq", id]),
      ...ids.map((id) => [id, "ow"]),
      ...(config.apiKeys
        ? [
            ["rq", "k"],
            ["k", "ow"],
          ]
        : []),
    ],
    h: Math.max(MIN_AUTHN_HEIGHT, AUTHN_PADDING + blockHeight),
    hops: [
      {
        f: "rq",
        t: "e0",
        label: "iss ✓",
        cap: "The token's <code>iss</code> matches a trusted issuer exactly.",
      },
      {
        f: "e0",
        t: "ow",
        label: "alice",
        tone: "ok",
        cap: "Checks pass: the caller is <code>issuer|alice</code>.",
      },
      ...(config.apiKeys
        ? [
            { f: "rq", t: "k", label: "poi_…", cap: "An API key is looked up by its hash." },
            {
              f: "k",
              t: "ow",
              label: "alice",
              tone: "ok",
              cap: "It has the owner of whoever minted it.",
            },
          ]
        : []),
    ],
  };
}

const SPECS = {
  basics: (config) => ({
    title: "Public URL",
    points: [
      "Becomes the ingress host and <code>auth.resource</code>.",
      "A client that only knows this URL gets a 401 that points to the metadata.",
      "The metadata names your issuers, so the client can log in.",
    ],
    nodes: {
      cl: { x: 10, y: 100, w: 100, label: "Client", sub: "Nextflow" },
      ing: {
        x: 160,
        y: 30,
        w: 110,
        label: "Ingress",
        sub: withoutScheme(config.publicUrl || "poiesis.example.org").slice(0, HOST_LABEL_CHARS),
      },
      api: { x: 300, y: 100, w: 110, label: "Poiesis API" },
      iss: { x: 160, y: 180, w: 110, label: "Issuer", sub: "Keycloak" },
    },
    edges: [
      ["cl", "ing"],
      ["ing", "api"],
      ["cl", "iss"],
      ["cl", "api"],
    ],
    hops: [
      { f: "cl", t: "ing", label: "GET /tasks", cap: "A client calls the public URL." },
      { f: "ing", t: "api", label: "GET /tasks", cap: "The ingress forwards it to the API." },
      {
        f: "api",
        t: "cl",
        label: "401",
        tone: "bad",
        cap: "No token: 401, pointing to the resource metadata.",
      },
      {
        f: "cl",
        t: "iss",
        label: "log in",
        cap: "The metadata names the issuer. The client logs in there.",
      },
      {
        f: "cl",
        t: "api",
        label: "Bearer …",
        tone: "ok",
        cap: "It retries with the token and gets 200.",
      },
    ],
  }),
  database: (config) => ({
    title: "Database",
    points: [
      "The API and tctl read <code>DATABASE_URL</code> from your Secret.",
      "A migration hook updates the schema before each install or upgrade.",
      "In production, use <code>sslmode=verify-full</code> with a CA ConfigMap.",
    ],
    nodes: {
      sec: { x: 10, y: 100, w: 110, label: "Secret", sub: config.databaseSecret || "poiesis-db" },
      api: { x: 160, y: 30, w: 110, label: "API" },
      tc: { x: 160, y: 170, w: 110, label: "tctl", sub: "task state" },
      pg: { x: 300, y: 100, w: 110, label: "Postgres" },
    },
    edges: [
      ["sec", "api"],
      ["sec", "tc"],
      ["api", "pg"],
      ["tc", "pg"],
    ],
    hops: [
      { f: "sec", t: "api", label: "DATABASE_URL", cap: "The API reads the URL from your Secret." },
      {
        f: "sec",
        t: "tc",
        label: "DATABASE_URL",
        cap: "So does tctl, which records how tasks end.",
      },
      { f: "api", t: "pg", label: "tasks", cap: "The API stores tasks and API keys." },
      {
        f: "tc",
        t: "pg",
        label: "COMPLETE",
        tone: "ok",
        cap: "tctl writes each task's final state.",
      },
    ],
  }),
  storage: (config) => ({
    title: "Storage",
    points: [
      "Only task inputs and outputs touch object storage.",
      "Credentials come from your Secret, or from workload identity.",
      "While a task runs, its files live on its own volume.",
    ],
    nodes: {
      in: { x: 10, y: 30, w: 100, label: "s3://in" },
      tif: { x: 155, y: 30, w: 110, label: "tif", sub: "stage in" },
      vol: { x: 155, y: 115, w: 110, label: "volume" },
      tof: { x: 155, y: 200, w: 110, label: "tof", sub: "stage out" },
      out: { x: 310, y: 200, w: 100, label: "s3://out" },
      cr: {
        x: 310,
        y: 30,
        w: 100,
        label: "credentials",
        sub: config.s3Credentials === "secret" ? config.s3Secret || "Secret" : "IRSA",
      },
    },
    edges: [
      ["cr", "tif"],
      ["in", "tif"],
      ["tif", "vol"],
      ["vol", "tof"],
      ["tof", "out"],
    ],
    h: 260,
    hops: [
      { f: "cr", t: "tif", label: "AWS_*", cap: "tif gets the S3 credentials." },
      { f: "in", t: "tif", label: "reads.fq", cap: "It downloads each input…" },
      { f: "tif", t: "vol", label: "reads.fq", cap: "…onto the task's volume." },
      {
        f: "vol",
        t: "tof",
        label: "sorted.bam",
        cap: "After the executors, tof picks up the outputs…",
      },
      { f: "tof", t: "out", label: "sorted.bam", tone: "ok", cap: "…and uploads them." },
    ],
  }),
  volumes: () => ({
    title: "Task volumes",
    points: [
      "Sized by the task's <code>disk_gb</code>, up to the largest allowed.",
      "Shared by the task's containers.",
      "Deleted with the Job after <code>retainAfterSeconds</code>.",
    ],
    taskFigure: true,
  }),
  authentication: authenticationSpec,
  authorization: (config) =>
    config.authzMode === "decision-service" ? DECISION_SERVICE_SPEC : OWNER_ONLY_SPEC,
  advanced: () => ({ title: "Advanced", points: ["None of these are needed to start."] }),
  review: () => REVIEW_SPEC,
};

const DECISION_SERVICE_SPEC = {
  title: "Authorization",
  points: [
    "Each decision is one AuthZEN call.",
    "The service can share tasks with groups or everyone.",
    "If it errors or times out, the answer is no (503).",
  ],
  nodes: {
    rq: { x: 10, y: 90, w: 100, label: "alice", sub: "GET task" },
    api: { x: 160, y: 90, w: 100, label: "API" },
    pdp: { x: 310, y: 30, w: 100, label: "Policy", sub: "AuthZEN" },
    db: { x: 310, y: 150, w: 100, label: "Tasks" },
  },
  edges: [
    ["rq", "api"],
    ["api", "pdp"],
    ["api", "db"],
  ],
  hops: [
    { f: "rq", t: "api", label: "GET", cap: "alice asks for a task." },
    {
      f: "api",
      t: "pdp",
      label: "evaluate",
      cap: "Poiesis asks the policy whether alice may read it.",
    },
    { f: "pdp", t: "api", label: "true", tone: "ok", cap: "Yes: her group shares it." },
    { f: "api", t: "db", label: "read", cap: "Only then is the task read." },
    { f: "api", t: "rq", label: "200", tone: "ok", cap: "alice gets the task." },
  ],
};

const OWNER_ONLY_SPEC = {
  title: "Authorization",
  points: [
    "Everyone sees and cancels only their own tasks.",
    "An admin group can revoke anyone's API keys.",
    "Add a decision service later to share tasks.",
  ],
  nodes: {
    rq: { x: 10, y: 90, w: 100, label: "alice", sub: "GET task" },
    api: { x: 160, y: 90, w: 100, label: "API", sub: "owner rule" },
    db: { x: 310, y: 90, w: 100, label: "Tasks" },
  },
  edges: [
    ["rq", "api"],
    ["api", "db"],
  ],
  h: 220,
  hops: [
    { f: "rq", t: "api", label: "GET", cap: "alice asks for a task." },
    { f: "api", t: "db", label: "owner?", cap: "Poiesis checks who owns the task." },
    { f: "api", t: "rq", label: "200", tone: "ok", cap: "It's hers: 200. Anyone else gets 404." },
  ],
};

const REVIEW_SPEC = {
  title: "Installing",
  points: [
    "Create the Secrets first; the chart only refers to them.",
    "A migration hook runs before the API starts.",
    "tctl polls TaskPods and records how each task ends.",
  ],
  nodes: {
    you: { x: 10, y: 90, w: 90, label: "You" },
    kc: { x: 150, y: 20, w: 120, label: "kubectl", sub: "Secrets" },
    hm: { x: 150, y: 160, w: 120, label: "helm", sub: "values.yaml" },
    cl: { x: 310, y: 90, w: 100, label: "Cluster", sub: "api · tctl" },
  },
  edges: [
    ["you", "kc"],
    ["you", "hm"],
    ["kc", "cl"],
    ["hm", "cl"],
  ],
  hops: [
    { f: "you", t: "kc", label: "create", cap: "Create the database and S3 Secrets." },
    { f: "kc", t: "cl", label: "Secrets", cap: "They land in the namespace." },
    { f: "you", t: "hm", label: "install", cap: "Run helm install with your values.yaml." },
    { f: "hm", t: "cl", label: "migrate", cap: "Migrations run, then the API and tctl start." },
    { f: "cl", t: "you", label: "ready", tone: "ok", cap: "Point an engine at the public URL." },
  ],
};

/**
 * @param {import("./config.js").DeployConfig} config
 * @param {string} stepId
 * @returns {ExplainSpec}
 */
export function explainSpec(config, stepId) {
  return SPECS[stepId](config);
}
