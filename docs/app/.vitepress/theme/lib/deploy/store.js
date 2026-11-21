// Reactive state of the deploy configurator, shared with every component through provide/inject.
import { computed, inject, provide, reactive } from "vue";
import { findAdvancedItem, parseAdvancedInput } from "./advanced.js";
import { createConfig, createIssuer, exampleKey } from "./config.js";
import { explainSpec } from "./explain.js";
import { fillStepExample } from "./examples.js";
import { linesToText, manualLines } from "./file-lines.js";
import { installShLines } from "./install-sh.js";
import { STEPS } from "./steps.js";
import { runTrial } from "./trials.js";
import { valuesYamlLines } from "./values-yaml.js";

const TOAST_MS = 1600;
const CONTEXT_KEY = Symbol("deploy");

/** @typedef {ReturnType<typeof createDeployStore>} DeployStore */

export function createDeployStore() {
  const config = reactive(createConfig());

  const wizard = reactive({
    step: 0,
    /** @type {Set<number>} */
    completed: new Set(),
    /** @type {(import("./trials.js").TrialResult & { run: number }) | null} */
    trial: null,
    /** @type {string | null} */
    openAdvancedGroup: null,
  });

  const file = reactive({
    /** @type {"values" | "install"} */
    tab: "values",
    editing: false,
    /** Hand-edited values.yaml; null while the form drives the file. */
    /** @type {string | null} */
    manualText: null,
  });

  const ui = reactive({
    /** @type {"human" | "agent"} */
    mode: "human",
    /** @type {string | null} */
    openPopover: null,
    toastText: "",
    toastVisible: false,
    panelOpen: false,
    /** @type {import("./explain.js").ExplainSpec | null} */
    panelSpec: null,
    panelStep: 0,
    /** Bumped on every open so the panel's figure restarts. */
    panelRevision: 0,
    reducedMotion: false,
  });

  const fileLines = computed(() => {
    if (file.tab === "values" && file.manualText !== null) return manualLines(file.manualText);
    return file.tab === "values" ? valuesYamlLines(config) : installShLines(config);
  });
  const fileText = computed(() => linesToText(fileLines.value));
  const fileName = computed(() => (file.tab === "values" ? "values.yaml" : "install.sh"));

  let trialRun = 0;
  let toastTimer = 0;

  return {
    config,
    wizard,
    file,
    ui,
    fileLines,
    fileText,
    fileName,

    /** Edit a config field; an edited field no longer holds an example value. */
    setField(key, value) {
      config[key] = value;
      config.exampleKeys.delete(key);
    },
    setIssuerField(index, key, value) {
      config.issuers[index][key] = value;
      config.exampleKeys.delete(exampleKey(key, index));
    },
    addIssuer(type) {
      config.issuers.push(createIssuer(type));
      wizard.trial = null;
    },
    removeIssuer(index) {
      config.issuers.splice(index, 1);
      wizard.trial = null;
    },
    toggleApiKeys() {
      config.apiKeys = !config.apiKeys;
      wizard.trial = null;
    },
    tryRequest(kind) {
      wizard.trial = { ...runTrial(config, kind), run: ++trialRun };
    },
    /** @param {string} key @param {{ value: string, checked: boolean }} input */
    setAdvanced(key, input) {
      const item = findAdvancedItem(key);
      config.advanced[key] = parseAdvancedInput(item, input);
    },
    fillStepExample(step) {
      fillStepExample(config, step);
    },

    togglePopover(id) {
      ui.openPopover = ui.openPopover === id ? null : id;
    },
    closePopover() {
      ui.openPopover = null;
    },

    showToast(text) {
      ui.toastText = text;
      ui.toastVisible = true;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        ui.toastVisible = false;
      }, TOAST_MS);
    },

    /** Show "How it works" for the current step, as the config is now. */
    openExplain() {
      ui.panelSpec = explainSpec(config, STEPS[wizard.step].id);
      ui.panelStep = wizard.step;
      ui.panelRevision++;
      ui.panelOpen = true;
    },
    closeExplain() {
      ui.panelOpen = false;
    },

    dispose() {
      clearTimeout(toastTimer);
    },
  };
}

/**
 * Everything components reach through useDeploy(): the store plus page-level actions
 * that need the DOM (navigation, the file panel).
 * @typedef {DeployStore & {
 *   goToStep: (index: number, focusId?: string | null) => Promise<void>,
 *   advance: () => Promise<void>,
 *   fillAll: () => Promise<void>,
 *   showInstallTab: () => void,
 *   editValuesHere: () => Promise<void>,
 *   downloadValues: () => void,
 *   docsHref: string,
 * }} DeployContext
 */

/** @param {DeployContext} context */
export function provideDeploy(context) {
  provide(CONTEXT_KEY, context);
}

/** @returns {DeployContext} */
export function useDeploy() {
  return inject(CONTEXT_KEY);
}
