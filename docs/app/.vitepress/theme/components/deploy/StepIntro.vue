<script setup>
// The line at the top of each step, with the "How it works" button.
import { useDeploy } from "../../lib/deploy/store.js";
import DeployIcon from "./DeployIcon.vue";

defineProps({
  text: { type: String, required: true },
});
const { openExplain } = useDeploy();
</script>

<template>
  <div class="why">
    <p>{{ text }}</p>
    <button class="explain-btn" @click="openExplain()">
      <DeployIcon name="play" />How it works
    </button>
  </div>
</template>
