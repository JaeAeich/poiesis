// "With an agent": the prompt to copy and the example session the terminal types out.

// Kept on one line: the prompt box wraps it to its own width.
export const AGENT_PROMPT =
  "Deploy Poiesis on my Kubernetes cluster. Read https://poiesis.jaeaeich.com/llms.txt first. " +
  "Ask me about my database, object storage and identity provider, then write values.yaml and " +
  "the helm install command. Tell me which Secrets to create; don't create them.";

/**
 * Line kinds, which are also the CSS classes: u = user (typed), r = agent reading,
 * q = agent question, ok = result, c2 = command.
 * @type {[string, string][]}
 */
export const AGENT_SESSION = [
  [
    "u",
    "Deploy Poiesis on my Kubernetes cluster. Read https://poiesis.jaeaeich.com/llms.txt first.",
  ],
  ["r", "reading llms.txt"],
  ["r", "reading Deploy, Helm values, Authentication"],
  ["q", "Which Postgres should Poiesis use?"],
  ["u", "Our managed Postgres. The URL is in a Secret called poiesis-db."],
  ["q", "Where do task inputs and outputs live?"],
  ["u", "S3 in eu-central-1. The nodes have IAM roles."],
  ["q", "Who issues your users' tokens?"],
  ["u", "Keycloak, realm poiesis, client poiesis-cli."],
  ["r", "writing values.yaml"],
  ["ok", "values.yaml, 22 lines"],
  ["ok", "Create the Secret poiesis-db first. S3 needs no Secret with IAM roles."],
  ["c2", "helm install poiesis ./deployment/helm/poiesis -n poiesis -f values.yaml"],
];

// Typing rhythm, in milliseconds.
export const SESSION_TIMING = Object.freeze({
  perCharacter: 16,
  afterTyped: 600,
  afterLine: { r: 650, q: 900 },
  afterOtherLine: 500,
  beforeRestart: 4500,
});
