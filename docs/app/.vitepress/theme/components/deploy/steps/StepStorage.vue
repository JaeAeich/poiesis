<script setup>
import { S3_CREDENTIAL_MODES } from "../../../lib/deploy/config.js";
import { FIELDS } from "../../../lib/deploy/fields.js";
import { useDeploy } from "../../../lib/deploy/store.js";
import ConfigField from "../ConfigField.vue";
import ProviderLogo from "../ProviderLogo.vue";
import SegmentedControl from "../SegmentedControl.vue";
import StepActions from "../StepActions.vue";
import StepIntro from "../StepIntro.vue";

defineProps({ step: { type: Number, required: true } });

// Planned backends: a logo name or a short text mark, and the tracking issue.
const PLANNED = [
  { logo: "gcs", name: "Google Cloud Storage", issue: 29 },
  { logo: "az", name: "Azure Blob", issue: 29 },
  { mark: "FTP", name: "FTP / SFTP", issue: 29 },
  { mark: "FS", name: "FUSE mounts", issue: 27 },
];
const { config } = useDeploy();
</script>

<template>
  <StepIntro text="Where task inputs come from and outputs go." />
  <div class="tiles">
    <button class="tile sel">
      <span class="lg logo"><ProviderLogo name="s3" /></span>
      <span><b>S3-compatible</b><small>AWS, MinIO, Ceph, SeaweedFS</small></span>
    </button>
    <div v-for="backend in PLANNED" :key="backend.name" class="tile soon">
      <span class="lg" :class="{ logo: backend.logo }">
        <ProviderLogo v-if="backend.logo" :name="backend.logo" />
        <template v-else>{{ backend.mark }}</template>
      </span>
      <span>
        <b>{{ backend.name }}</b
        ><small>Planned · #{{ backend.issue }}</small>
      </span>
    </div>
  </div>
  <ConfigField :field="FIELDS.s3Endpoint" />
  <ConfigField :field="FIELDS.s3Region" />
  <SegmentedControl
    v-model="config.s3Credentials"
    label="Credentials"
    :options="S3_CREDENTIAL_MODES"
  />
  <ConfigField v-if="config.s3Credentials === 'secret'" :field="FIELDS.s3Secret" />
  <ConfigField v-else :field="FIELDS.s3RoleArn" />
  <StepActions :step="step" />
</template>
