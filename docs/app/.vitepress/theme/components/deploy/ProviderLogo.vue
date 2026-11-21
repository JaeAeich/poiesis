<script setup>
// A provider mark for the tiles: inline SVG where we have the path, otherwise the site's image.
import { withBase } from "vitepress";
import { LOGO_PATHS } from "../../lib/deploy/logos.js";

defineProps({
  name: { type: String, required: true },
});

const IMAGES = { gc: "logos/google-cloud.svg", az: "logos/azure.svg" };
</script>

<template>
  <svg v-if="LOGO_PATHS[name]" viewBox="0 0 24 24" aria-hidden="true">
    <path :fill="LOGO_PATHS[name].fill" :d="LOGO_PATHS[name].path" />
  </svg>
  <template v-else-if="name === 'aws'">
    <img class="lt" :src="withBase('/logos/aws-light.svg')" alt="" />
    <img class="dk" :src="withBase('/logos/aws.svg')" alt="" />
  </template>
  <img v-else :src="withBase('/' + IMAGES[name])" alt="" />
</template>

<style scoped>
/* AWS has separate light and dark marks */
.poi img.dk {
  display: none;
}
html.dark .poi img.dk {
  display: block;
}
html.dark .poi img.lt {
  display: none;
}
</style>
