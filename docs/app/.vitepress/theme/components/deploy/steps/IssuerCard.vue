<script setup>
// One trusted issuer: its type, name, remove button and fields.
import { computed } from "vue";
import { exampleKey } from "../../../lib/deploy/config.js";
import { ISSUER_FIELDS } from "../../../lib/deploy/fields.js";
import { useDeploy } from "../../../lib/deploy/store.js";
import DeployIcon from "../DeployIcon.vue";
import FormField from "../FormField.vue";

const props = defineProps({
  /** @type {import("vue").PropType<import("../../../lib/deploy/config.js").Issuer>} */
  issuer: { type: Object, required: true },
  index: { type: Number, required: true },
});
const { config, wizard, removeIssuer, setIssuerField } = useDeploy();

// The first field spans the card; the other two share a row.
const primaryField = computed(() => ISSUER_FIELDS[props.issuer.type][0]);
const rowFields = computed(() => ISSUER_FIELDS[props.issuer.type].slice(1));
const fieldProps = (field) => ({
  inputId: `c-${props.index}-${field.domKey}`,
  popoverId: `c${props.index}${field.domKey}`,
  label: field.label,
  help: field.help,
  placeholder: field.placeholder,
  value: props.issuer[field.key] || "",
  example: config.exampleKeys.has(exampleKey(field.key, props.index)),
  describedByHelp: false,
});
const removeLabel = computed(
  () => `Remove ${props.issuer.issuer || "issuer " + (props.index + 1)}`,
);
</script>

<template>
  <li class="link" :class="{ hit: wizard.trial?.hit === index }">
    <div class="lh">
      <span class="tag" :class="{ gw: issuer.type === 'gateway' }">
        {{ issuer.type === "oidc" ? "OIDC" : "Gateway" }}
      </span>
      <span class="nm">{{ issuer.issuer || "issuer not set" }}</span>
      <button
        class="mini"
        :aria-label="removeLabel"
        :disabled="config.issuers.length <= 1"
        @click="removeIssuer(index)"
      >
        <DeployIcon name="x" />
      </button>
    </div>
    <div class="lb">
      <FormField
        v-bind="fieldProps(primaryField)"
        style="margin-bottom: 10px"
        @update="setIssuerField(index, primaryField.key, $event)"
      />
      <div class="row2">
        <FormField
          v-for="field in rowFields"
          :key="field.key"
          v-bind="fieldProps(field)"
          style="margin-bottom: 10px"
          @update="setIssuerField(index, field.key, $event)"
        />
      </div>
    </div>
  </li>
</template>
