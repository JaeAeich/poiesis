<script setup>
import { TLS_MODES } from "../../../lib/deploy/config.js";
import { FIELDS } from "../../../lib/deploy/fields.js";
import { useDeploy } from "../../../lib/deploy/store.js";
import ConfigField from "../ConfigField.vue";
import ProviderLogo from "../ProviderLogo.vue";
import SegmentedControl from "../SegmentedControl.vue";
import StepActions from "../StepActions.vue";
import StepIntro from "../StepIntro.vue";

defineProps({ step: { type: Number, required: true } });

const PRESETS = [
  ["aws", "AWS preset"],
  ["gc", "Google Cloud preset"],
  ["az", "Azure preset"],
];
const { config } = useDeploy();
</script>

<template>
  <StepIntro text="Where Poiesis runs, and the URL people use to reach it." />
  <div class="tiles">
    <div class="tile sel">
      <span class="lg logo"><ProviderLogo name="k8s" /></span>
      <span><b>Any Kubernetes</b><small>EKS, GKE, AKS, k3s, bare metal</small></span>
    </div>
    <div v-for="[logo, name] in PRESETS" :key="logo" class="tile soon preset">
      <span class="lg logo"><ProviderLogo :name="logo" /></span>
      <span
        ><b>{{ name }}</b
        ><small>Planned, with its storage</small></span
      >
    </div>
    <p class="soon-line">AWS, Google Cloud and Azure presets are planned</p>
  </div>
  <ConfigField :field="FIELDS.publicUrl" />
  <div class="sublab">TLS</div>
  <SegmentedControl v-model="config.tlsMode" label="TLS" :options="TLS_MODES" />
  <ConfigField v-if="config.tlsMode === 'cert-manager'" :field="FIELDS.clusterIssuer" />
  <ConfigField v-else-if="config.tlsMode === 'secret'" :field="FIELDS.tlsSecret" />
  <div class="row2">
    <ConfigField :field="FIELDS.namespace" />
    <ConfigField :field="FIELDS.ingressClass" />
  </div>
  <StepActions :step="step" />
</template>

<style scoped>
/* on phones the preset tiles give way to one line */
.poi .soon-line {
  display: none;
  margin: 0;
  font-size: 13px;
  color: var(--muted);
}
@media (max-width: 760px) {
  .poi .tile.preset {
    display: none;
  }
  .poi .soon-line {
    display: block;
  }
}
</style>
