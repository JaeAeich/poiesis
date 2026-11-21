<script setup>
// The deploy configurator page: step-by-step form with a live values.yaml, or an agent prompt.
import { nextTick, onMounted, onUnmounted, ref } from "vue";
import { withBase } from "vitepress";
import { prefersReducedMotion } from "../lib/deploy/browser.js";
import { createDeployStore, provideDeploy } from "../lib/deploy/store.js";
import { useKeyboardModality } from "../lib/deploy/use-keyboard-modality.js";
import { useStepNavigation } from "../lib/deploy/use-step-navigation.js";
import AgentMode from "./deploy/AgentMode.vue";
import ExplainPanel from "./deploy/ExplainPanel.vue";
import FilePanel from "./deploy/FilePanel.vue";
import SegmentedControl from "./deploy/SegmentedControl.vue";
import StepList from "./deploy/StepList.vue";

const MODES = [
  ["human", "Step by step"],
  ["agent", "With an agent"],
];

const store = createDeployStore();
const { ui } = store;
const stepList = ref(null);
const filePanel = ref(null);
const keyboard = useKeyboardModality();
const navigation = useStepNavigation(store, {
  stepsElement: () => stepList.value?.$el ?? null,
  keyboard,
});

provideDeploy({
  ...store,
  ...navigation,
  showInstallTab: () => filePanel.value.showInstall(),
  editValuesHere: () => filePanel.value.editValues(),
  downloadValues: () => filePanel.value.downloadValues(),
  docsHref: withBase("/docs/start/what-is-poiesis"),
});

async function setMode(mode) {
  ui.mode = mode;
  if (mode === "agent") {
    store.closeExplain();
    return;
  }
  await nextTick();
  filePanel.value.refresh();
}

// Escape closes the innermost thing first: an open "?" popover, then the panel.
function onKeydown(event) {
  if (event.key !== "Escape") return;
  if (ui.openPopover) store.closePopover();
  else if (ui.panelOpen) store.closeExplain();
}

// A click anywhere outside the popover (or its "?" button) closes it.
function onDocumentClick(event) {
  if (ui.openPopover && !event.target.closest(".pop, [data-info]")) store.closePopover();
}

onMounted(() => {
  ui.reducedMotion = prefersReducedMotion();
  window.addEventListener("keydown", onKeydown);
  document.addEventListener("click", onDocumentClick);
  if (location.hash === "#example") navigation.fillAll();
});

onUnmounted(() => {
  window.removeEventListener("keydown", onKeydown);
  document.removeEventListener("click", onDocumentClick);
  store.closeExplain();
  store.dispose();
});
</script>

<template>
  <main class="poi poi-deploy">
    <div class="wrap">
      <div class="dhead">
        <div>
          <h1>Deploy Poiesis</h1>
          <p class="dsub">
            You bring a cluster, Postgres, an S3 bucket and an OIDC issuer. You get a values.yaml
            and the commands to install it.
          </p>
        </div>
        <div class="right">
          <button
            id="fill-all"
            class="btn sm"
            :hidden="ui.mode !== 'human'"
            @click="navigation.fillAll()"
          >
            Show an example file
          </button>
          <SegmentedControl
            class="big"
            label="How to deploy"
            :options="MODES"
            :model-value="ui.mode"
            @update:model-value="setMode"
          />
        </div>
      </div>
      <div id="mode-human" :hidden="ui.mode !== 'human'">
        <div class="cfg">
          <StepList ref="stepList" />
          <FilePanel ref="filePanel" />
        </div>
      </div>
      <div id="mode-agent" :hidden="ui.mode !== 'agent'">
        <AgentMode />
      </div>
    </div>
    <ExplainPanel />
    <div id="toast" class="toast" :class="{ on: ui.toastVisible }" role="status" aria-live="polite">
      {{ ui.toastText }}
    </div>
  </main>
</template>
