<script setup>
// A review line that links back to the step (and field) to fix.
import { useDeploy } from "../../../lib/deploy/store.js";

defineProps({
  /** @type {import("vue").PropType<import("../../../lib/deploy/validation.js").ReviewTarget>} */
  entry: { type: Object, required: true },
  action: { type: String, required: true },
  /** Current example value, shown highlighted. */
  value: { type: String, default: "" },
});
const { goToStep } = useDeploy();
</script>

<template>
  <li>
    <span class="d" style="color: var(--fg)">{{ entry.label }}</span>
    <span v-if="value" class="v rv-ex">{{ value }}</span>
    <button class="btn ghost sm go" @click="goToStep(entry.step, entry.focusId)">
      {{ action }}
    </button>
  </li>
</template>
