<script setup>
// One advanced setting: a checkbox, a select, or a text/number input with its chart key.
import { computed } from "vue";
import { advancedFieldId, advancedValue } from "../../../lib/deploy/advanced.js";
import { useDeploy } from "../../../lib/deploy/store.js";

const props = defineProps({
  /** @type {import("vue").PropType<import("../../../lib/deploy/advanced.js").AdvancedItem>} */
  item: { type: Object, required: true },
});
const { config, setAdvanced } = useDeploy();

const id = advancedFieldId(props.item.key);
const value = computed(() => advancedValue(config, props.item));
// Text inputs keep what the user typed; a cleared number reads as the default without
// writing it back into the box.
const initialValue = advancedValue(config, props.item);
const placeholder =
  props.item.placeholder ||
  (props.item.defaultValue === "" ? "not set" : String(props.item.defaultValue));
const shownKey = props.item.shownKey || props.item.key;

const update = (event) =>
  setAdvanced(props.item.key, { value: event.target.value, checked: event.target.checked });
</script>

<template>
  <label v-if="item.kind === 'boolean'" :id="id" class="check">
    <input :id="`${id}-i`" type="checkbox" :checked="value" @change="update" />
    <span
      >{{ item.label }}<small>{{ item.why }}</small></span
    >
  </label>
  <div v-else :id="id" class="f">
    <div class="lab">
      <label :for="`${id}-i`">{{ item.label }}</label>
      <span class="k" :title="shownKey">{{ shownKey }}</span>
    </div>
    <select v-if="item.kind === 'select'" :id="`${id}-i`" @input="update">
      <option
        v-for="option in item.options"
        :key="option"
        :selected="option === value"
        :value="option"
      >
        {{ option || "not set" }}
      </option>
    </select>
    <input
      v-else
      :id="`${id}-i`"
      :type="item.kind === 'number' ? 'number' : 'text'"
      :value="initialValue"
      :placeholder="placeholder"
      @input="update"
    />
    <div class="hint">{{ item.why }}</div>
  </div>
</template>
