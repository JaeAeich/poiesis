<script setup>
// The "how a task runs" figure. Portrait under NARROW_WIDTH; it is rebuilt only when the host
// crosses that width.
import { onMounted, onUnmounted, ref } from "vue";
import { mountTaskFigure } from "../lib/figures/taskFigure.js";
import { NARROW_WIDTH } from "../lib/figures/taskLayout.js";

const props = defineProps({ compact: { type: Boolean, default: false } });

const host = ref(null);
let unmount = () => {};
let observer = null;

onMounted(() => {
  const el = host.value;
  let narrow = null;
  observer = new ResizeObserver(() => {
    if (!el.clientWidth) return;
    const isNarrow = el.clientWidth < NARROW_WIDTH;
    if (isNarrow === narrow) return;
    narrow = isNarrow;
    unmount();
    unmount = mountTaskFigure(el, { compact: props.compact });
  });
  observer.observe(el);
});

onUnmounted(() => {
  observer?.disconnect();
  unmount();
});
</script>

<template>
  <div ref="host" class="poi fig-host"></div>
</template>
