<script setup>
import { withBase } from "vitepress";
import { useSidebar } from "vitepress/theme-without-fonts";
const { hasSidebar } = useSidebar();
const els = [["84", "Po", "[209]"], ["53", "I", "126.90"], ["99", "Es", "[252]"], ["53", "I", "126.90"], ["16", "S", "32.06"]];
</script>

<template>
  <div class="poi poi-footer" :class="{ 'has-sidebar': hasSidebar }">
    <footer>
      <div class="wrap">
        <div class="fcols">
          <div><b>Poiesis</b><p>A GA4GH Task Execution Service for Kubernetes.</p></div>
          <div><b>Product</b><a :href="withBase('/docs/start/what-is-poiesis')">Docs</a><a :href="withBase('/deploy')">Deploy</a><a href="https://github.com/JaeAeich/poiesis">GitHub</a></div>
          <div><b>Project</b><span>GA4GH TES v1.1</span><span>Apache 2.0</span><span>Helm chart</span></div>
          <div><b><a href="https://jaeaeich.com">jaeaeich</a></b></div>
        </div>
        <div class="elements" aria-label="Poiesis, spelled with elements: polonium, iodine, einsteinium, iodine, sulfur">
          <div v-for="(e, i) in els" :key="i" class="el" aria-hidden="true"><i>{{ e[0] }}</i><b>{{ e[1] }}</b><small>{{ e[2] }}</small></div>
        </div>
        <div class="fbase"><span>© 2026 Poiesis contributors</span><span>Built for workflows that matter</span></div>
      </div>
    </footer>
  </div>
</template>

<style>
/* clear the fixed sidebar on doc pages, the same way VitePress offsets its content */
@media (min-width: 960px) { .poi-footer.has-sidebar { padding-left: var(--vp-sidebar-width); } }
@media (min-width: 1440px) { .poi-footer.has-sidebar { padding-left: calc((100vw - var(--vp-layout-max-width)) / 2 + var(--vp-sidebar-width)); padding-right: calc((100vw - var(--vp-layout-max-width)) / 2); } }
.poi-footer { position: relative; z-index: 3; }
</style>
