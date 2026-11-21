<script setup>
// Hand-drawn diagrams that follow the site theme (light and dark) instead of rendered Mermaid
// images: <PoiDiagram name="overview" />, "taskpod" or "lifecycle". The drawings are described
// in lib/diagrams/.
import { computed } from "vue";
import { DIAGRAMS } from "../lib/diagrams/index.js";

const props = defineProps({
  name: { type: String, required: true, validator: (name) => name in DIAGRAMS },
});

const diagram = computed(() => DIAGRAMS[props.name]);
</script>

<template>
  <figure class="poi-diagram">
    <svg :viewBox="diagram.viewBox" role="img" :aria-label="diagram.label">
      <defs>
        <marker
          id="pd-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0 0L10 5L0 10z" class="ah" />
        </marker>
      </defs>
      <component :is="item.tag" v-for="(item, i) in diagram.nodes" :key="i" v-bind="item.attrs">
        <template v-if="item.text">{{ item.text }}</template>
        <component
          :is="child.tag"
          v-for="(child, j) in item.children"
          :key="j"
          v-bind="child.attrs"
        >
          <template v-if="child.text">{{ child.text }}</template>
        </component>
      </component>
    </svg>
  </figure>
</template>

<style scoped>
/* frame */
.poi-diagram {
  margin: 24px 0;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  padding: 12px;
  overflow-x: auto;
}
.poi-diagram svg {
  display: block;
  width: 100%;
  height: auto;
  min-width: 560px;
}

/* boxes: plain, your code (hot), sidecar (side), client (pill), group frame, volume, note */
.poi-diagram .bx rect,
.poi-diagram .bx path,
.poi-diagram .bx ellipse {
  fill: var(--bg);
  stroke: var(--line-strong);
  stroke-width: 1.2;
}
.poi-diagram .bx.hot rect {
  fill: var(--coral-wash);
  stroke: var(--coral);
}
.poi-diagram .bx.side rect {
  fill: var(--blue-wash);
  stroke: var(--blue);
}
.poi-diagram .bx.pill rect {
  stroke: var(--blue);
}
.poi-diagram .grp rect {
  fill: none;
  stroke: var(--blue);
  stroke-width: 1.3;
  stroke-dasharray: 5 4;
}
.poi-diagram .vol rect {
  fill: var(--bg);
  stroke: var(--blue);
  stroke-opacity: 0.6;
}
.poi-diagram .note rect {
  fill: var(--bg);
  stroke: var(--line-strong);
  stroke-dasharray: 3 3;
}

/* text: title, sub line, group label, edge label */
.poi-diagram text {
  font-family: var(--mono);
  text-anchor: middle;
}
.poi-diagram .t {
  font-size: 12.5px;
  font-weight: 500;
  fill: var(--fg);
}
.poi-diagram .s {
  font-size: 10.5px;
  fill: var(--muted);
}
.poi-diagram .gl {
  font-size: 11.5px;
  fill: var(--blue-ink);
  text-anchor: start;
  font-weight: 500;
}
.poi-diagram .gl.sm {
  fill: var(--muted);
  font-weight: 400;
  font-size: 10.5px;
}
.poi-diagram .lb {
  font-size: 10.5px;
  fill: var(--body);
  paint-order: stroke;
  stroke: var(--surface);
  stroke-width: 5px;
  stroke-linejoin: round;
}
.poi-diagram .lb.l {
  text-anchor: start;
}

/* arrows, lanes and step numbers */
.poi-diagram .ar {
  fill: none;
  stroke: var(--muted);
  stroke-width: 1.2;
}
.poi-diagram .ar.dash {
  stroke-dasharray: 4 3;
}
.poi-diagram .ah {
  fill: var(--muted);
}
.poi-diagram .lane {
  stroke: var(--line-strong);
  stroke-dasharray: 2 4;
}
.poi-diagram .num circle {
  fill: var(--coral);
}
.poi-diagram .num text {
  font-size: 9.5px;
  font-weight: 600;
  fill: #0d2033;
}
</style>
