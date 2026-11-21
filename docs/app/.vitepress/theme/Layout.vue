<script setup>
// VitePress's layout with our footer under every page.
import DefaultTheme from "vitepress/theme-without-fonts";
import PeriodicFooter from "./components/PeriodicFooter.vue";

const { Layout } = DefaultTheme;
</script>

<template>
  <Layout>
    <template #layout-bottom>
      <PeriodicFooter />
    </template>
  </Layout>
</template>
