<script setup>
// Continue / Review, and "Use example values" for steps that have them.
import { stepHasExamples } from "../../lib/deploy/examples.js";
import { STEP } from "../../lib/deploy/steps.js";
import { useDeploy } from "../../lib/deploy/store.js";

const props = defineProps({
  step: { type: Number, required: true },
});
const deploy = useDeploy();

function useExamples() {
  deploy.fillStepExample(props.step);
  deploy.advance();
}
</script>

<template>
  <div class="acts">
    <button class="btn primary sm" @click="deploy.advance()">
      {{ step === STEP.ADVANCED ? "Review" : "Continue" }}
    </button>
    <button v-if="stepHasExamples(step)" class="btn sm" @click="useExamples">
      Use example values
    </button>
  </div>
</template>
