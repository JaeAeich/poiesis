<script setup>
import { FIELDS } from "../../../lib/deploy/fields.js";
import ConfigField from "../ConfigField.vue";
import StepActions from "../StepActions.vue";
import StepIntro from "../StepIntro.vue";

defineProps({ step: { type: Number, required: true } });
</script>

<template>
  <StepIntro
    text="Poiesis stores tasks in Postgres. You create the Secret; the chart never does."
  />
  <ConfigField :field="FIELDS.databaseSecret" />
  <ConfigField :field="FIELDS.databaseCaConfigMap" />
  <StepActions :step="step" />
</template>
