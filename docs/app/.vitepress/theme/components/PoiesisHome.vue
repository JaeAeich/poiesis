<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { withBase } from "vitepress";
import TaskFigure from "./TaskFigure.vue";
import { mountHome } from "../lib/home.js";

const NF = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#0DC09D" d="M.005 4.424V0c6.228.259 11.227 5.268 11.477 11.506H7.058C6.828 7.715 3.786 4.673.005 4.424m7.082 8.089h4.424C11.251 18.741 6.242 23.741.005 23.99v-4.423c3.79-.231 6.832-3.273 7.082-7.054m9.826-1.036h-4.424C12.749 5.249 17.758.25 23.995 0v4.424c-3.79.23-6.832 3.263-7.082 7.053m7.082 8.099V24c-6.228-.259-11.227-5.268-11.477-11.506h4.424c.23 3.791 3.272 6.833 7.053 7.082"/></svg>';
const CWL = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M13.905 0L8.571 5.4l.037.037.096.096 3.586 3.395-2.24 2.252h-.01l-1.576 1.586 3.737 3.766-3.735 3.803.126.139v.012L12.052 24l1.608-1.64-1.98-2.034 3.737-3.79-1.608-1.642-.01.012-2.13-2.129 3.867-3.866-.017-.015.016-.016-3.641-3.524 3.64-3.694z"/></svg>';
const img = (f, cls = "") => `<img ${cls ? `class="${cls}" ` : ""}src="${withBase("/logos/" + f)}" alt="">`;
// Status is only what we have run end to end; keep it honest.
const engines = [
  { name: "Nextflow", detail: "nf-ga4gh 1.5.0", st: "", label: "Tested · 25.10.4", logo: NF, size: 96 },
  { name: "Snakemake", detail: "TES executor 0.1.3", st: "", label: "Tested · 9.27.2", logo: img("snakemake.svg"), size: 88 },
  { name: "py-tes", detail: "GA4GH Python client", st: "", label: "Tested · 1.1.4", logo: img("ga4gh.png"), size: 76 },
  { name: "TES compliance suite", detail: "GA4GH conformance tests", st: "", label: "Passing", logo: img("ga4gh.png"), size: 70 },
  { name: "Sprocket", detail: "WDL · 0.34.1, two workarounds for now", st: "part", label: "Partly tested", logo: img("sprocket.png", "crop"), size: 80 },
  { name: "cwl-tes", detail: "API key as Basic password", st: "part", label: "Partly tested", logo: CWL, size: 68 },
  { name: "Cromwell", detail: "WDL", st: "no", label: "Not tested yet", logo: img("cromwell.png"), size: 82 },
  { name: "Toil", detail: "CWL, WDL", st: "no", label: "Not tested yet", logo: img("toil.svg"), size: 72 },
];
const ISSUE = "https://github.com/JaeAeich/poiesis/issues/new?title=Engine%20support%3A%20&body=Engine%20and%20version%3A%0ALink%3A%0AWhat%20you%20tried%3A";
const root = ref(null);
let stop = () => {};
onMounted(() => { stop = mountHome(root.value); });
onUnmounted(() => stop());
</script>

<template>
  <div ref="root" class="poi poi-home">
    <div class="stage layer" id="stage">
      <canvas id="bg" class="li" aria-hidden="true"></canvas>
      <div class="wrap hero li" id="hero">
        <div class="copy reveal" id="copy">
          <h1>Science at <em>cluster scale.</em></h1>
          <p>Poiesis is a GA4GH Task Execution Service for Kubernetes. Point your workflow engine at it, and every task runs in its own Pod.</p>
          <div class="actions" id="hero-actions">
            <a class="btn primary" :href="withBase('/deploy')">Deploy <svg class="arr" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6"/></svg></a>
            <a class="btn" :href="withBase('/docs/start/what-is-poiesis')">Docs</a>
          </div>
        </div>
        <div class="wheel-wrap">
          <div class="wheel" id="wheel" role="slider" tabindex="0" aria-label="The Poiesis wheel. Drag or use the arrow keys to turn it." aria-valuemin="0" aria-valuemax="360" aria-valuenow="0"></div>
        </div>
      </div>
    </div>

    <div class="sheet layer" id="s-eng">
      <div class="wrap li">
        <div class="eng-center" id="eng-center">
          <div class="intro"><h2>Bring the engine <em>you already use.</em></h2></div>
          <ul class="eng">
            <li v-for="(e, i) in engines" :key="e.name" :class="e.st" :data-i="i">
              <span class="ic" v-html="e.logo"></span>
              <span class="nm">{{ e.name }}<small>{{ e.detail }}</small></span>
              <span class="st" :class="e.st">{{ e.label }}</span>
            </li>
            <li class="ask" :data-i="engines.length">
              <span class="ic">?</span>
              <span class="nm">Using another engine?<small>Ask us to test it, or send a PR with the setup</small></span>
              <a class="btn sm" :href="ISSUE" target="_blank" rel="noopener">Open an issue</a>
            </li>
          </ul>
        </div>
      </div>
      <div class="field" id="eng-field" aria-hidden="true">
        <span v-for="(e, i) in engines" :key="e.name" class="pl" :class="e.st" :data-i="i" :data-s="e.size" :style="{ '--s': e.size + 'px' }" :title="e.name + ': ' + e.label" v-html="e.logo"></span>
        <a class="pl ask" :data-i="engines.length" data-s="66" style="--s:66px" tabindex="-1" target="_blank" rel="noopener" :href="ISSUE" title="Using another engine? Ask us to test it">?</a>
      </div>
    </div>

    <div class="sheet layer" id="s-task">
      <div class="wrap li">
        <div class="intro"><h2>How a task <em>runs.</em></h2></div>
        <div class="figwrap"><TaskFigure /></div>
        <div class="facts">
          <div><h3>Standard</h3><p>GA4GH TES v1.1. Engines that speak TES need no changes.</p></div>
          <div><h3>Verbatim</h3><p>Your image and command, as submitted. No injected libraries; only <code>ignore_error</code> adds a <code>/bin/sh</code> wrapper.</p></div>
          <div><h3>Yours to secure</h3><p>OIDC issuers, gateway tokens, API keys and an optional policy engine.</p></div>
        </div>
      </div>
    </div>
  </div>
</template>
