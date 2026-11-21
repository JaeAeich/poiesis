<script setup>
// The API reference: Swagger UI rendering public/openapi.yaml (copied from the spec at build time).
import { onMounted, ref } from "vue";
import SwaggerUI from "swagger-ui";
import "swagger-ui/dist/swagger-ui.css";

const loading = ref(true);
const error = ref(null);

onMounted(() => {
  try {
    SwaggerUI({
      url: "/openapi.yaml",
      dom_id: "#swagger-container",
      presets: [SwaggerUI.presets.apis],
      layout: "BaseLayout",
      docExpansion: "list",
      deepLinking: true,
      filter: true,
      syntaxHighlight: {
        activate: true,
        theme: "agate",
      },
      onComplete: () => {
        loading.value = false;
      },
    });
  } catch (err) {
    console.error("SwaggerViewer: Error initializing SwaggerUI:", err);
    error.value = err.message;
    loading.value = false;
  }
});
</script>

<template>
  <div id="swagger-container">
    <div v-if="error" class="swagger-error">
      <p>Failed to load API documentation: {{ error }}</p>
    </div>
    <div v-if="loading" class="swagger-loading">Loading API documentation...</div>
  </div>
</template>
