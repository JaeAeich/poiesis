<script setup>
// "With an agent": the prompt to paste into a coding agent, and an example session.
import { AGENT_PROMPT } from "../../lib/deploy/agent-session.js";
import AgentTerminal from "./AgentTerminal.vue";
import CopyButton from "./CopyButton.vue";
</script>

<template>
  <div class="agent">
    <div>
      <ol class="howto">
        <li>
          <span
            ><b>Copy the prompt</b>It points your agent at the docs and tells it what to ask.</span
          >
        </li>
        <li>
          <span
            ><b>Paste it into your coding agent</b>Claude Code, Codex, Cursor, or any agent that can
            run commands.</span
          >
        </li>
        <li>
          <span
            ><b>Answer its questions</b>It writes <code>values.yaml</code>, lists the Secrets to
            create and gives you the install command.</span
          >
        </li>
      </ol>
      <div id="agent-prompt" class="prompt">
        {{ AGENT_PROMPT }}<CopyButton class="btn sm copy" :text="AGENT_PROMPT">Copy</CopyButton>
      </div>
    </div>
    <AgentTerminal />
  </div>
</template>

<style scoped>
.poi .agent {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 48px;
  padding: 40px 0 96px;
  align-items: start;
}
@media (max-width: 760px) {
  .poi .agent {
    grid-template-columns: 1fr;
    gap: 28px;
  }
}

/* numbered how-to */
.poi .howto {
  list-style: none;
  counter-reset: h;
  margin: 0 0 24px;
  padding: 0;
  display: grid;
  gap: 18px;
}
.poi .howto li {
  counter-increment: h;
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 12px;
  font-size: 15px;
  color: var(--body);
}
.poi .howto li::before {
  content: counter(h);
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  display: grid;
  place-items: center;
  font: 500 12px var(--mono);
  color: var(--fg);
}
.poi .howto b {
  display: block;
  color: var(--fg);
  font-weight: 500;
  margin-bottom: 2px;
}

/* the prompt to copy */
.poi .prompt {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--code-bg);
  padding: 14px 16px;
  font: 13.5px/1.65 var(--mono);
  color: var(--code-fg);
  white-space: pre-wrap;
}
.poi .prompt .copy {
  position: absolute;
  top: 8px;
  right: 8px;
}
</style>
