<script setup>
import { AZURE_CREDENTIAL_MODES, S3_CREDENTIAL_MODES } from "../../../lib/deploy/config.js";
import { FIELDS } from "../../../lib/deploy/fields.js";
import { useDeploy } from "../../../lib/deploy/store.js";
import ConfigField from "../ConfigField.vue";
import ProviderLogo from "../ProviderLogo.vue";
import SegmentedControl from "../SegmentedControl.vue";
import StepActions from "../StepActions.vue";
import StepIntro from "../StepIntro.vue";

defineProps({ step: { type: Number, required: true } });

const STORES = [
  { id: "s3", logo: "s3", name: "S3-compatible", note: "AWS, MinIO, Ceph, SeaweedFS" },
  { id: "gcs", logo: "gcs", name: "Google Cloud", note: "gs:// · experimental" },
  { id: "azure", logo: "az", name: "Azure Blob", note: "az:// · experimental" },
];
// Planned backends: a short text mark and the tracking issue.
const PLANNED = [
  { mark: "FTP", name: "FTP / SFTP", issue: 29 },
  { mark: "FS", name: "FUSE mounts", issue: 27 },
];
const { config } = useDeploy();
</script>

<template>
  <StepIntro text="Where task inputs come from and outputs go." />
  <div class="tiles" role="group" aria-label="Object store">
    <button
      v-for="store in STORES"
      :key="store.id"
      class="tile"
      :class="{ sel: config.storage === store.id }"
      :aria-pressed="String(config.storage === store.id)"
      @click="config.storage = store.id"
    >
      <span class="lg logo"><ProviderLogo :name="store.logo" /></span>
      <span
        ><b>{{ store.name }}</b
        ><small>{{ store.note }}</small></span
      >
    </button>
    <div v-for="backend in PLANNED" :key="backend.name" class="tile soon">
      <span class="lg">{{ backend.mark }}</span>
      <span>
        <b>{{ backend.name }}</b><small>Planned · #{{ backend.issue }}</small>
      </span>
    </div>
  </div>

  <template v-if="config.storage === 's3'">
    <ConfigField :field="FIELDS.s3Endpoint" />
    <ConfigField :field="FIELDS.s3Region" />
    <SegmentedControl
      v-model="config.s3Credentials"
      label="Credentials"
      :options="S3_CREDENTIAL_MODES"
    />
    <ConfigField v-if="config.s3Credentials === 'secret'" :field="FIELDS.s3Secret" />
    <ConfigField v-else :field="FIELDS.s3RoleArn" />
  </template>
  <ConfigField v-else-if="config.storage === 'gcs'" :field="FIELDS.gcsSecret" />
  <template v-else>
    <ConfigField :field="FIELDS.azureAccount" />
    <SegmentedControl
      v-model="config.azureCredentials"
      label="Credentials"
      :options="AZURE_CREDENTIAL_MODES"
    />
    <ConfigField v-if="config.azureCredentials === 'secret'" :field="FIELDS.azureSecret" />
    <div v-else class="row2">
      <ConfigField :field="FIELDS.azureClientId" />
      <ConfigField :field="FIELDS.azureTenantId" />
    </div>
  </template>
  <StepActions :step="step" />
</template>
