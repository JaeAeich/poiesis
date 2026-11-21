<script setup>
import { FIELDS } from "../../../lib/deploy/fields.js";
import ConfigField from "../ConfigField.vue";
import StepActions from "../StepActions.vue";
import StepIntro from "../StepIntro.vue";

defineProps({ step: { type: Number, required: true } });
</script>

<template>
  <StepIntro text="Each task gets its own volume, deleted with the task." />
  <div class="row2">
    <ConfigField :field="FIELDS.defaultSizeGi" />
    <ConfigField :field="FIELDS.maxSizeGi" />
  </div>
  <div class="row2">
    <ConfigField :field="FIELDS.storageClass" />
    <ConfigField :field="FIELDS.retainSeconds" />
  </div>
  <StepActions :step="step" />
</template>
