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
          <code>{{ item.shownKey || item.key }}</code><span class="d"></span>
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

<style scoped>
/* lists of values; rows come from this template and from ReviewRow, hence :deep */
.poi .rv {
  display: grid;
  gap: 18px;
  grid-template-columns: minmax(0, 1fr);
}
.poi .rv h3 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.poi .rv h3 .cnt {
  font: 12px var(--mono);
  color: var(--muted);
  font-weight: 400;
}
.poi .rv ul {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.poi .rv li {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 8px 8px 8px 12px;
  font-size: 14px;
}
.poi .rv li + li {
  border-top: 1px solid var(--line);
}
.poi .rv li code {
  flex: none;
}
.poi .rv li :deep(.d) {
  flex: 1;
  min-width: 0;
  color: var(--muted);
  font-size: 13.5px;
  line-height: 1.4;
}
.poi .rv li :deep(.v) {
  font: 12.5px var(--mono);
  color: var(--fg);
  flex: none;
}
.poi .rv li :deep(.v.rv-ex) {
  color: var(--coral-ink);
  background: var(--coral-wash);
  border-radius: 4px;
  padding: 1px 6px;
  max-width: 55%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 0 1 auto;
}
.poi .rv li :deep(.go) {
  flex: none;
  font-size: 13px;
}
.poi .rv .miss li {
  background: var(--coral-wash);
}
.poi .rv .miss li:first-child {
  border-radius: 8px 8px 0 0;
}
.poi .rv .miss li:last-child {
  border-radius: 0 0 8px 8px;
}

/* ready / not ready */
.poi .rv .ok.neutral {
  color: var(--body);
}
.poi .rv .ok {
  color: var(--blue-ink);
  font-size: 14px;
  display: flex;
  gap: 8px;
  align-items: center;
}

/* chart defaults, grouped and collapsed */
.poi .rv details {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.poi .rv details + details {
  margin-top: 6px;
}
.poi .rv details > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 9px 12px;
  font-size: 14px;
  color: var(--fg);
}
.poi .rv details > summary::-webkit-details-marker {
  display: none;
}
.poi .rv details > summary::before {
  content: "";
  width: 6px;
  height: 6px;
  border-right: 1.5px solid var(--muted);
  border-bottom: 1.5px solid var(--muted);
  transform: rotate(-45deg);
  transition: transform 0.2s;
}
.poi .rv details[open] > summary::before {
  transform: rotate(45deg);
}
.poi .rv details > summary small {
  margin-left: auto;
  font: 12px var(--mono);
  color: var(--muted);
}
.poi .rv details ul {
  border: 0;
  border-top: 1px solid var(--line);
  border-radius: 0;
}

/* install commands */
.poi .cmd {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: var(--code-bg);
  padding: 6px 6px 6px 12px;
  font: 13px var(--mono);
  color: var(--code-fg);
  margin-bottom: 8px;
}
.poi .cmd span {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  white-space: nowrap;
}
</style>
