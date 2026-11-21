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
