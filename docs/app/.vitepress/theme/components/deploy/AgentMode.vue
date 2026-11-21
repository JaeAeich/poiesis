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
