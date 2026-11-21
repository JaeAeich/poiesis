<script setup>
import { AUTHZ_MODES } from "../../../lib/deploy/config.js";
import { FIELDS } from "../../../lib/deploy/fields.js";
import { useDeploy } from "../../../lib/deploy/store.js";
import ConfigField from "../ConfigField.vue";
import SegmentedControl from "../SegmentedControl.vue";
import StepActions from "../StepActions.vue";
import StepIntro from "../StepIntro.vue";

defineProps({ step: { type: Number, required: true } });
const { config } = useDeploy();
</script>

<template>
  <StepIntro
    text="What a caller may do once authenticated. By default, everyone sees only their own tasks."
  />
  <SegmentedControl v-model="config.authzMode" label="Authorization" :options="AUTHZ_MODES" />
  <template v-if="config.authzMode === 'decision-service'">
    <ConfigField :field="FIELDS.decisionServiceUrl" />
    <label class="check">
      <input
        type="checkbox"
        :checked="config.sharing"
        @input="config.sharing = $event.target.checked"
      />
      <span>Let the policy share tasks<small>With groups, teams or everyone.</small></span>
    </label>
  </template>
  <div class="row2">
    <ConfigField :field="FIELDS.userGroup" />
    <ConfigField v-if="config.authzMode === 'owner'" :field="FIELDS.adminGroup" />
  </div>
  <StepActions :step="step" />
</template>
