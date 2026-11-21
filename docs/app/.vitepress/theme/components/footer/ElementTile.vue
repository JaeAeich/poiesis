<script setup>
// One periodic-table tile. Hover, focus or tap shows its illustration, a small animated accent
// and a fact; the symbol shrinks into the corner.
import { computed } from "vue";
import { withBase } from "vitepress";
import { HIGHLIGHT_SYMBOL } from "../../lib/footer/content.js";

const props = defineProps({
  /** @type {import("vue").PropType<import("../../lib/footer/content.js").ChemicalElement>} */
  element: { type: Object, required: true },
  active: { type: Boolean, default: false },
  /** Set the illustration's URLs (it loads only then). */
  loadArt: { type: Boolean, default: false },
});
defineEmits(["toggle"]);

const artUrl = (variant) => `url(${withBase(`/elements/${props.element.art}-${variant}.webp`)})`;
// --ml / --md: the illustration as a mask in light and dark mode
const artStyle = computed(() =>
  props.loadArt
    ? { "--ml": artUrl("light"), "--md": artUrl(props.element.darkArt ? "dark" : "light") }
    : null,
);
</script>

<template>
  <button
    type="button"
    class="el"
    :class="{ es: element.symbol === HIGHLIGHT_SYMBOL, on: active }"
    :aria-pressed="active"
    :aria-label="`${element.name}, ${element.number}: ${element.fact}`"
    :data-k="element.art"
    :style="artStyle"
    @click="$emit('toggle')"
  >
    <i class="art" aria-hidden="true"></i>
    <svg class="acc" viewBox="0 0 100 112" aria-hidden="true">
      <!-- a glowing vial in Curie's hand -->
      <template v-if="element.art === 'curie'">
        <defs>
          <radialGradient id="poi-rg">
            <stop offset="0" stop-color="#7fe6c8" stop-opacity=".9" />
            <stop offset="1" stop-color="#7fe6c8" stop-opacity="0" />
          </radialGradient>
        </defs>
        <g class="vial">
          <circle class="halo" cx="40" cy="62" r="9" fill="url(#poi-rg)" />
          <rect x="38.4" y="56.5" width="3.2" height="9" rx="1.5" class="glass" />
          <rect x="38.8" y="60.5" width="2.4" height="4.6" rx="1.1" class="glowfill" />
        </g>
      </template>
      <!-- bubbles rising through the kelp -->
      <g v-else-if="element.art === 'kelp'" class="bub">
        <circle cx="30" cy="112" r="1.6" />
        <circle cx="64" cy="112" r="1.1" />
        <circle cx="48" cy="112" r="2" />
        <circle cx="76" cy="112" r="1.3" />
      </g>
      <!-- chalk writing itself -->
      <text v-else-if="element.art === 'einstein'" class="chalk" x="10" y="40">E = mc²</text>
      <!-- violet vapour over a flame -->
      <template v-else-if="element.art === 'retort'">
        <g class="vap">
          <path d="M30 46c-4-5 4-8 0-13s4-8 0-12" />
          <path d="M26 44c-3-4 3-7 0-11" />
          <path d="M34 44c3-4-3-7 0-11" />
        </g>
        <g class="flame"><ellipse cx="26" cy="63" rx="7" ry="2.2" /></g>
      </template>
      <!-- embers from the volcano -->
      <g v-else class="emb">
        <circle cx="60" cy="86" r="1" />
        <circle cx="58" cy="86" r=".8" />
        <circle cx="63" cy="86" r="1.1" />
        <circle cx="61" cy="86" r=".7" />
        <circle cx="56" cy="86" r=".9" />
      </g>
    </svg>
    <span class="z" aria-hidden="true">{{ element.number }}</span>
    <span class="m" aria-hidden="true">{{ element.mass }}</span>
    <span class="cnt" aria-hidden="true"
      ><i v-for="(count, shell) in element.shells" :key="shell">{{ count }}</i></span
    >
    <b aria-hidden="true">{{ element.symbol }}</b>
    <span class="econf" aria-hidden="true">{{ element.configuration }}</span>
    <span class="fact" aria-hidden="true">{{ element.fact }}</span>
  </button>
</template>

<style scoped>
/* tile: number, mass, shells, symbol and configuration over a faint illustration */
.poi-footer .el {
  border-radius: clamp(8px, 1vw, 14px);
  position: relative;
  aspect-ratio: 1/1.08;
  padding: 0;
  display: block;
  overflow: hidden;
  isolation: isolate;
  outline: none;
  border: 1.5px solid var(--line-strong);
  background: none;
  font: inherit;
  color: inherit;
  text-align: inherit;
  width: 100%;
  cursor: pointer;
  transition:
    border-color 0.2s,
    transform 0.2s var(--ease);
}
/* keyboard focus keeps the site's focus ring (primitives.css), which used to win here */
.poi-footer .el:focus-visible {
  outline: 2px solid var(--blue);
  outline-offset: 2px;
  border-radius: 4px;
}
.poi-footer .el.es {
  border-color: var(--coral);
  background: none;
}
.poi-footer .el .art {
  position: absolute;
  inset: 0;
  z-index: -1;
  background: var(--fg);
  -webkit-mask: var(--ml) center/cover no-repeat;
  mask: var(--ml) center/cover no-repeat;
  opacity: 0.08;
  transform: scale(1.06);
  transition:
    opacity 0.2s,
    transform 0.2s var(--ease);
}
html.dark .poi-footer .el .art {
  -webkit-mask-image: var(--md);
  mask-image: var(--md);
}
.poi-footer .el::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 52%;
  z-index: 0;
  pointer-events: none;
  background: linear-gradient(transparent, var(--bg) 62%);
  opacity: 0;
  transition: opacity 0.2s;
}
.poi-footer .el > * {
  z-index: 1;
}
.poi-footer .el .acc {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  transition: opacity 0.2s;
}
.poi-footer .el .z {
  position: absolute;
  left: clamp(8px, 1.2vw, 16px);
  top: clamp(8px, 1.2vw, 14px);
  font: 600 clamp(10px, 1.25vw, 17px)/1 var(--mono);
  color: var(--blue-ink);
  transition: opacity 0.2s;
}
.poi-footer .el .m {
  position: absolute;
  right: clamp(8px, 1.2vw, 16px);
  top: clamp(8px, 1.2vw, 14px);
  font: clamp(9px, 1.05vw, 14px)/1 var(--mono);
  color: var(--muted);
  transition: opacity 0.2s;
}
.poi-footer .el .cnt {
  position: absolute;
  right: clamp(8px, 1.2vw, 16px);
  top: clamp(26px, 3vw, 40px);
  display: flex;
  flex-direction: column;
  gap: 1px;
  font: clamp(8px, 0.85vw, 11.5px)/1.2 var(--mono);
  color: var(--muted);
  text-align: right;
  transition: opacity 0.2s;
}
.poi-footer .el .cnt i {
  font-style: normal;
  font: inherit;
  color: inherit;
}
.poi-footer .el b {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  padding-bottom: 6%;
  margin: 0;
  font: 600 clamp(36px, 7.4vw, 112px)/0.9 var(--sans);
  letter-spacing: -0.04em;
  color: var(--fg);
  transition:
    transform 0.2s var(--ease),
    color 0.2s;
}
.poi-footer .el.es b {
  color: var(--coral-ink);
}
html.dark .poi-footer .el.es b {
  color: var(--coral);
}
.poi-footer .el .econf,
.poi-footer .el .fact {
  position: absolute;
  left: clamp(8px, 1.2vw, 16px);
  right: clamp(8px, 1.2vw, 16px);
  bottom: clamp(8px, 1.1vw, 14px);
  transition:
    opacity 0.2s,
    transform 0.2s var(--ease);
}
.poi-footer .el .econf {
  font: clamp(8px, 0.85vw, 11.5px)/1.3 var(--mono);
  color: var(--muted);
  white-space: nowrap;
  letter-spacing: -0.03em;
  overflow: hidden;
  text-overflow: ellipsis;
}
.poi-footer .el .fact {
  opacity: 0;
  transform: translateY(6px);
  font: 500 clamp(10px, 0.95vw, 13.5px)/1.4 var(--sans);
  color: var(--fg);
}

/* tap / focus / hover: slow in, fast out (the base rules above leave in .2s) */
.poi-footer .el:is(.on, :focus-visible) {
  transform: translateY(-6px);
  border-color: var(--blue);
  transition:
    border-color 0.35s,
    transform 0.45s var(--ease);
}
.poi-footer .el.es:is(.on, :focus-visible) {
  border-color: var(--coral);
}
.poi-footer .el:is(.on, :focus-visible) .art {
  opacity: 0.82;
  transform: scale(1);
  transition:
    opacity 0.6s,
    transform 1.1s var(--ease);
}
.poi-footer .el:is(.on, :focus-visible) .acc,
.poi-footer .el:is(.on, :focus-visible)::after {
  opacity: 1;
  transition: opacity 0.5s;
}
.poi-footer .el:is(.on, :focus-visible) b {
  transform: translate(-30%, -36%) scale(0.42);
  color: var(--fg);
  transition:
    transform 0.6s var(--ease),
    color 0.3s;
}
.poi-footer .el.es:is(.on, :focus-visible) b {
  color: var(--coral-ink);
}
.poi-footer .el:is(.on, :focus-visible) :is(.econf, .cnt, .z, .m) {
  opacity: 0;
  transition: opacity 0.3s;
}
.poi-footer .el:is(.on, :focus-visible) .fact {
  opacity: 1;
  transform: none;
  transition:
    opacity 0.35s 0.12s,
    transform 0.5s var(--ease) 0.12s;
}
@media (hover: hover) and (pointer: fine) {
  .poi-footer .el:hover {
    transform: translateY(-6px);
    border-color: var(--blue);
    transition:
      border-color 0.35s,
      transform 0.45s var(--ease);
  }
  .poi-footer .el.es:hover {
    border-color: var(--coral);
  }
  .poi-footer .el:hover .art {
    opacity: 0.82;
    transform: scale(1);
    transition:
      opacity 0.6s,
      transform 1.1s var(--ease);
  }
  .poi-footer .el:hover .acc,
  .poi-footer .el:hover::after {
    opacity: 1;
    transition: opacity 0.5s;
  }
  .poi-footer .el:hover b {
    transform: translate(-30%, -36%) scale(0.42);
    color: var(--fg);
    transition:
      transform 0.6s var(--ease),
      color 0.3s;
  }
  .poi-footer .el.es:hover b {
    color: var(--coral-ink);
  }
  .poi-footer .el:hover :is(.econf, .cnt, .z, .m) {
    opacity: 0;
    transition: opacity 0.3s;
  }
  .poi-footer .el:hover .fact {
    opacity: 1;
    transform: none;
    transition:
      opacity 0.35s 0.12s,
      transform 0.5s var(--ease) 0.12s;
  }
}

/* accents, animated while the tile is open */
.poi-footer .acc * {
  transform-box: view-box;
}
.poi-footer .vial .halo {
  stroke: var(--halo);
}
.poi-footer .vial .glass {
  fill: none;
  stroke: var(--fg);
  stroke-width: 0.5;
  opacity: 0.8;
}
.poi-footer .vial .glowfill {
  fill: #7fe6c8;
}
.poi-footer .el.on .vial .halo {
  animation: poi-pulse 2.2s ease-in-out infinite;
  transform-origin: 40px 62px;
}
@keyframes poi-pulse {
  50% {
    transform: scale(1.45);
    opacity: 0.55;
  }
}
.poi-footer .chalk {
  font:
    italic 500 10px Georgia,
    "Times New Roman",
    serif;
  fill: transparent;
  stroke: var(--fg);
  stroke-width: 0.3;
  stroke-dasharray: 70;
  stroke-dashoffset: 70;
  opacity: 0.85;
}
.poi-footer .el.on .chalk {
  animation: poi-write 2.4s 0.25s ease-out forwards;
}
@keyframes poi-write {
  60% {
    fill: transparent;
    stroke-dashoffset: 0;
  }
  to {
    stroke-dashoffset: 0;
    fill: var(--fg);
  }
}
.poi-footer .el[data-k="kelp"] .art {
  transform-origin: 50% 100%;
}
.poi-footer .el[data-k="kelp"].on .art {
  animation: poi-sway 4s ease-in-out infinite alternate;
}
@keyframes poi-sway {
  from {
    transform: rotate(-1.6deg);
  }
  to {
    transform: rotate(1.6deg);
  }
}
.poi-footer .bub circle {
  fill: none;
  stroke: var(--blue);
  stroke-width: 0.5;
}
.poi-footer .el.on .bub circle {
  animation: poi-bub 3.4s ease-in infinite;
}
.poi-footer .bub circle:nth-child(2) {
  animation-delay: -1s !important;
}
.poi-footer .bub circle:nth-child(3) {
  animation-delay: -2s !important;
}
.poi-footer .bub circle:nth-child(4) {
  animation-delay: -2.7s !important;
}
@keyframes poi-bub {
  from {
    transform: translateY(0);
    opacity: 0;
  }
  15% {
    opacity: 1;
  }
  to {
    transform: translate(3px, -80px);
    opacity: 0;
  }
}
.poi-footer .vap path {
  fill: none;
  stroke: #9b7cf4;
  stroke-width: 1.4;
  stroke-linecap: round;
  opacity: 0;
}
.poi-footer .el.on .vap path {
  animation: poi-rise 2.6s ease-in infinite;
}
.poi-footer .vap path:nth-child(2) {
  animation-delay: -0.9s !important;
}
.poi-footer .vap path:nth-child(3) {
  animation-delay: -1.7s !important;
}
@keyframes poi-rise {
  0% {
    transform: translateY(6px);
    opacity: 0;
  }
  30% {
    opacity: 0.9;
  }
  100% {
    transform: translateY(-14px);
    opacity: 0;
  }
}
.poi-footer .flame ellipse {
  fill: var(--coral);
  opacity: 0;
  filter: blur(1.2px);
}
.poi-footer .el.on .flame ellipse {
  animation: poi-flick 0.5s ease-in-out infinite alternate;
}
@keyframes poi-flick {
  from {
    opacity: 0.25;
  }
  to {
    opacity: 0.6;
  }
}
.poi-footer .emb circle {
  fill: var(--coral);
}
.poi-footer .el.on .emb circle {
  animation: poi-ember 2.2s ease-out infinite;
}
.poi-footer .emb circle:nth-child(2) {
  animation-delay: -0.4s !important;
  --dx: -9px;
}
.poi-footer .emb circle:nth-child(3) {
  animation-delay: -0.9s !important;
  --dx: 8px;
}
.poi-footer .emb circle:nth-child(4) {
  animation-delay: -1.4s !important;
  --dx: -4px;
}
.poi-footer .emb circle:nth-child(5) {
  animation-delay: -1.8s !important;
  --dx: 12px;
}
@keyframes poi-ember {
  from {
    transform: translate(0, 0);
    opacity: 0;
  }
  15% {
    opacity: 1;
  }
  to {
    transform: translate(var(--dx, 4px), -34px);
    opacity: 0;
  }
}
@media (hover: hover) and (pointer: fine) {
  .poi-footer .el:hover .vial .halo {
    animation: poi-pulse 2.2s ease-in-out infinite;
    transform-origin: 40px 62px;
  }
  .poi-footer .el:hover .chalk {
    animation: poi-write 2.4s 0.25s ease-out forwards;
  }
  .poi-footer .el[data-k="kelp"]:hover .art {
    animation: poi-sway 4s ease-in-out infinite alternate;
  }
  .poi-footer .el:hover .bub circle {
    animation: poi-bub 3.4s ease-in infinite;
  }
  .poi-footer .el:hover .vap path {
    animation: poi-rise 2.6s ease-in infinite;
  }
  .poi-footer .el:hover .flame ellipse {
    animation: poi-flick 0.5s ease-in-out infinite alternate;
  }
  .poi-footer .el:hover .emb circle {
    animation: poi-ember 2.2s ease-out infinite;
  }
}

/* phones: the art and animation on tap; the fact sits under the row (PeriodicFooter) */
@media (max-width: 760px) {
  .poi-footer .el .cnt,
  .poi-footer .el .econf,
  .poi-footer .el .fact,
  .poi-footer .el .m {
    display: none;
  }
  .poi-footer .el:is(.on, :focus-visible) b {
    transform: translate(-26%, -34%) scale(0.5);
  }
  .poi-footer .el:is(.on, :focus-visible) .z {
    opacity: 0;
  }
  .poi-footer .el::after {
    display: none;
  }
}
@media (hover: hover) and (pointer: fine) and (max-width: 760px) {
  .poi-footer .el:hover b {
    transform: translate(-26%, -34%) scale(0.5);
  }
  .poi-footer .el:hover .z {
    opacity: 0;
  }
}
/* small phones: smaller symbols so the five tiles fit */
@media (max-width: 400px) {
  .poi-footer .el b {
    font-size: clamp(24px, 8.6vw, 36px);
    padding-top: 14%;
  }
  .poi-footer .el:is(.on, :focus-visible) b {
    transform: translate(-22%, -26%) scale(0.5);
  }
}
@media (hover: hover) and (pointer: fine) and (max-width: 400px) {
  .poi-footer .el:hover b {
    transform: translate(-22%, -26%) scale(0.5);
  }
}
/* reduced motion: colour and opacity still fade; nothing moves or animates */
@media (prefers-reduced-motion: reduce) {
  .poi-footer .el,
  .poi-footer .el * {
    animation: none !important;
    transition-property: opacity, color, border-color !important;
  }
}
</style>
