// Everything the steps don't ask, with the chart default and a reason to change it.

/**
 * @typedef {object} AdvancedItem
 * @property {string} key Chart path; also the key in config.advanced.
 * @property {string} [shownKey] Chart path to display when it differs from key.
 * @property {string} label
 * @property {string | number | boolean} defaultValue
 * @property {"text" | "number" | "boolean" | "select"} kind
 * @property {string[]} [options] For kind "select".
 * @property {string} [placeholder]
 * @property {string} why
 * @property {(config: import("./config.js").DeployConfig) => boolean} [when] Shown only if true.
 */

/**
 * @typedef {object} AdvancedGroup
 * @property {string} name
 * @property {AdvancedItem[]} items
 * @property {(config: import("./config.js").DeployConfig) => boolean} [when]
 */

/** @type {AdvancedGroup[]} */
export const ADVANCED_GROUPS = [
  {
    name: "Service info",
    items: [
      {
        key: "serviceInfo.id",
        label: "Service id",
        defaultValue: "",
        kind: "text",
        placeholder: "org.ga4gh.poiesis",
        why: "Tells your deployment apart in registries and policies.",
      },
      {
        key: "serviceInfo.name",
        label: "Display name",
        defaultValue: "",
        kind: "text",
        placeholder: "Poiesis",
        why: "Shown by clients and registries.",
      },
      {
        key: "serviceInfo.environment",
        label: "Environment",
        defaultValue: "",
        kind: "select",
        options: ["", "prod", "staging", "test", "dev"],
        why: "Lets clients tell prod from test.",
      },
    ],
  },
  {
    name: "API",
    items: [
      {
        key: "api.replicas",
        label: "Replicas",
        defaultValue: 1,
        kind: "number",
        why: "More replicas for availability.",
      },
      {
        key: "api.pdb.enabled",
        label: "PodDisruptionBudget",
        defaultValue: false,
        kind: "boolean",
        why: "Keeps an API Pod up during node drains.",
      },
      {
        key: "logLevel",
        label: "Log level",
        defaultValue: "INFO",
        kind: "select",
        options: ["DEBUG", "INFO", "WARNING", "ERROR"],
        why: "DEBUG while you set things up.",
      },
    ],
  },
  {
    name: "API keys",
    when: (config) => config.apiKeys,
    items: [
      {
        key: "auth.apiKeys.defaultTtl",
        label: "Default lifetime",
        defaultValue: "7d",
        kind: "text",
        why: "How long a key lasts if the request names no lifetime.",
      },
      {
        key: "auth.apiKeys.maxTtl",
        label: "Longest lifetime",
        defaultValue: "90d",
        kind: "text",
        why: "The longest an owner may ask for.",
      },
      {
        key: "auth.apiKeys.maxPerOwner",
        label: "Keys per owner",
        defaultValue: 20,
        kind: "number",
        why: "Active keys one owner may hold.",
      },
    ],
  },
  {
    name: "Swagger UI login",
    when: (config) => config.issuers.some((issuer) => issuer.type === "oidc" && issuer.issuer),
    items: [
      {
        key: "auth.swaggerUi.clientId",
        label: "Public client id",
        defaultValue: "",
        kind: "text",
        placeholder: "poiesis-swagger",
        why: "Lets users log in at /docs and mint keys in the browser.",
      },
    ],
  },
  {
    name: "Task pods",
    items: [
      {
        key: "taskpods.namespace",
        label: "Task namespace",
        defaultValue: "",
        kind: "text",
        placeholder: "same as release",
        why: "Runs tasks apart from the control plane.",
      },
      {
        key: "taskpods.outputGlobFallback",
        label: "Upload everything when a glob matches nothing",
        defaultValue: false,
        kind: "boolean",
        why: "Off is safer: a typo can't export a whole volume.",
      },
      {
        key: "taskpods.persistence.rwx",
        shownKey: "taskpods.persistence.accessModes",
        label: "ReadWriteMany volumes",
        defaultValue: false,
        kind: "boolean",
        why: "Only if your storage offers nothing else.",
      },
    ],
  },
  {
    name: "Security",
    items: [
      {
        key: "networkPolicy.enabled",
        label: "NetworkPolicy",
        defaultValue: false,
        kind: "boolean",
        why: "Limits who can reach the API Pods.",
      },
      {
        key: "audit.enabled",
        label: "Audit log",
        defaultValue: true,
        kind: "boolean",
        why: "One JSON line per decision and key event.",
      },
      {
        key: "authz.adminRead",
        label: "Admins can read every task",
        defaultValue: false,
        kind: "boolean",
        when: (config) => config.authzMode === "owner" && Boolean(config.adminGroup),
        why: "Off: admins see only their own tasks.",
      },
      {
        key: "authz.maxOwners",
        label: "Most owners per list",
        defaultValue: 1000,
        kind: "number",
        when: (config) => config.authzMode === "decision-service" && config.sharing,
        why: "Caps what one shared list may query.",
      },
    ],
  },
];

const ALL_ITEMS = ADVANCED_GROUPS.flatMap((group) => group.items);

/** @param {string} key */
export function findAdvancedItem(key) {
  return ALL_ITEMS.find((item) => item.key === key);
}

/** Current value: the override if set, else the chart default. */
export function advancedValue(config, item) {
  return item.key in config.advanced ? config.advanced[item.key] : item.defaultValue;
}

/** @param {AdvancedItem} item */
export function isAdvancedChanged(config, item) {
  return advancedValue(config, item) !== item.defaultValue;
}

/**
 * Groups and items that apply to the current config.
 * @returns {{ name: string, items: AdvancedItem[] }[]}
 */
export function liveAdvancedGroups(config) {
  return ADVANCED_GROUPS.filter((group) => !group.when || group.when(config)).map((group) => ({
    name: group.name,
    items: group.items.filter((item) => !item.when || item.when(config)),
  }));
}

/** @returns {(AdvancedItem & { group: string })[]} */
export function liveAdvancedItems(config) {
  return liveAdvancedGroups(config).flatMap((group) =>
    group.items.map((item) => ({ ...item, group: group.name })),
  );
}

export function changedAdvancedItems(config) {
  return liveAdvancedItems(config).filter((item) => isAdvancedChanged(config, item));
}

export function defaultAdvancedItems(config) {
  return liveAdvancedItems(config).filter((item) => !isAdvancedChanged(config, item));
}

/** Live overrides as { chartPath: value }; hidden items never reach the file. */
export function advancedOverrides(config) {
  return Object.fromEntries(
    changedAdvancedItems(config).map((item) => [item.key, advancedValue(config, item)]),
  );
}

/** DOM id of an advanced field's wrapper; its input is `${id}-i`. */
export function advancedFieldId(key) {
  return "a-" + key.replace(/\./g, "-");
}

/**
 * Value to store for what the user entered in an advanced field.
 * @param {AdvancedItem} item
 * @param {{ value: string, checked: boolean }} input
 */
export function parseAdvancedInput(item, input) {
  if (item.kind === "boolean") return input.checked;
  if (item.kind === "number") return input.value === "" ? item.defaultValue : Number(input.value);
  return input.value;
}

/** Value as shown in the review: empty reads "unset". */
export function formatAdvancedValue(value) {
  return value === "" ? "unset" : String(value);
}
