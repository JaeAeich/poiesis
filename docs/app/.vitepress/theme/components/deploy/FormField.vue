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
    <div v-if="hintHtml" class="hint" v-html="hintHtml"></div>
  </div>
</template>
