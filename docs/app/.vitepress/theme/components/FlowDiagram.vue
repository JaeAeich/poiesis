<script setup>
// An animated flow diagram, authored in Markdown:
// <FlowDiagram :spec="{ title, h?, nodes: { id: { x, y, w?, label, sub? } }, edges: [[a, b]],
//   hops: [{ f, t, label, cap, tone? }] }" />
// See lib/figures/flowGeometry.js for the spec's shape.
import { onMounted, onUnmounted, ref } from "vue";
import { mountFlowDiagram } from "../lib/figures/flowDiagram.js";

/** Hosts at least this wide get the stretched canvas, px. */
const WIDE_HOST = 600;

const props = defineProps({
  /** @type {import("vue").PropType<import("../lib/figures/flowGeometry.js").FlowSpec>} */
  spec: { type: Object, required: true },
});

const host = ref(null);
let unmount = () => {};

onMounted(() => {
  unmount = mountFlowDiagram(host.value, props.spec, { wide: host.value.clientWidth >= WIDE_HOST });
});
onUnmounted(() => unmount());
</script>

<template>
  <div ref="host" class="poi fig-host"></div>
</template>
