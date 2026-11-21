<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { withBase } from "vitepress";
import TaskFigure from "./TaskFigure.vue";
import EngineLogo from "./EngineLogo.vue";
import { mountHome } from "../lib/home.js";
import { ASK_BUBBLE_SIZE, ENGINES, ENGINE_REQUEST_URL } from "../lib/home/engineList.js";

const engineGuide = (engine) => withBase("/docs/guides/workflow-engines#" + engine.doc);

const root = ref(null);
let unmount = () => {};
onMounted(() => {
  unmount = mountHome(root.value);
});
onUnmounted(() => unmount());
</script>

<template>
  <main ref="root" class="poi poi-home">
    <div class="stage layer" id="stage">
      <canvas id="bg" class="li" aria-hidden="true"></canvas>
      <div class="wrap hero li" id="hero">
        <div class="copy reveal" id="copy">
          <h1>Science at <em>cluster scale.</em></h1>
          <p>
            Poiesis is a GA4GH Task Execution Service for Kubernetes. Point your workflow engine at
            it, and every task runs in its own Pod.
          </p>
          <div class="actions" id="hero-actions">
            <a class="btn primary" :href="withBase('/deploy')"
              >Deploy
              <svg
                class="arr"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                aria-hidden="true"
              >
                <path d="M5 12h14M13 6l6 6-6 6" /></svg
            ></a>
            <a class="btn" :href="withBase('/docs/start/what-is-poiesis')">Docs</a>
          </div>
        </div>
        <div class="wheel-wrap">
          <div
            class="wheel"
            id="wheel"
            role="slider"
            tabindex="0"
            aria-label="The Poiesis wheel. Drag or use the arrow keys to turn it."
            aria-valuemin="0"
            aria-valuemax="360"
            aria-valuenow="0"
          ></div>
        </div>
      </div>
    </div>

    <div class="sheet layer" id="s-eng">
      <div class="wrap li">
        <div class="eng-center" id="eng-center">
          <div class="intro">
            <h2>Bring the engine <em>you already use.</em></h2>
          </div>
          <ul class="eng">
            <li
              v-for="(engine, i) in ENGINES"
              :key="engine.name"
              :class="engine.status"
              :data-i="i"
            >
              <span class="ic"><EngineLogo :logo="engine.logo" /></span>
              <span class="nm">
                <a class="row-link" :href="engineGuide(engine)">{{ engine.name }}</a
                ><small>{{ engine.detail }}</small>
              </span>
              <span class="st" :class="engine.status">{{ engine.label }}</span>
            </li>
            <li class="ask" :data-i="ENGINES.length">
              <span class="ic">?</span>
              <span class="nm"
                >Using another engine?<small
                  >Ask us to test it, or send a PR with the setup</small
                ></span
              >
              <a class="btn sm" :href="ENGINE_REQUEST_URL" target="_blank" rel="noopener"
                >Open an issue</a
              >
            </li>
          </ul>
        </div>
      </div>
      <div class="field" id="eng-field" aria-hidden="true">
        <a
          v-for="(engine, i) in ENGINES"
          :key="engine.name"
          class="pl"
          :class="engine.status"
          :data-i="i"
          :data-s="engine.size"
          :style="{ '--s': engine.size + 'px' }"
          :title="engine.name + ': ' + engine.label"
          :href="engineGuide(engine)"
          tabindex="-1"
          ><EngineLogo :logo="engine.logo"
        /></a>
        <a
          class="pl ask"
          :data-i="ENGINES.length"
          :data-s="ASK_BUBBLE_SIZE"
          :style="{ '--s': ASK_BUBBLE_SIZE + 'px' }"
          tabindex="-1"
          target="_blank"
          rel="noopener"
          :href="ENGINE_REQUEST_URL"
          title="Using another engine? Ask us to test it"
          >?</a
        >
      </div>
    </div>

    <div class="sheet layer" id="s-task">
      <canvas class="world" id="world" aria-hidden="true"></canvas>
      <div class="wrap li">
        <div class="intro">
          <h2>How a task <em>runs.</em></h2>
        </div>
        <div class="figwrap"><TaskFigure /></div>
        <div class="facts">
          <div>
            <h3>Standard</h3>
            <p>GA4GH TES v1.1. Engines that speak TES need no changes.</p>
          </div>
          <div>
            <h3>Verbatim</h3>
            <p>
              Your image and command, as submitted. No injected libraries; only
              <code>ignore_error</code> adds a <code>/bin/sh</code> wrapper.
            </p>
          </div>
          <div>
            <h3>Yours to secure</h3>
            <p>OIDC issuers, gateway tokens, API keys and an optional policy engine.</p>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>
