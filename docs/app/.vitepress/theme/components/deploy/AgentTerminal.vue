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

<style scoped>
.poi .term {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--code-bg);
  overflow: hidden;
  box-shadow: var(--shadow);
}
.poi .term .th {
  display: flex;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--bg);
  font: 12px var(--mono);
  color: var(--muted);
}
.poi .term .tb {
  padding: 16px 18px;
  font: 13px/1.8 var(--mono);
  height: 420px;
  overflow: hidden;
  color: var(--code-fg);
}
@media (max-width: 760px) {
  .poi .term .tb {
    height: 340px;
  }
}

/* line kinds (lib/deploy/agent-session.js): user, reading, question, result, command */
.poi .term .l {
  white-space: pre-wrap;
  opacity: 0;
  animation: tr 0.25s var(--ease) forwards;
}
.poi .term .u {
  color: var(--fg);
  margin-top: 6px;
}
.poi .term .u::before {
  content: "› ";
  color: var(--coral);
}
.poi .term .r {
  color: var(--muted);
}
.poi .term .r::before {
  content: "· ";
}
.poi .term .q {
  color: var(--blue-ink);
  margin-top: 6px;
}
.poi .term .ok::before {
  content: "✓ ";
  color: var(--blue);
}
.poi .term .c2 {
  color: var(--fg);
  margin-top: 6px;
}
.poi .term .c2::before {
  content: "$ ";
  color: var(--muted);
}
</style>
