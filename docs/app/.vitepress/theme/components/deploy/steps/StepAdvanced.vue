<script setup>
import { isAdvancedChanged, liveAdvancedGroups } from "../../../lib/deploy/advanced.js";
import { useDeploy } from "../../../lib/deploy/store.js";
import StepActions from "../StepActions.vue";
import StepIntro from "../StepIntro.vue";
import AdvancedField from "./AdvancedField.vue";

defineProps({ step: { type: Number, required: true } });
const { config, wizard } = useDeploy();

// Which group starts open (set by review links); afterwards each group opens and closes freely.
const initiallyOpen = wizard.openAdvancedGroup;

const changedCount = (group) =>
  group.items.filter((item) => isAdvancedChanged(config, item)).length;

function onToggle(name, event) {
  if (event.target.open) wizard.openAdvancedGroup = name;
  else if (wizard.openAdvancedGroup === name) wizard.openAdvancedGroup = null;
}
</script>

<template>
  <StepIntro text="Everything else. Each value keeps the chart default unless you change it." />
  <details
    v-for="group in liveAdvancedGroups(config)"
    :key="group.name"
    class="adv-group"
    :open="group.name === initiallyOpen"
    @toggle="onToggle(group.name, $event)"
  >
    <summary>
      {{ group.name
      }}<small>{{ changedCount(group) ? `${changedCount(group)} changed` : "defaults" }}</small>
    </summary>
    <div class="in">
      <AdvancedField v-for="item in group.items" :key="item.key" :item="item" />
    </div>
  </details>
  <StepActions :step="step" />
</template>

<style scoped>
/* collapsible groups with a chevron */
.poi .adv-group {
  border: 1px solid var(--line);
  border-radius: 8px;
  margin-bottom: 10px;
  background: var(--bg);
}
.poi .adv-group > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  font-weight: 500;
  color: var(--fg);
  font-size: 15px;
}
.poi .adv-group > summary::-webkit-details-marker {
  display: none;
}
.poi .adv-group > summary::before {
  content: "";
  width: 7px;
  height: 7px;
  border-right: 1.5px solid var(--muted);
  border-bottom: 1.5px solid var(--muted);
  transform: rotate(-45deg);
  transition: transform 0.2s;
}
.poi .adv-group[open] > summary::before {
  transform: rotate(45deg);
}
.poi .adv-group > summary small {
  margin-left: auto;
  font: 12px var(--mono);
  color: var(--muted);
  font-weight: 400;
}
.poi .adv-group .in {
  padding: 4px 14px 6px;
}
</style>
