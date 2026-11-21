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
    <div id="stage" class="stage layer">
      <canvas id="bg" class="li" aria-hidden="true"></canvas>
      <div id="hero" class="wrap hero li">
        <div id="copy" class="copy reveal">
          <h1>Science at <em>cluster scale.</em></h1>
          <p>
            Poiesis is a GA4GH Task Execution Service for Kubernetes. Point your workflow engine at
            it, and every task runs in its own Pod.
          </p>
          <div id="hero-actions" class="actions">
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
            id="wheel"
            class="wheel"
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

    <div id="s-eng" class="sheet layer">
      <div class="wrap li">
        <div id="eng-center" class="eng-center">
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
                <a class="row-link" :href="engineGuide(engine)">{{ engine.name }}</a><small>{{
                  engine.detail
                }}</small>
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
      <!-- the logos are playthings to drag and throw; only the table rows link to the guide -->
      <div id="eng-field" class="field" aria-hidden="true">
        <span
          v-for="(engine, i) in ENGINES"
          :key="engine.name"
          class="pl"
          :class="engine.status"
          :data-i="i"
          :data-s="engine.size"
          :style="{ '--s': engine.size + 'px' }"
          :title="engine.name + ': ' + engine.label"
          ><EngineLogo :logo="engine.logo"
        /></span>
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

    <div id="s-task" class="sheet layer">
      <canvas id="world" class="world" aria-hidden="true"></canvas>
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
              Your image and command, as submitted. No injected libraries; a
              <code>/bin/sh</code> wrapper is added only for <code>ignore_error</code> or
              stdin/stdout/stderr paths.
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

<style scoped>
/* section stack: each section is a sticky layer the next one slides over (lib/home/stack.js) */
.poi .stage {
  position: relative;
  overflow: hidden;
  isolation: isolate;
}
.poi .layer {
  position: sticky;
  top: 0;
}
@media (min-width: 960px) {
  .poi .layer {
    top: 64px;
  }
}
.poi #stage {
  z-index: 0;
}
.poi #s-eng {
  z-index: 1;
}
.poi #s-task {
  z-index: 2;
}
.poi .li {
  transform-origin: 50% 30%;
}
.poi .sheet {
  background: var(--bg);
  border-radius: 24px 24px 0 0;
  margin-top: -24px;
  padding: 64px 0 96px;
  overflow: hidden;
  box-shadow:
    0 -1px 0 var(--line-strong),
    0 -6px 16px -10px rgba(13, 32, 51, 0.12);
}
html.dark .poi .sheet {
  box-shadow:
    0 -1px 0 var(--line-strong),
    0 -6px 16px -10px rgba(0, 0, 0, 0.5);
}

/* playthings: dragging and clicking never selects text */
.poi #stage,
.poi #s-eng {
  -webkit-user-select: none;
  user-select: none;
  -webkit-touch-callout: none;
}
.poi #stage a,
.poi #s-eng a {
  -webkit-user-drag: none;
}

/* hero: background canvas, copy, wheel */
.poi #bg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: -1;
  display: block;
}
.poi .stage.lat-hover {
  cursor: pointer;
}
.poi .stage.amoeba-hover {
  cursor: crosshair;
}
.poi .hero {
  min-height: 740px;
  padding: 80px 24px 196px;
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 40px;
  align-items: center;
}
.poi .hero h1 {
  font-size: clamp(46px, 6.4vw, 80px);
  line-height: 0.98;
  letter-spacing: -0.048em;
  max-width: 9ch;
  text-wrap: balance;
}
.poi .hero h1 em {
  font-style: normal;
  color: var(--coral);
}
.poi .hero p {
  font-size: 19px;
  line-height: 1.55;
  max-width: 27em;
  margin: 24px 0 36px;
}
.poi .hero .actions {
  display: flex;
  gap: 12px;
}
.poi .hero .btn {
  height: 40px;
  padding: 0 18px;
  font-size: 15px;
}
.poi .btn .arr {
  transition: transform 0.25s var(--ease);
}
@media (hover: hover) and (pointer: fine) {
  .poi .btn:hover .arr {
    transform: translateX(3px);
  }
}
.poi .reveal > * {
  opacity: 0;
  transform: translateY(12px);
  animation: rise 0.9s var(--ease) forwards;
}
.poi .reveal > *:nth-child(2) {
  animation-delay: 0.1s;
}
.poi .reveal > *:nth-child(3) {
  animation-delay: 0.2s;
}
@keyframes rise {
  to {
    opacity: 1;
    transform: none;
  }
}

/* the wheel's SVG is drawn by lib/home/wheel.js, hence :deep */
.poi .wheel-wrap {
  justify-self: center;
  position: relative;
  width: min(400px, 100%);
}
.poi .wheel {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  touch-action: none;
  cursor: grab;
  user-select: none;
  -webkit-user-select: none;
  border-radius: 50%;
}
.poi .wheel.grab {
  cursor: grabbing;
}
.poi .wheel::before {
  content: "";
  position: absolute;
  inset: 20%;
  border-radius: 50%;
  box-shadow: 0 18px 30px rgba(31, 106, 174, 0.18);
  z-index: -1;
  pointer-events: none;
}
.poi .wheel :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}
.poi .wheel :deep(.halo) {
  stroke: var(--halo);
}
.poi .wheel :deep(.in) {
  transform-box: view-box;
  transform-origin: 256px 256px;
  opacity: 0;
  animation: wheelIn 1.1s var(--ease) forwards;
}
.poi .wheel :deep(.in.h) {
  animation-name: handleIn;
}
.poi .wheel :deep(.sp) {
  stroke-dasharray: var(--len);
  stroke-dashoffset: var(--len);
  animation: draw 1.8s var(--ease-io) 0.5s forwards;
}
@keyframes wheelIn {
  from {
    opacity: 0;
    transform: scale(0.86) rotate(-25deg);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes handleIn {
  from {
    opacity: 0;
    transform: scale(0.7);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes draw {
  to {
    stroke-dashoffset: 0;
  }
}

/* section headings */
.poi .intro {
  text-align: center;
  max-width: 960px;
  margin: 0 auto;
}
.poi .intro h2 {
  margin: 0;
  font-size: clamp(34px, 4.8vw, 60px);
  font-weight: 600;
  letter-spacing: -0.042em;
  line-height: 1.02;
  color: var(--fg);
  text-wrap: balance;
}
.poi .intro h2 em {
  font-style: normal;
  color: var(--blue);
}
html.dark .poi .intro h2 em {
  color: var(--blue-ink);
}

/* engines: the list */
.poi #s-eng > .wrap {
  width: 100%;
}
@media (min-width: 761px) {
  .poi #s-eng {
    min-height: 760px;
  }
}
.poi .eng-center {
  max-width: 600px;
  margin: 0 auto;
  position: relative;
  z-index: 1;
}
.poi .eng-center .intro {
  margin-bottom: 28px;
}
.poi .eng {
  list-style: none;
  margin: 0;
  padding: 0;
}
.poi .eng li {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 4px;
  border-bottom: 1px solid var(--line);
  transition: background 0.2s;
}
.poi .eng li:first-child {
  border-top: 1px solid var(--line);
}
.poi .eng li.hl {
  background: var(--blue-wash);
}
.poi .eng li:has(.row-link):hover {
  background: var(--surface);
}
.poi .eng li:has(.row-link:focus-visible) {
  outline: 2px solid var(--blue);
  outline-offset: -2px;
  border-radius: 6px;
}
.poi .eng .row-link {
  color: inherit;
  text-decoration: none;
}
.poi .eng .row-link::after {
  content: "";
  position: absolute;
  inset: 0;
}
.poi .eng .row-link:focus-visible {
  outline: none;
}
.poi .eng .ic {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  border: 1px solid var(--line);
  display: grid;
  place-items: center;
  background: var(--bg);
  flex: none;
  color: var(--fg);
}
.poi .eng .ic > * {
  width: 20px;
  height: 20px;
  object-fit: contain;
}
.poi .eng .ic img.crop {
  object-fit: cover;
  object-position: left;
}
.poi .eng li.ask .ic {
  border-style: dashed;
  font: 500 15px var(--sans);
  color: var(--muted);
}
/* dark mode: logos sit on a light chip (this also wins over the "ask" row's muted colour) */
html.dark .poi .eng .ic {
  background: #d6dee8;
  border-color: transparent;
  color: #0d2033;
}
.poi .eng li.no .ic > * {
  filter: grayscale(1);
  opacity: 0.55;
}
.poi .eng li.ask .nm {
  font-weight: 500;
}
.poi .eng .nm {
  flex: 1;
  min-width: 0;
  color: var(--fg);
  font-weight: 500;
}
.poi .eng .nm small {
  display: block;
  color: var(--muted);
  font: 12.5px var(--mono);
  font-weight: 400;
}
.poi .st {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font: 13px var(--mono);
  white-space: nowrap;
}
.poi .st::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--blue);
}
.poi .st.part::before {
  background: none;
  border: 1.5px solid var(--blue);
}
.poi .st.no {
  color: var(--muted);
}
.poi .st.no::before {
  background: none;
  border: 1.5px dashed var(--muted);
}
@media (max-width: 400px) {
  .poi .eng li {
    flex-wrap: wrap;
    row-gap: 2px;
  }
  .poi .eng .st {
    order: 3;
    flex-basis: 100%;
    padding-left: 48px;
  }
}

/* engines: the playground of logos (lib/home/engines.js moves them) */
.poi .field {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
}
.poi .pl {
  position: absolute;
  left: 0;
  top: 0;
  width: var(--s);
  height: var(--s);
  display: grid;
  place-items: center;
  z-index: 1;
  pointer-events: auto;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 50%;
  box-shadow: var(--shadow);
  color: var(--fg);
  cursor: grab;
  touch-action: none;
  user-select: none;
  -webkit-user-select: none;
  transition:
    filter 0.3s,
    opacity 0.3s,
    box-shadow 0.2s,
    outline-color 0.2s;
  will-change: transform;
  outline: 2px solid transparent;
  outline-offset: 3px;
  text-decoration: none;
}
.poi .pl.held {
  cursor: grabbing;
  box-shadow: 0 14px 30px rgba(13, 32, 51, 0.22);
  z-index: 3;
}
.poi .pl > * {
  width: 52%;
  height: 52%;
  object-fit: contain;
  pointer-events: none;
  -webkit-user-drag: none;
}
.poi .pl img.crop {
  object-fit: cover;
  object-position: left;
}
.poi .pl.part > * {
  filter: grayscale(0.5);
  opacity: 0.85;
}
.poi .pl.no {
  box-shadow: none;
  border: 1.5px dashed var(--line-strong);
}
.poi .pl.no > * {
  filter: grayscale(1);
  opacity: 0.45;
}
.poi .pl.held > * {
  filter: none;
  opacity: 1;
}
.poi .pl.hl {
  outline-color: var(--coral);
}
.poi .pl.hl > * {
  filter: none !important;
  opacity: 1 !important;
}
.poi .pl.ask {
  border: 1.5px dashed var(--line-strong);
  background: var(--bg);
  box-shadow: none;
  font: 500 20px var(--sans);
  color: var(--muted);
  text-decoration: none;
}
@media (hover: hover) and (pointer: fine) {
  .poi .pl:hover > * {
    filter: none;
    opacity: 1;
  }
  .poi .pl.ask:hover {
    border-color: var(--coral);
    color: var(--coral-ink);
  }
}
html.dark .poi .pl:not(.ask) {
  background: #d6dee8;
  border-color: transparent;
  color: #0d2033;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
}
html.dark .poi .pl.no {
  background: var(--surface);
  border: 1.5px dashed var(--line-strong);
  box-shadow: none;
}
html.dark .poi .pl.no > * {
  opacity: 0.35;
}
@media (pointer: coarse) {
  .poi .pl {
    touch-action: pan-y;
  }
}

/* how a task runs: world map behind, figure, three facts */
.poi #s-task .world {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  pointer-events: none;
  display: block;
}
.poi #s-task > .wrap {
  position: relative;
  z-index: 1;
}
.poi .figwrap {
  max-width: 900px;
  margin: 36px auto 0;
}
.poi .facts {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin-top: 56px;
  border-top: 1px solid var(--line);
}
.poi .facts div {
  padding: 22px 28px 0 0;
}
.poi .facts div + div {
  padding-left: 28px;
  border-left: 1px solid var(--line);
}
.poi .facts h3 {
  font-size: 16px;
  margin-bottom: 6px;
}
.poi .facts p {
  margin: 0;
  font-size: 15px;
}

/* phones */
@media (max-width: 760px) {
  .poi .hero {
    grid-template-columns: 1fr;
    min-height: 0;
    padding: 28px 16px 182px;
    gap: 12px;
    text-align: center;
  }
  .poi .hero .copy {
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .poi .hero h1 {
    max-width: 9ch;
  }
  .poi .hero p {
    margin: 18px auto 28px;
  }
  .poi .hero .actions {
    justify-content: center;
  }
  .poi .wheel-wrap {
    width: 190px;
    grid-row: 1;
  }
  .poi .field {
    position: relative;
    height: 190px;
    margin: 20px 0 0;
    pointer-events: auto;
  }
  .poi .pl.ask {
    display: none;
  }
  .poi .pl {
    width: calc(var(--s) * 0.62);
    height: calc(var(--s) * 0.62);
  }
  .poi .facts {
    grid-template-columns: 1fr;
  }
  .poi .facts div + div {
    padding-left: 0;
    border-left: 0;
    border-top: 1px solid var(--line);
  }
  .poi .facts div {
    padding: 18px 0;
  }
  .poi .sheet {
    border-radius: 20px 20px 0 0;
  }
}
</style>
