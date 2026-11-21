<script setup>
import { withBase } from "vitepress";

/** @type {{ logo: import("../lib/home/engineList.js").EngineLogo }} */
defineProps({ logo: { type: Object, required: true } });
</script>

<template>
  <svg v-if="logo.path" viewBox="0 0 24 24" aria-hidden="true">
    <path :fill="logo.fill" :d="logo.path" />
  </svg>
  <img
    v-else
    v-bind="logo.crop ? { class: 'crop' } : {}"
    :src="withBase('/logos/' + logo.file)"
    alt=""
  />
</template>
