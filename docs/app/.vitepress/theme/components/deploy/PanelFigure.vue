<script setup>
// The animated figure in the "How it works" panel; it stops when the panel closes.
import { onMounted, onUnmounted, ref, watch } from "vue";
import { flow, taskFigure } from "../../lib/figures.js";

const props = defineProps({
  /** @type {import("vue").PropType<import("../../lib/deploy/explain.js").ExplainSpec>} */
  spec: { type: Object, required: true },
  active: { type: Boolean, required: true },
});

const host = ref(null);
let stop = () => {};

onMounted(() => {
  stop = props.spec.taskFigure
    ? taskFigure(host.value, { compact: true })
    : flow(host.value, props.spec);
});
watch(
  () => props.active,
  (active) => {
    if (!active) stop();
  },
);
onUnmounted(() => stop());
</script>

<template>
  <div id="pfig" ref="host"></div>
</template>
