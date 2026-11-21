<script setup>
// "Try a request": replays how the chain treats a sample credential, one line at a time.
import { TRIAL_OPTIONS, trialSymbol } from "../../../lib/deploy/trials.js";
import { useDeploy } from "../../../lib/deploy/store.js";

const LINE_STAGGER_MS = 140;
const { ui, wizard, tryRequest } = useDeploy();
const delay = (position) => `${ui.reducedMotion ? 0 : position * LINE_STAGGER_MS}ms`;
</script>

<template>
  <div class="tryit">
    <div class="eyebrow">Try a request</div>
    <div class="opts">
      <button
        v-for="[kind, label] in TRIAL_OPTIONS"
        :key="kind"
        :class="{ on: wizard.trial?.kind === kind }"
        @click="tryRequest(kind)"
      >
        {{ label }}
      </button>
    </div>
    <ol class="trace">
      <template v-if="wizard.trial">
        <li
          v-for="(line, position) in wizard.trial.steps"
          :key="`${wizard.trial.run}-${position}`"
          :class="line.tone"
          :style="{ animationDelay: delay(position) }"
        >
          <span class="s">{{ trialSymbol(line.tone) }}</span>
          <span
            ><b v-if="line.strong">{{ line.strong }}</b
            >{{ line.text }}</span
          >
        </li>
      </template>
      <li v-else style="opacity: 1; animation: none" class="muted">
        <span class="s">›</span>Pick one to see how the chain handles it.
      </li>
    </ol>
  </div>
</template>

<style scoped>
.poi .tryit {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: var(--surface);
  margin-bottom: 16px;
}
.poi .tryit .eyebrow {
  margin-bottom: 10px;
}
.poi .tryit .opts {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.poi .tryit .opts button {
  border: 1px solid var(--line-strong);
  background: var(--bg);
  border-radius: 999px;
  padding: 4px 12px;
  font: 12.5px var(--mono);
  color: var(--body);
}
.poi .tryit .opts button.on {
  border-color: var(--blue);
  color: var(--blue-ink);
  background: var(--blue-wash);
}

/* the trace types in line by line */
.poi .trace {
  list-style: none;
  margin: 0;
  padding: 0;
  font: 13px/1.5 var(--mono);
}
.poi .trace li {
  display: flex;
  gap: 10px;
  padding: 3px 0;
  opacity: 0;
  transform: translateX(-4px);
  animation: tr 0.3s var(--ease) forwards;
}
.poi .trace li .s {
  width: 14px;
  flex: none;
  color: var(--blue);
}
.poi .trace li.bad {
  color: var(--coral-ink);
}
.poi .trace li.bad .s {
  color: var(--coral-ink);
}
.poi .trace li.ok b {
  color: var(--blue-ink);
}
</style>
