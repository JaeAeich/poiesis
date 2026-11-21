<script setup>
defineProps({ type: { type: String, default: "info" } });
</script>

<template>
  <div class="poi-callout" :class="type" role="note">
    <svg v-if="type === 'warn'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5M12 18h.01"/></svg>
    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/></svg>
    <div><slot /></div>
  </div>
</template>

<style>
.poi-callout { display: flex; gap: 12px; border: 1px solid color-mix(in srgb, var(--blue) 30%, var(--line)); background: var(--blue-wash); border-radius: 8px; padding: 14px 16px; margin: 24px 0; font-size: 15px; line-height: 1.6; color: var(--fg); }
.poi-callout > svg { flex: none; width: 18px; height: 18px; color: var(--blue); margin-top: 3px; }
.poi-callout > div > :first-child { margin-top: 0; }
.poi-callout > div > :last-child { margin-bottom: 0; }
.poi-callout.warn { border-color: color-mix(in srgb, var(--coral) 35%, var(--line)); background: var(--coral-wash); }
.poi-callout.warn > svg { color: var(--coral-ink); }
</style>
