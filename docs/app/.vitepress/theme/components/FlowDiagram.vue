<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { flow } from "../lib/figures.js";

// spec: { title, h?, nodes: { id: { x, y, w?, label, sub? } }, edges: [[a, b]], hops: [{ f, t, label, cap, tone? }] }
const props = defineProps({ spec: { type: Object, required: true } });
const host = ref(null);
let stop = () => {};
onMounted(() => { stop = flow(host.value, props.spec, { wide: true }) || (() => {}); });
onUnmounted(() => stop());
</script>

<template>
  <div ref="host" class="poi fig-host"></div>
</template>
