<script setup>
// values.yaml / install.sh with highlighting, the step's lines marked, and an in-place editor.
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { downloadText, scrollBehavior } from "../../lib/deploy/browser.js";
import { highlightShellLine, highlightYamlLine } from "../../lib/deploy/highlight.js";
import { useDeploy } from "../../lib/deploy/store.js";
import CopyButton from "./CopyButton.vue";
import DeployIcon from "./DeployIcon.vue";

const TABS = [
  ["values", "values.yaml"],
  ["install", "install.sh"],
];
// The marked lines settle a third of the way down the editor.
const HIGHLIGHT_OFFSET_RATIO = 1 / 3;
const INDENT = "  ";
// The code is a <pre>: its template has no whitespace between tags, since any would show.

const deploy = useDeploy();
const { config, wizard, file, ui } = deploy;

const fileElement = ref(null);
const editorElement = ref(null);
const codeElement = ref(null);
const textareaElement = ref(null);

const isEditing = computed(() => file.editing && file.tab === "values");
const highlightLine = computed(() =>
  file.tab === "values" ? highlightYamlLine : highlightShellLine,
);
const renderedLines = computed(() =>
  deploy.fileLines.value.map((line) => ({
    tokens: highlightLine.value(line.text),
    current: line.step === wizard.step,
  })),
);

/** Keep the textarea over the code: same text (unless the user is typing) and same height. */
function syncEditor() {
  const textarea = textareaElement.value;
  if (!textarea) return;
  if (isEditing.value && document.activeElement !== textarea) {
    textarea.value = deploy.fileText.value.replace(/\n$/, "");
  }
  textarea.style.height = codeElement.value.offsetHeight + "px";
}

/** Bring the current step's first line into view. */
function scrollToCurrentLines() {
  if (isEditing.value) return;
  const first = codeElement.value?.querySelector(".hl");
  if (!first) return;
  const editor = editorElement.value;
  editor.scrollTo({
    top: Math.max(0, first.offsetTop - editor.clientHeight * HIGHLIGHT_OFFSET_RATIO),
    behavior: scrollBehavior(ui.reducedMotion),
  });
}

watch([() => deploy.fileText.value, isEditing, () => file.tab], syncEditor, { flush: "post" });

// Any form change re-centres the marked lines; editing the file by hand does not.
let skipNextScroll = false;
watch(
  [config, () => wizard.step, () => wizard.trial, () => file.tab, () => file.manualText === null],
  () => {
    if (skipNextScroll) skipNextScroll = false;
    else scrollToCurrentLines();
  },
  { flush: "post", deep: true },
);

function selectTab(tab, { scroll = true } = {}) {
  if (tab !== file.tab && !scroll) skipNextScroll = true;
  file.tab = tab;
  if (tab !== "values") file.editing = false;
}

async function toggleEditing() {
  file.editing = !file.editing;
  if (!file.editing) return;
  await nextTick();
  textareaElement.value.focus();
}

function discardEdits() {
  if (!confirm("Discard your edits and rebuild values.yaml from the form?")) return;
  file.manualText = null;
  file.editing = false;
}

function onTextareaInput(event) {
  file.manualText = event.target.value;
}

// Tab indents; Escape first lets the next Tab leave the editor, as keyboard users expect.
let tabLeaves = false;
function onTextareaKeydown(event) {
  if (event.key === "Escape") {
    tabLeaves = true;
    return;
  }
  if (event.key === "Tab" && !tabLeaves) {
    event.preventDefault();
    document.execCommand("insertText", false, INDENT);
  }
}

function onTextareaBlur() {
  tabLeaves = false;
}

function download() {
  downloadText(deploy.fileText.value, deploy.fileName.value);
  deploy.showToast("Downloaded " + deploy.fileName.value);
}

const scrollFileIntoView = (block) =>
  fileElement.value.scrollIntoView({ behavior: scrollBehavior(ui.reducedMotion), block });

onMounted(() => {
  syncEditor();
  scrollToCurrentLines();
});

defineExpose({
  /** Re-measure after the panel becomes visible again. */
  refresh: syncEditor,
  showInstall() {
    selectTab("install");
    scrollFileIntoView("nearest");
  },
  async editValues() {
    selectTab("values", { scroll: false });
    file.editing = true;
    scrollFileIntoView("start");
    await nextTick();
    textareaElement.value.focus({ preventScroll: true });
  },
  downloadValues() {
    selectTab("values", { scroll: false });
    download();
  },
});
</script>

<template>
  <div ref="fileElement" class="file">
    <div class="fh">
      <button
        v-for="[tab, label] in TABS"
        :key="tab"
        class="tab"
        :class="{ on: file.tab === tab }"
        :aria-pressed="String(file.tab === tab)"
        @click="selectTab(tab)"
      >
        {{ label }}
      </button>
      <div class="sp">
        <button
          id="edit-btn"
          class="btn sm edit-btn"
          :class="{ on: isEditing }"
          :aria-pressed="String(isEditing)"
          :disabled="file.tab !== 'values'"
          @click="toggleEditing"
        >
          {{ isEditing ? "Done" : "Edit" }}
        </button>
        <CopyButton
          id="copy-file"
          class="icon-btn"
          aria-label="Copy file"
          icon-only
          :text="() => deploy.fileText.value"
        >
          <DeployIcon name="copy" />
        </CopyButton>
        <button id="dl-file" class="icon-btn" aria-label="Download file" @click="download">
          <DeployIcon name="download" />
        </button>
      </div>
    </div>
    <div
      id="banner"
      class="banner"
      :class="{ on: file.manualText !== null && file.tab === 'values' }"
    >
      <span>Edited by hand. The form no longer changes this file.</span>
      <button id="regen" class="btn sm" @click="discardEdits">Discard edits</button>
    </div>
    <div id="ed" ref="editorElement" class="ed" :class="{ editing: isEditing }">
      <pre
        id="code"
        ref="codeElement"
      ><span v-for="(line, index) in renderedLines" :key="index" class="ln" :class="{ hl: line.current }"><template v-if="line.tokens.length"><template v-for="(token, position) in line.tokens" :key="position"><span v-if="token.className" :class="token.className">{{ token.text }}</span><template v-else>{{ token.text }}</template></template></template><template v-else> </template></span></pre>
      <textarea
        id="ta"
        ref="textareaElement"
        spellcheck="false"
        autocapitalize="off"
        autocomplete="off"
        aria-label="values.yaml"
        @input="onTextareaInput"
        @keydown="onTextareaKeydown"
        @blur="onTextareaBlur"
      ></textarea>
    </div>
    <div class="ff">
      <span class="legend">example value, replace</span>
      <span id="file-meta">{{ renderedLines.length }} lines</span>
    </div>
  </div>
</template>
