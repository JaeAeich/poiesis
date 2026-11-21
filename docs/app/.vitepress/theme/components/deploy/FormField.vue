<script setup>
// A labelled input with an optional "?" popover, chart key and hint.
// `id` and `style` fall through to the wrapper, which is what review links scroll to.
import { computed } from "vue";
import { useDeploy } from "../../lib/deploy/store.js";

const props = defineProps({
  inputId: { type: String, required: true },
  popoverId: { type: String, required: true },
  label: { type: String, required: true },
  required: { type: Boolean, default: false },
  help: { type: String, default: "" },
  chartKey: { type: String, default: "" },
  type: { type: String, default: "text" },
  placeholder: { type: String, default: "" },
  /** Static markup only. */
  hintHtml: { type: String, default: "" },
  value: { type: [String, Number], default: "" },
  example: { type: Boolean, default: false },
  /** Point the input's aria-describedby at the popover (issuer fields never did). */
  describedByHelp: { type: Boolean, default: true },
});
const emit = defineEmits(["update"]);

const { ui, togglePopover } = useDeploy();
const popoverElementId = computed(() => `p-${props.popoverId}`);
const popoverOpen = computed(() => Boolean(props.help) && ui.openPopover === props.popoverId);
</script>

<template>
  <div class="f" :class="{ 'pop-on': popoverOpen }">
    <div class="lab">
      <label :for="inputId"
        >{{ required ? label + " " : label
        }}<span v-if="required" class="req" aria-hidden="true">*</span></label
      >
      <button
        v-if="help"
        type="button"
        class="ib"
        data-info
        :aria-label="`About ${label}`"
        :aria-expanded="String(popoverOpen)"
        :aria-controls="popoverElementId"
        @click.prevent="togglePopover(popoverId)"
      >
        ?
      </button>
      <span v-if="chartKey" class="k" :title="chartKey">{{ chartKey }}</span>
    </div>
    <div v-if="help" :id="popoverElementId" class="pop" role="tooltip">{{ help }}</div>
    <input
      :id="inputId"
      :type="type"
      :aria-required="required ? 'true' : undefined"
      :aria-describedby="help && describedByHelp ? popoverElementId : undefined"
      :value="value"
      :placeholder="placeholder"
      :class="{ ex: example }"
      @input="emit('update', $event.target.value)"
    />
    <!-- eslint-disable-next-line vue/no-v-html -- hints are static markup from fields.js -->
    <div v-if="hintHtml" class="hint" v-html="hintHtml"></div>
  </div>
</template>

<style scoped>
/* the "?" button and the help popover it opens */
.poi .ib {
  flex: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  background: var(--bg);
  color: var(--muted);
  font: 600 10px/1 var(--sans);
  display: inline-grid;
  place-items: center;
  padding: 0;
  align-self: center;
}
.poi .ib:hover,
.poi .f.pop-on .ib {
  border-color: var(--blue);
  color: var(--blue-ink);
  background: var(--blue-wash);
}
.poi .pop {
  display: none;
  position: absolute;
  left: 0;
  right: 0;
  top: calc(100% + 6px);
  z-index: 6;
  background: var(--bg);
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  box-shadow: var(--shadow);
  padding: 10px 12px;
  font-size: 13.5px;
  line-height: 1.5;
  color: var(--body);
  white-space: normal;
}
.poi .f.pop-on .pop {
  display: block;
  animation: in 0.18s var(--ease);
}
</style>
