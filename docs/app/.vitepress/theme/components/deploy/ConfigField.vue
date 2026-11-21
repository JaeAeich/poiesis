<script setup>
// A FormField bound to one config value from FIELDS.
import { useDeploy } from "../../lib/deploy/store.js";
import FormField from "./FormField.vue";

defineProps({
  /** @type {import("vue").PropType<import("../../lib/deploy/fields.js").FieldDefinition>} */
  field: { type: Object, required: true },
});
const { config, setField } = useDeploy();
</script>

<template>
  <FormField
    :id="`w-${field.domId}`"
    :input-id="`f-${field.domId}`"
    :popover-id="field.domId"
    :label="field.label"
    :required="field.required"
    :help="field.help"
    :chart-key="field.chartKey"
    :type="field.type"
    :placeholder="field.placeholder"
    :hint-html="field.hintHtml"
    :value="config[field.key] ?? ''"
    :example="config.exampleKeys.has(field.key)"
    @update="setField(field.key, $event)"
  />
</template>
