<script setup>
// A button that copies text, then says so in place (same box, so nothing moves).
import { onUnmounted, ref } from "vue";
import { copyText } from "../../lib/deploy/browser.js";
import { useDeploy } from "../../lib/deploy/store.js";
import DeployIcon from "./DeployIcon.vue";

const FEEDBACK_MS = 1600;

const props = defineProps({
  /** Text to copy, or a function returning it at click time. */
  text: { type: [String, Function], required: true },
  /** Icon-only buttons show just the check; text buttons add "Copied". */
  iconOnly: { type: Boolean, default: false },
  ariaLabel: { type: String, default: undefined },
});

const deploy = useDeploy();
const button = ref(null);
/** @type {import("vue").Ref<"ok" | "fail" | null>} */
const status = ref(null);
const minWidth = ref("");
let resetTimer = 0;

async function onClick() {
  const ok = await copyText(typeof props.text === "function" ? props.text() : props.text);
  deploy.showToast(ok ? "Copied" : "Copy failed");
  if (!button.value) return;
  // keep the original width while the shorter or longer feedback shows
  if (!status.value) minWidth.value = button.value.offsetWidth + "px";
  status.value = ok ? "ok" : "fail";
  clearTimeout(resetTimer);
  resetTimer = setTimeout(() => {
    status.value = null;
    minWidth.value = "";
  }, FEEDBACK_MS);
}

onUnmounted(() => clearTimeout(resetTimer));
</script>

<template>
  <button
    ref="button"
    :class="{ copied: status === 'ok', 'copy-fail': status === 'fail' }"
    :style="minWidth ? { minWidth } : undefined"
    :aria-label="status ? (status === 'ok' ? 'Copied' : 'Copy failed') : ariaLabel"
    @click="onClick"
  >
    <template v-if="status">
      <DeployIcon :name="status === 'ok' ? 'check' : 'cross'" />{{
        iconOnly ? "" : status === "ok" ? "Copied" : "Copy failed"
      }}
    </template>
    <slot v-else />
  </button>
</template>

<style scoped>
/* the copy confirms on the button itself */
.poi button.copied,
.poi button.copied:hover {
  color: var(--blue-ink);
  border-color: var(--blue);
}
.poi button.copy-fail,
.poi button.copy-fail:hover {
  color: var(--coral-ink);
  border-color: var(--coral);
}
</style>
