<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { withBase } from "vitepress";
import { mountDeploy } from "../lib/deploy.js";

const root = ref(null);
let stop = () => {};
onMounted(() => { stop = mountDeploy(root.value, withBase("/")); });
onUnmounted(() => stop());
</script>

<template>
  <main ref="root" class="poi poi-deploy">
  <div class="wrap">
    <div class="dhead">
      <div><h1>Deploy Poiesis</h1><p class="dsub">You bring a cluster, Postgres, an S3 bucket and an OIDC issuer. You get a values.yaml and the commands to install it.</p></div>
      <div class="right">
        <button class="btn sm" id="fill-all">Show an example file</button>
        <div class="seg2 big" role="group" aria-label="How to deploy"><button data-mode="human" class="on" aria-pressed="true">Step by step</button><button data-mode="agent" aria-pressed="false">With an agent</button></div>
      </div>
    </div>
    <div id="mode-human">
    <div class="cfg">
      <ol class="steps" id="steps"></ol>
      <div class="file">
        <div class="fh">
          <button class="tab on" data-tab="values" aria-pressed="true">values.yaml</button>
          <button class="tab" data-tab="install" aria-pressed="false">install.sh</button>
          <div class="sp">
            <button class="btn sm edit-btn" id="edit-btn" aria-pressed="false">Edit</button>
            <button class="icon-btn" id="copy-file" aria-label="Copy file"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h9"/></svg></button>
            <button class="icon-btn" id="dl-file" aria-label="Download file"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg></button>
          </div>
        </div>
        <div class="banner" id="banner"><span>Edited by hand. The form no longer changes this file.</span><button class="btn sm" id="regen">Discard edits</button></div>
        <div class="ed" id="ed"><pre id="code"></pre><textarea id="ta" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="values.yaml"></textarea></div>
        <div class="ff"><span class="legend">example value, replace</span><span id="file-meta"></span></div>
      </div>
    </div>
    </div>
    <div id="mode-agent" hidden>
      <div class="agent">
        <div>
          <ol class="howto">
            <li><span><b>Copy the prompt</b>It points your agent at the docs and tells it what to ask.</span></li>
            <li><span><b>Paste it into your coding agent</b>Claude Code, Codex, Cursor, or any agent that can run commands.</span></li>
            <li><span><b>Answer its questions</b>It writes <code>values.yaml</code>, lists the Secrets to create and gives you the install command.</span></li>
          </ol>
          <div class="prompt" id="agent-prompt">Deploy Poiesis on my Kubernetes cluster.
Read https://poiesis.jaeaeich.com/llms.txt first.
Ask me about my database, object storage and
identity provider, then write values.yaml and
the helm install command. Tell me which
Secrets to create; don't create them.<button class="btn sm copy" data-copy="agent-prompt">Copy</button></div>
        </div>
        <div class="term"><div class="th"><span>agent session</span><span>example</span></div><div class="tb" id="term-b"></div></div>
      </div>
    </div>
  </div>
<div class="scrim" id="scrim"></div>
<aside class="panel" id="panel" role="dialog" aria-modal="true" aria-labelledby="panel-title">
  <div class="grab"></div>
  <div class="ph"><span class="eyebrow" id="panel-step"></span><h2 id="panel-title"></h2><button class="icon-btn x" id="panel-x" aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>
  <div class="pb" id="panel-body"></div>
</aside>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
  </main>
</template>
