<script setup>
// The "How it works" side sheet: a modal dialog with a focus trap. Escape is handled by the page.
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useDeploy } from "../../lib/deploy/store.js";
import DeployIcon from "./DeployIcon.vue";
import PanelFigure from "./PanelFigure.vue";

// Wait for the slide-in to start before moving focus, so the sheet doesn't jump.
const FOCUS_DELAY_MS = 50;
const FOCUSABLE = "button, a, [tabindex]";
// Talking points are static markup from explain.js, so v-html is safe there.

const { ui, closeExplain, docsHref } = useDeploy();
const panelElement = ref(null);
const closeButton = ref(null);
const spec = computed(() => ui.panelSpec);
const hasFigure = computed(() =>
  Boolean(spec.value && (spec.value.taskFigure || spec.value.nodes)),
);

let returnFocusTo = null;
let focusTimer = 0;

watch(
  () => [ui.panelOpen, ui.panelRevision],
  ([open], [wasOpen]) => {
    clearTimeout(focusTimer);
    if (open) {
      if (!wasOpen) returnFocusTo = document.activeElement;
      focusTimer = setTimeout(
        () => closeButton.value?.focus({ preventScroll: true }),
        FOCUS_DELAY_MS,
      );
    } else if (wasOpen && returnFocusTo?.focus) {
      returnFocusTo.focus({ preventScroll: true });
    }
  },
);

/** Keep Tab and Shift+Tab inside the panel while it is open. */
function trapFocus(event) {
  if (event.key !== "Tab" || !ui.panelOpen) return;
  const focusable = [...panelElement.value.querySelectorAll(FOCUSABLE)].filter(
    (element) => !element.disabled && element.offsetParent,
  );
  if (!focusable.length) return;
  const position = focusable.indexOf(document.activeElement);
  if (event.shiftKey && position <= 0) {
    event.preventDefault();
    focusable[focusable.length - 1].focus();
  } else if (!event.shiftKey && position === focusable.length - 1) {
    event.preventDefault();
    focusable[0].focus();
  }
}

onMounted(() => window.addEventListener("keydown", trapFocus));
onUnmounted(() => {
  window.removeEventListener("keydown", trapFocus);
  clearTimeout(focusTimer);
});
</script>

<template>
  <div id="scrim" class="scrim" :class="{ on: ui.panelOpen }" @click="closeExplain()"></div>
  <aside
    id="panel"
    ref="panelElement"
    class="panel"
    :class="{ on: ui.panelOpen }"
    role="dialog"
    aria-modal="true"
    aria-labelledby="panel-title"
  >
    <div class="grab"></div>
    <div class="ph">
      <span id="panel-step" class="eyebrow">{{ spec ? `Step ${ui.panelStep + 1}` : "" }}</span>
      <h2 id="panel-title">{{ spec?.title }}</h2>
      <button
        id="panel-x"
        ref="closeButton"
        class="icon-btn x"
        aria-label="Close"
        @click="closeExplain()"
      >
        <DeployIcon name="x" />
      </button>
    </div>
    <div id="panel-body" class="pb">
      <template v-if="spec">
        <PanelFigure v-if="hasFigure" :key="ui.panelRevision" :spec="spec" :active="ui.panelOpen" />
        <ul class="pts">
          <li v-for="point in spec.points" :key="point"><span v-html="point"></span></li>
        </ul>
        <div class="pnav"><a class="btn ghost sm" :href="docsHref">Read the docs</a></div>
      </template>
    </div>
  </aside>
</template>
