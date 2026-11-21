<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { taskFigure } from "../lib/figures.js";

const props = defineProps({ compact: { type: Boolean, default: false } });
const host = ref(null);
let stop = () => {}, ro;
onMounted(() => {
  const el = host.value;
  let narrow = null;
  const build = () => { stop(); stop = taskFigure(el, { compact: props.compact }) || (() => {}); };
  // portrait under 600px; rebuild only when the width crosses that line
  ro = new ResizeObserver(() => {
    if (!el.clientWidth) return;
    const n = el.clientWidth < 600;
    if (n !== narrow) { narrow = n; build(); }
  });
  ro.observe(el);
});
onUnmounted(() => { ro && ro.disconnect(); stop(); });
</script>

<template>
  <div ref="host" class="poi fig-host"></div>
</template>
