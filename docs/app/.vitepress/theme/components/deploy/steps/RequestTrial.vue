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
