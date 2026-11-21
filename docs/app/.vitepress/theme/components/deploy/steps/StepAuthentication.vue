<script setup>
import { useDeploy } from "../../../lib/deploy/store.js";
import DeployIcon from "../DeployIcon.vue";
import StepActions from "../StepActions.vue";
import StepIntro from "../StepIntro.vue";
import IssuerCard from "./IssuerCard.vue";
import RequestTrial from "./RequestTrial.vue";

defineProps({ step: { type: Number, required: true } });
const { config, wizard, addIssuer, toggleApiKeys } = useDeploy();
</script>

<template>
  <StepIntro text="Who may call the API. Each token is checked by the issuer that signed it." />
  <div class="sublab">Trusted issuers</div>
  <ol class="chain">
    <IssuerCard
      v-for="(issuer, index) in config.issuers"
      :key="issuer.id"
      :issuer="issuer"
      :index="index"
    />
    <li v-if="config.apiKeys" class="link" :class="{ hit: wizard.trial?.hit === 'key' }">
      <div class="lh">
        <span class="tag key">API keys</span>
        <span class="nm">poi_… for engines, minted by OIDC users</span>
        <button class="mini" aria-label="Turn API keys off" @click="toggleApiKeys()">
          <DeployIcon name="x" />
        </button>
      </div>
    </li>
  </ol>
  <div class="adds">
    <button class="btn sm" @click="addIssuer('oidc')">+ OIDC issuer</button>
    <button class="btn sm" @click="addIssuer('gateway')">+ Gateway JWT</button>
    <button v-if="!config.apiKeys" class="btn sm" @click="toggleApiKeys()">+ API keys</button>
    <span class="soonchip">GA4GH Passports · planned</span>
  </div>
  <RequestTrial />
  <StepActions :step="step" />
</template>
