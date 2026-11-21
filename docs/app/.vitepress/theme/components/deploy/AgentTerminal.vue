<script setup>
// The example agent session, typed out while the agent view is showing.
import { onMounted, onUpdated, ref } from "vue";
import { AGENT_SESSION } from "../../lib/deploy/agent-session.js";
import { useDeploy } from "../../lib/deploy/store.js";
import { useTypedTerminal } from "../../lib/deploy/use-typed-terminal.js";

const { ui } = useDeploy();
const body = ref(null);
const { lines, showAll, start } = useTypedTerminal(AGENT_SESSION, {
  isActive: () => ui.mode === "agent",
  reducedMotion: () => ui.reducedMotion,
});

onMounted(() => {
  if (ui.mode === "agent") start();
});
// follow the newest line while typing; the reduced-motion transcript stays at the top
onUpdated(() => {
  if (body.value && !showAll.value) body.value.scrollTop = body.value.scrollHeight;
});
</script>

<template>
  <div class="term">
    <div class="th"><span>agent session</span><span>example</span></div>
    <div id="term-b" ref="body" class="tb">
      <div
        v-for="line in lines"
        :key="line.key"
        class="l"
        :class="line.kind"
        :style="showAll ? { opacity: 1, animation: 'none' } : undefined"
      >
        {{ line.text }}
      </div>
    </div>
  </div>
</template>
