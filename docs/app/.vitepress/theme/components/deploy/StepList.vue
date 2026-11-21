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

<style scoped>
/* a vertical rail of numbered steps; the current one is open */
.poi .steps {
  list-style: none;
  margin: 0;
  padding: 0;
  border-left: 1px solid var(--line);
}
.poi .step {
  position: relative;
  padding: 0 0 6px 28px;
}
.poi .hd-h {
  margin: 0;
  font: inherit;
}
.poi .step .hd {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  border: 0;
  background: none;
  padding: 10px 0;
  text-align: left;
  color: var(--body);
}
.poi .step .hd .n {
  position: absolute;
  left: -12px;
  width: 23px;
  height: 23px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font: 500 11px var(--mono);
  background: var(--bg);
  border: 1px solid var(--line-strong);
  color: var(--muted);
  transition:
    background-color 0.25s,
    border-color 0.25s,
    color 0.25s,
    box-shadow 0.25s;
}
.poi .step .hd .ttl {
  font-weight: 500;
  font-size: 16px;
}
.poi .step .hd .opt {
  font: 11.5px var(--mono);
  color: var(--muted);
}
.poi .step .hd .sum {
  margin-left: auto;
  font: 12.5px var(--mono);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 50%;
}
.poi .step.done .hd .n {
  background: var(--blue);
  border-color: var(--blue);
  color: var(--bg);
}
.poi .step.cur .hd .n {
  border-color: var(--coral);
  color: var(--coral-ink);
  box-shadow: 0 0 0 4px var(--coral-wash);
}
.poi .step.cur .hd .ttl {
  color: var(--fg);
}
.poi .step .bd {
  display: none;
  padding: 0 0 22px;
}
.poi .step.cur .bd {
  display: block;
  animation: in 0.3s var(--ease);
}
@media (max-width: 760px) {
  .poi .step .hd .sum {
    display: none;
  }
}
</style>
