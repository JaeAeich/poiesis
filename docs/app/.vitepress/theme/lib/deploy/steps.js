import { changedAdvancedItems } from "./advanced.js";

/** Step positions; values.yaml lines carry these to know which step wrote them. */
export const STEP = Object.freeze({
  BASICS: 0,
  DATABASE: 1,
  STORAGE: 2,
  VOLUMES: 3,
  AUTHENTICATION: 4,
  AUTHORIZATION: 5,
  ADVANCED: 6,
  REVIEW: 7,
});

/**
 * @typedef {object} StepDefinition
 * @property {string} id
 * @property {string} title
 * @property {boolean} optional Optional steps have no "Use example values".
 * @property {(config: import("./config.js").DeployConfig) => string} summary Shown when collapsed.
 */

/** @type {StepDefinition[]} */
export const STEPS = [
  {
    id: "basics",
    title: "Basics",
    optional: false,
    summary: (config) => config.publicUrl || "public URL",
  },
  {
    id: "database",
    title: "Database",
    optional: false,
    summary: (config) => (config.databaseSecret ? `Secret ${config.databaseSecret}` : "Postgres"),
  },
  {
    id: "storage",
    title: "Storage",
    optional: false,
    summary: (config) => (config.s3Region ? `S3 · ${config.s3Region}` : "S3"),
  },
  {
    id: "volumes",
    title: "Task volumes",
    optional: false,
    summary: (config) => `${config.defaultSizeGi}–${config.maxSizeGi} Gi`,
  },
  {
    id: "authentication",
    title: "Authentication",
    optional: false,
    summary: (config) => {
      const count = config.issuers.length;
      return `${count} issuer${count === 1 ? "" : "s"}${config.apiKeys ? " + API keys" : ""}`;
    },
  },
  {
    id: "authorization",
    title: "Authorization",
    optional: false,
    summary: (config) => (config.authzMode === "owner" ? "owner only" : "decision service"),
  },
  {
    id: "advanced",
    title: "Advanced",
    optional: true,
    summary: (config) => {
      const changed = changedAdvancedItems(config).length;
      return changed ? `${changed} changed` : "chart defaults";
    },
  },
  {
    id: "review",
    title: "Review",
    optional: false,
    summary: () => "",
  },
];

export const LAST_STEP = STEPS.length - 1;
