<script setup>
// A row of mutually exclusive toggle buttons (role=group, aria-pressed on each).
defineProps({
  label: { type: String, required: true },
  /** [value, text] pairs. */
  options: { type: Array, required: true },
  modelValue: { type: String, required: true },
});
const emit = defineEmits(["update:modelValue"]);
</script>

<template>
  <div class="seg2" role="group" :aria-label="label">
    <button
      v-for="[value, text] in options"
      :key="value"
      :class="{ on: value === modelValue }"
      :aria-pressed="String(value === modelValue)"
      @click="emit('update:modelValue', value)"
    >
      {{ text }}
    </button>
  </div>
</template>
