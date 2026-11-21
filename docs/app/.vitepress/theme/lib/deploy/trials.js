// "Try a request": how the authentication chain treats a sample credential.
import { DEFAULT_AUDIENCE, withoutScheme } from "./config.js";

export const TRIAL_OPTIONS = /** @type {const} */ ([
  ["kc", "Keycloak token"],
  ["gw", "Gateway token"],
  ["key", "API key"],
  ["none", "No credential"],
]);

/**
 * @typedef {object} TrialStep
 * @property {string} text
 * @property {"ok" | "bad"} [tone]
 * @property {string} [strong] Bold status code shown before the text.
 */

/**
 * @typedef {object} TrialResult
 * @property {string} kind
 * @property {number | "key" | null} hit Issuer position or "key" that handled it.
 * @property {TrialStep[]} steps
 */

const rejected = (credential, reason) => [
  { text: credential },
  { text: reason, tone: "bad" },
  { text: "401 invalid_token", tone: "bad" },
];

const TRIALS = {
  kc(config) {
    const index = config.issuers.findIndex((issuer) => issuer.type === "oidc" && issuer.issuer);
    if (index < 0) {
      return {
        hit: null,
        steps: rejected("Bearer eyJ… (iss: keycloak)", "no OIDC issuer set yet"),
      };
    }
    const issuer = config.issuers[index];
    const name = withoutScheme(issuer.issuer);
    const client = (issuer.clients || "any").split(",")[0];
    return {
      hit: index,
      steps: [
        { text: "Bearer eyJhbGci…" },
        { text: `iss matches ${name}` },
        { text: "signature checked against the issuer's keys" },
        { text: `aud ${issuer.audience || DEFAULT_AUDIENCE} · typ JWT · client ${client}` },
        ...(config.userGroup ? [{ text: `groups contains ${config.userGroup}` }] : []),
        { strong: "200", text: `  owner ${name}|alice`, tone: "ok" },
      ],
    };
  },
  gw(config) {
    const index = config.issuers.findIndex((issuer) => issuer.type === "gateway");
    if (index < 0) {
      return {
        hit: null,
        steps: rejected("Bearer eyJ… (iss: gateway)", "no entry for this issuer"),
      };
    }
    return {
      hit: index,
      steps: [
        { text: "Bearer eyJ… signed by the gateway" },
        { text: `iss matches ${withoutScheme(config.issuers[index].issuer || "")}` },
        { text: "keys from the static jwksUri" },
        { strong: "200", text: "  owner gateway|svc-nextflow", tone: "ok" },
      ],
    };
  },
  key(config) {
    if (!config.apiKeys)
      return { hit: null, steps: rejected("Bearer poi_7Kq…", "API keys are off") };
    return {
      hit: "key",
      steps: [
        { text: "Bearer poi_7Kq…" },
        { text: "poi_ prefix: an API key, looked up by hash" },
        { text: "not revoked, not expired" },
        { strong: "200", text: "  same owner as the user who minted it", tone: "ok" },
      ],
    };
  },
  none(config) {
    const hasUrl = Boolean(config.publicUrl);
    return {
      hit: null,
      steps: [
        { text: "no Authorization header" },
        { text: "401", tone: "bad" },
        { text: `WWW-Authenticate: Bearer${hasUrl ? " resource_metadata=…" : ""}`, tone: "bad" },
        {
          text: hasUrl
            ? "the client follows it to your issuer"
            : "set a public URL so clients can find the issuer",
        },
      ],
    };
  },
};

/**
 * @param {import("./config.js").DeployConfig} config
 * @param {string} kind One of TRIAL_OPTIONS.
 * @returns {TrialResult}
 */
export function runTrial(config, kind) {
  return { kind, ...TRIALS[kind](config) };
}

/** Marker before each trace line. */
export function trialSymbol(tone) {
  if (tone === "bad") return "×";
  if (tone === "ok") return "✓";
  return "›";
}
