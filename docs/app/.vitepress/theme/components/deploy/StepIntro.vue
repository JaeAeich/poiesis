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

<style scoped>
.poi .why {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
  margin: 0 0 18px;
  font-size: 15px;
}
.poi .why p {
  margin: 0;
}
.poi .explain-btn {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 999px;
  padding: 3px 10px 3px 8px;
  font-size: 13px;
  color: var(--blue-ink);
}
.poi .explain-btn:hover {
  border-color: var(--blue);
}
.poi .explain-btn svg {
  width: 14px;
  height: 14px;
}
</style>
