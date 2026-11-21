<script setup>
// Line icons used across the configurator (24x24, stroked with currentColor).
import { computed } from "vue";

const ICONS = {
  x: { strokeWidth: 2, shapes: [["path", { d: "M6 6l12 12M18 6 6 18" }]] },
  play: {
    strokeWidth: 2,
    shapes: [
      ["circle", { cx: 12, cy: 12, r: 9 }],
      ["path", { d: "M10 8.5v7l5.5-3.5z", fill: "currentColor" }],
    ],
  },
  copy: {
    strokeWidth: 1.75,
    shapes: [
      ["rect", { x: 9, y: 9, width: 11, height: 11, rx: 2 }],
      ["path", { d: "M5 15V5a1 1 0 0 1 1-1h9" }],
    ],
  },
  file: {
    strokeWidth: 1.75,
    shapes: [
      ["path", { d: "M14 3H6v18h12V7z" }],
      ["path", { d: "M14 3v4h4" }],
    ],
  },
  download: { strokeWidth: 1.75, shapes: [["path", { d: "M12 4v11M7 10l5 5 5-5M5 20h14" }]] },
  check: { strokeWidth: 2.5, shapes: [["path", { d: "M5 12l5 5 9-10" }]] },
  cross: { strokeWidth: 2.5, shapes: [["path", { d: "M6 6l12 12M18 6 6 18" }]] },
};

const props = defineProps({
  name: { type: String, required: true },
});
const icon = computed(() => ICONS[props.name]);
</script>

<template>
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="icon.strokeWidth"
    aria-hidden="true"
  >
    <component :is="tag" v-for="([tag, attrs], index) in icon.shapes" :key="index" v-bind="attrs" />
  </svg>
</template>
