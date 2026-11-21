<script setup>
// The site footer: link columns, then POIESIS spelled with element tiles. The tiles' art loads
// only when the footer comes near the screen.
import { onMounted, onUnmounted, ref } from "vue";
import { withBase } from "vitepress";
import { useSidebar } from "vitepress/theme-without-fonts";
import ElementTile from "./footer/ElementTile.vue";
import { ELEMENTS, LINK_COLUMNS } from "../lib/footer/content.js";

/** Start loading the art this far before the footer scrolls into view. */
const ART_PRELOAD_MARGIN = "400px";

const { hasSidebar } = useSidebar();
const linkHref = (href) => (href.startsWith("/") ? withBase(href) : href);

const root = ref(null);
const artNear = ref(false);
/** Index of the tapped tile, -1 for none. */
const active = ref(-1);
const toggle = (index) => {
  active.value = active.value === index ? -1 : index;
};

let observer = null;
onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      artNear.value = true;
      observer.disconnect();
    },
    { rootMargin: ART_PRELOAD_MARGIN },
  );
  observer.observe(root.value);
});
onUnmounted(() => observer?.disconnect());
</script>

<template>
  <div ref="root" class="poi poi-footer" :class="{ 'has-sidebar': hasSidebar }">
    <footer>
      <div class="wrap">
        <div class="fcols">
          <div>
            <b>Poiesis</b>
            <p>A GA4GH Task Execution Service for Kubernetes.</p>
          </div>
          <div v-for="column in LINK_COLUMNS" :key="column.title">
            <b>{{ column.title }}</b>
            <a v-for="link in column.links" :key="link.text" :href="linkHref(link.href)">{{
              link.text
            }}</a>
          </div>
        </div>
        <div
          class="elements"
          role="group"
          aria-label="Poiesis, spelled with elements: polonium, iodine, einsteinium, iodine, sulfur"
        >
          <ElementTile
            v-for="(element, index) in ELEMENTS"
            :key="index"
            :element="element"
            :active="active === index"
            :load-art="artNear"
            @toggle="toggle(index)"
          />
        </div>
        <!-- on phones the fact shows here, under the row -->
        <p class="tap-fact" aria-live="polite">{{ active >= 0 ? ELEMENTS[active].fact : "" }}</p>
        <div class="fbase">
          <span>© 2026 Poiesis contributors · Illustrations: public domain, Wikimedia Commons</span>
          <a class="by" href="https://jaeaeich.com">Made by jaeaeich</a>
          <span>Built for workflows that matter</span>
        </div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
/* clear the fixed sidebar on doc pages, the same way VitePress offsets its content */
.poi-footer {
  position: relative;
  z-index: 3;
}
@media (min-width: 960px) {
  .poi-footer.has-sidebar {
    padding-left: var(--vp-sidebar-width);
  }
}
@media (min-width: 1440px) {
  .poi-footer.has-sidebar {
    padding-left: calc((100vw - var(--vp-layout-max-width)) / 2 + var(--vp-sidebar-width));
    padding-right: calc((100vw - var(--vp-layout-max-width)) / 2);
  }
}

/* frame and link columns */
.poi footer {
  position: relative;
  z-index: 3;
  background: var(--bg);
  border-top: 1px solid var(--line);
  padding: 64px 0 32px;
  font-size: 14px;
  color: var(--muted);
  overflow: hidden;
}
.poi footer .wrap {
  display: block;
}
.poi footer a {
  color: var(--body);
}
.poi .fcols {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 32px;
}
.poi .fcols b {
  display: block;
  color: var(--fg);
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 12px;
}
.poi .fcols a {
  display: block;
  color: var(--body);
  margin: 6px 0;
}
.poi .fcols p {
  margin: 0;
  max-width: 22em;
}
@media (max-width: 760px) {
  .poi .fcols {
    grid-template-columns: 1fr 1fr;
  }
  .poi .fcols > div:first-child {
    grid-column: 1/-1;
  }
}

/* the row of tiles, underlined with a blue-coral rule */
.poi .elements {
  position: relative;
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: clamp(6px, 1.2vw, 16px);
  margin: 56px 0 0;
  -webkit-user-select: none;
  user-select: none;
  -webkit-touch-callout: none;
}
.poi .elements::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -29px;
  height: 2px;
  border-radius: 2px;
  background: linear-gradient(90deg, var(--blue), var(--coral) 50%, var(--blue));
  opacity: 0.5;
}
.poi-footer .tap-fact {
  display: none;
  margin: 14px 0 0;
  min-height: 2.8em;
  font-size: 13px;
  line-height: 1.4;
  color: var(--body);
}
@media (max-width: 760px) {
  .poi-footer .tap-fact {
    display: block;
    margin-top: 46px;
  }
}

/* base line */
.poi .fbase {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 56px;
  font-size: 13px;
}
.poi-footer .fbase .by {
  font: 12px var(--mono);
  letter-spacing: 0.04em;
  color: var(--muted);
  text-decoration: none;
  transition: color 0.2s;
}
.poi-footer .fbase .by:hover {
  color: var(--fg);
}
</style>
