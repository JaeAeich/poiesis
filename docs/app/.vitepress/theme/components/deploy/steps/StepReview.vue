<script setup>
// What is still missing, what is an example, what changed, and how to install.
import { computed } from "vue";
import {
  advancedFieldId,
  advancedValue,
  changedAdvancedItems,
  defaultAdvancedItems,
  formatAdvancedValue,
} from "../../../lib/deploy/advanced.js";
import {
  helmInstallCommand,
  releaseNamespace,
  secretCount,
} from "../../../lib/deploy/install-sh.js";
import { STEP } from "../../../lib/deploy/steps.js";
import { useDeploy } from "../../../lib/deploy/store.js";
import { exampleEntries, missingFields } from "../../../lib/deploy/validation.js";
import CopyButton from "../CopyButton.vue";
import DeployIcon from "../DeployIcon.vue";
import ReviewRow from "./ReviewRow.vue";

const SUMMARY_LABEL_CHARS = 48;

defineProps({ step: { type: Number, required: true } });
const deploy = useDeploy();
const { config, wizard } = deploy;

const missing = computed(() => missingFields(config));
const examples = computed(() => exampleEntries(config));
const changed = computed(() => changedAdvancedItems(config));
const defaults = computed(() => defaultAdvancedItems(config));
const defaultGroups = computed(() =>
  [...new Set(defaults.value.map((item) => item.group))].map((name) => {
    const items = defaults.value.filter((item) => item.group === name);
    const labels = items.map((item) => item.label).join(", ");
    const summary =
      labels.slice(0, SUMMARY_LABEL_CHARS) + (labels.length > SUMMARY_LABEL_CHARS ? "…" : "");
    return { name, items, summary };
  }),
);
const secrets = computed(() => secretCount(config));
const installCommand = computed(() => helmInstallCommand(releaseNamespace(config)));

function editAdvanced(item) {
  wizard.openAdvancedGroup = item.group;
  deploy.goToStep(STEP.ADVANCED, advancedFieldId(item.key));
}
</script>

<template>
  <div class="rv">
    <div v-if="missing.length">
      <h3>
        Still required <span class="cnt">{{ missing.length }}</span>
      </h3>
      <ul class="miss">
        <ReviewRow v-for="entry in missing" :key="entry.label" :entry="entry" action="Set" />
      </ul>
    </div>
    <div v-else-if="examples.length" class="ok neutral">
      Ready once you replace {{ examples.length }} example value{{
        examples.length > 1 ? "s" : ""
      }}.
    </div>
    <div v-else class="ok">
      <DeployIcon name="check" width="16" height="16" />Every required value is set.
    </div>

    <div v-if="examples.length">
      <h3>
        Example values to replace <span class="cnt">{{ examples.length }}</span>
      </h3>
      <ul>
        <ReviewRow
          v-for="(entry, position) in examples"
          :key="position"
          :entry="entry"
          action="Change"
          :value="entry.value"
        />
      </ul>
    </div>

    <div v-if="changed.length">
      <h3>
        Changed from the defaults <span class="cnt">{{ changed.length }}</span>
      </h3>
      <ul>
        <li v-for="item in changed" :key="item.key">
          <code>{{ item.shownKey || item.key }}</code
          ><span class="d"></span>
          <span class="v">{{ formatAdvancedValue(advancedValue(config, item)) }}</span>
          <button class="btn ghost sm go" @click="editAdvanced(item)">Edit</button>
        </li>
      </ul>
    </div>

    <div>
      <h3>
        Left at the chart defaults <span class="cnt">{{ defaults.length }}</span>
      </h3>
      <details v-for="group in defaultGroups" :key="group.name">
        <summary>
          {{ group.name }}<small>{{ group.summary }}</small>
        </summary>
        <ul>
          <li v-for="item in group.items" :key="item.key">
            <span class="d"
              ><b style="font-weight: 500; color: var(--fg)">{{ item.label }}</b
              ><br />{{ item.why }}</span
            >
            <span class="v">{{ formatAdvancedValue(item.defaultValue) }}</span>
            <button class="btn ghost sm go" @click="editAdvanced(item)">Change</button>
          </li>
        </ul>
      </details>
    </div>

    <div>
      <h3>Install</h3>
      <div class="cmd">
        <span>{{ secrets }} Secret{{ secrets > 1 ? "s" : "" }} to create, in install.sh</span>
        <button class="mini" aria-label="Show install.sh" @click="deploy.showInstallTab()">
          <DeployIcon name="file" />
        </button>
      </div>
      <div class="cmd">
        <span>{{ installCommand }}</span>
        <CopyButton class="mini" aria-label="Copy" icon-only :text="installCommand">
          <DeployIcon name="copy" />
        </CopyButton>
      </div>
    </div>
    <div class="acts">
      <button class="btn primary sm" @click="deploy.editValuesHere()">Edit values.yaml here</button>
      <button id="dl2" class="btn sm" @click="deploy.downloadValues()">Download</button>
    </div>
  </div>
</template>
