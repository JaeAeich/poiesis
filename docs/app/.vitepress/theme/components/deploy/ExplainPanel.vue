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
          <!-- eslint-disable-next-line vue/no-v-html -- static markup from explain.js -->
          <li v-for="point in spec.points" :key="point"><span v-html="point"></span></li>
        </ul>
        <div class="pnav"><a class="btn ghost sm" :href="docsHref">Read the docs</a></div>
      </template>
    </div>
  </aside>
</template>

<style scoped>
/* "How it works": a side sheet on desktop, a bottom sheet on phones */
.poi .scrim {
  position: fixed;
  inset: 0;
  background: rgba(8, 18, 30, 0.32);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.3s;
  z-index: 40;
}
.poi .scrim.on {
  opacity: 1;
  pointer-events: auto;
}
.poi .panel {
  position: fixed;
  z-index: 41;
  background: var(--bg);
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  transition:
    transform 0.45s var(--ease),
    visibility 0s 0.45s;
  visibility: hidden;
}
@media (min-width: 761px) {
  .poi .panel {
    top: 0;
    bottom: 0;
    right: 0;
    width: min(480px, 92vw);
    border-left: 1px solid var(--line);
    transform: translateX(102%);
  }
}
@media (max-width: 760px) {
  .poi .panel {
    left: 0;
    right: 0;
    bottom: 0;
    max-height: 84dvh;
    border-radius: 16px 16px 0 0;
    border-top: 1px solid var(--line);
    transform: translateY(102%);
  }
}
.poi .panel.on {
  transform: none;
  visibility: visible;
  transition: transform 0.45s var(--ease);
}
.poi .panel .grab {
  display: none;
  width: 36px;
  height: 4px;
  border-radius: 2px;
  background: var(--line-strong);
  margin: 8px auto 0;
}
@media (max-width: 760px) {
  .poi .panel .grab {
    display: block;
  }
}

/* header, body, talking points, step navigation */
.poi .panel .ph {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--line);
}
.poi .panel .ph h2 {
  font-size: 18px;
}
.poi .panel .ph .x {
  margin-left: auto;
}
.poi .panel .pb {
  padding: 18px;
  overflow: auto;
}
.poi .panel .pts {
  list-style: none;
  margin: 18px 0 0;
  padding: 0;
  display: grid;
  gap: 10px;
  font-size: 15px;
}
.poi .panel .pts li {
  display: flex;
  gap: 12px;
}
.poi .panel .pts li::before {
  content: "";
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--coral);
  margin-top: 10px;
}
.poi .panel .pnav {
  display: flex;
  justify-content: flex-start;
  gap: 8px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}
</style>
