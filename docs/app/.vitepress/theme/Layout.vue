<script setup>
import DefaultTheme from "vitepress/theme-without-fonts";
import PeriodicFooter from "./components/PeriodicFooter.vue";
const { Layout } = DefaultTheme;
</script>

<template>
  <Layout>
    <template #layout-bottom><PeriodicFooter /></template>
  </Layout>
</template>
