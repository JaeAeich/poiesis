<script setup>
// The accordion of steps; only the open step renders its body.
import { STEPS } from "../../lib/deploy/steps.js";
import { useDeploy } from "../../lib/deploy/store.js";
import StepAdvanced from "./steps/StepAdvanced.vue";
import StepAuthentication from "./steps/StepAuthentication.vue";
import StepAuthorization from "./steps/StepAuthorization.vue";
import StepBasics from "./steps/StepBasics.vue";
import StepDatabase from "./steps/StepDatabase.vue";
import StepReview from "./steps/StepReview.vue";
import StepStorage from "./steps/StepStorage.vue";
import StepVolumes from "./steps/StepVolumes.vue";

const BODIES = {
  basics: StepBasics,
  database: StepDatabase,
  storage: StepStorage,
  volumes: StepVolumes,
  authentication: StepAuthentication,
  authorization: StepAuthorization,
  advanced: StepAdvanced,
  review: StepReview,
};

const { config, wizard, goToStep } = useDeploy();
const isDone = (index) => wizard.completed.has(index) && index !== wizard.step;
</script>

<template>
  <ol id="steps" class="steps">
    <li
      v-for="(step, index) in STEPS"
      :key="step.id"
      class="step"
      :class="{ cur: index === wizard.step, done: isDone(index) }"
    >
      <h2 class="hd-h">
        <button
          class="hd"
          :aria-expanded="String(index === wizard.step)"
          :aria-controls="`bd-${index}`"
          @click="goToStep(index)"
        >
          <span class="n">{{ isDone(index) ? "✓" : index + 1 }}</span>
          <span class="ttl">{{ step.title }}</span>
          <span v-if="step.optional" class="opt">optional</span>
          <span class="sum">{{ index === wizard.step ? "" : step.summary(config) }}</span>
        </button>
      </h2>
      <div :id="`bd-${index}`" class="bd">
        <component :is="BODIES[step.id]" v-if="index === wizard.step" :step="index" />
      </div>
    </li>
  </ol>
</template>
