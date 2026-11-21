<script setup>
// Hand-drawn diagrams that follow the site theme (light and dark) instead of rendered Mermaid images.
// <PoiDiagram name="overview" />, name="taskpod", name="lifecycle"
import { computed } from "vue";
const props = defineProps({ name: { type: String, required: true } });

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const box = (x, y, w, h, label, sub, cls = "") =>
  `<g class="bx ${cls}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8"/>` +
  `<text class="t" x="${x + w / 2}" y="${y + (sub ? h / 2 - 3 : h / 2 + 4)}">${esc(label)}</text>` +
  (sub ? `<text class="s" x="${x + w / 2}" y="${y + h / 2 + 13}">${esc(sub)}</text>` : "") + `</g>`;
const db = (x, y, w, h, label) =>
  `<g class="bx db"><path d="M${x} ${y + 8}v${h - 16}a${w / 2} 8 0 0 0 ${w} 0v-${h - 16}"/><ellipse cx="${x + w / 2}" cy="${y + 8}" rx="${w / 2}" ry="8"/>` +
  `<text class="t" x="${x + w / 2}" y="${y + h / 2 + 8}">${esc(label)}</text></g>`;
const arrow = (d, label, lx, ly, cls = "") =>
  `<path class="ar ${cls}" d="${d}" marker-end="url(#pd-arrow)"/>` + (label ? `<text class="lb" x="${lx}" y="${ly}">${esc(label)}</text>` : "");
const defs = `<defs><marker id="pd-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="ah"/></marker></defs>`;

function overview() {
  return {
    vb: "0 0 760 320", label: "Poiesis overview: the API, one TaskPod per task, TCtl and Postgres",
    body: defs +
      `<g class="bx pill"><rect x="10" y="62" width="110" height="40" rx="20"/><text class="t" x="65" y="86">TES client</text></g>` +
      box(170, 62, 130, 40, "Poiesis API") +
      `<g class="grp"><rect x="360" y="16" width="390" height="172" rx="12"/><text class="gl" x="376" y="38">TaskPod · one per task</text></g>` +
      box(376, 56, 78, 40, "tif", "stage in") + box(464, 56, 104, 40, "exec-0…N", "your images", "hot") + box(578, 56, 72, 40, "tof", "stage out") + box(660, 56, 74, 40, "ack", "main") +
      arrow("M454 76H462", "", 0, 0, "tiny") + arrow("M568 76H576", "", 0, 0, "tiny") + arrow("M650 76H658", "", 0, 0, "tiny") +
      box(376, 126, 358, 44, "trec · native sidecar", "records state and logs as the Pod runs", "side") +
      db(175, 236, 120, 64, "PostgreSQL") + box(600, 262, 150, 40, "TCtl", "leader-elected") +
      arrow("M120 82H168", "HTTP", 144, 74) +
      arrow("M300 82H358", "submits Job", 329, 74) +
      arrow("M235 102V234", "reads / writes", 241, 172, "") +
      arrow("M440 170C440 228 350 258 297 262", "writes state", 400, 236) +
      arrow("M675 262V190", "watches Pods", 681, 230) +
      arrow("M600 284H297", "backstop write", 450, 300)
  };
}

function taskpod() {
  let b = defs + `<g class="grp"><rect x="16" y="16" width="488" height="372" rx="14"/><text class="gl" x="34" y="40">TaskPod</text></g>`;
  b += `<text class="gl sm" x="34" y="66">init containers, in order</text>`;
  const y0 = 78;
  [["tif", "stage inputs onto the volume"], ["exec-0", "your first command"], ["exec-…", "each reads what the last wrote"], ["exec-N", "your last command"], ["tof", "upload outputs"]].forEach(([l, s], i) => {
    const y = y0 + i * 52; b += box(34, y, 250, 40, l, s, l.startsWith("exec") ? "hot" : "");
    if (i < 4) b += arrow(`M159 ${y + 40}V${y + 50}`, "", 0, 0, "tiny");
  });
  b += box(34, y0 + 5 * 52 + 4, 250, 36, "ack", "main container, exits 0");
  b += `<g class="bx side tall"><rect x="306" y="78" width="180" height="222" rx="8"/><text class="t" x="396" y="176">trec</text><text class="s" x="396" y="194">native sidecar</text><text class="s" x="396" y="210">restartPolicy: Always</text><text class="s" x="396" y="232">watches the Pod,</text><text class="s" x="396" y="248">writes state and logs</text></g>`;
  b += `<g class="vol"><rect x="306" y="314" width="180" height="62" rx="8"/><text class="t" x="396" y="340">volume</text><text class="s" x="396" y="358">shared by every container</text></g>`;
  return { vb: "0 0 520 404", label: "TaskPod layout: init containers in order, a native sidecar, a shared volume", body: b };
}

function lifecycle() {
  const A = [["c", "Client"], ["api", "Poiesis API"], ["k", "Kubernetes"], ["pod", "TaskPod"], ["trec", "trec"], ["tctl", "TCtl"], ["pg", "PostgreSQL"]];
  const X = Object.fromEntries(A.map(([k], i) => [k, 60 + i * 107]));
  const M = [
    ["c", "api", "POST /tasks"], ["api", "api", "validate, assign id"], ["api", "pg", "INSERT task (QUEUED)"], ["api", "k", "create Job (TaskPod)"], ["api", "k", "create PVC, owned by the Job"], ["api", "c", "200 {id}", "r"],
    ["k", "pod", "schedule"], ["pod", "trec", "start native sidecar"], ["trec", "pg", "state RUNNING"], ["pod", "pod", "tif → exec-0…N → tof"], ["trec", "pg", "executor and system logs"], ["k", "pod", "phase Succeeded"], ["trec", "pg", "state COMPLETE"],
    ["note"], ["tctl", "pg", "backstop write", "r"],
    ["c", "api", "GET /tasks/{id}"], ["api", "pg", "SELECT task"], ["api", "c", "200 {state}", "r"]];
  const top = 64, row = 34, H = top + M.length * row + 40;
  let b = defs;
  A.forEach(([k, l]) => { b += `<line class="lane" x1="${X[k]}" y1="${top - 14}" x2="${X[k]}" y2="${H - 16}"/>` + box(X[k] - 50, 10, 100, 34, l); });
  let n = 0;
  M.forEach((m, i) => {
    const y = top + 20 + i * row;
    if (m[0] === "note") { b += `<g class="note"><rect x="${X.tctl - 52}" y="${y - 15}" width="${X.pg - X.tctl + 104}" height="24" rx="6"/><text class="s" x="${(X.tctl + X.pg) / 2}" y="${y + 1}">backstop, always running</text></g>`; return; }
    const [f, t, label, r] = m; n++;
    if (f === t) b += arrow(`M${X[f]} ${y - 6}h34v14h-32`, "", 0, 0, "self") + `<text class="lb l" x="${X[f] + 42}" y="${y + 4}">${esc(label)}</text>`;
    else { const d = X[t] > X[f] ? -1 : 1; b += arrow(`M${X[f]} ${y}H${X[t] + d * 2}`, "", 0, 0, r ? "dash" : "") + `<text class="lb l" x="${Math.min(X[f], X[t]) + 14}" y="${y - 7}">${esc(label)}</text>`; }
    b += `<g class="num"><circle cx="${X[f]}" cy="${y}" r="8"/><text x="${X[f]}" y="${y + 3.5}">${n}</text></g>`;
  });
  return { vb: `0 0 760 ${H}`, label: "Task lifecycle, from POST /tasks to COMPLETE", body: b };
}

const d = computed(() => ({ overview, taskpod, lifecycle })[props.name]());
</script>

<template>
  <figure class="poi-diagram">
    <svg :viewBox="d.vb" role="img" :aria-label="d.label" v-html="d.body"></svg>
  </figure>
</template>

<style>
.poi-diagram{margin:24px 0;border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:12px;overflow-x:auto}
.poi-diagram svg{display:block;width:100%;height:auto;min-width:560px}
.poi-diagram .bx rect,.poi-diagram .bx path,.poi-diagram .bx ellipse{fill:var(--bg);stroke:var(--line-strong);stroke-width:1.2}
.poi-diagram .bx.hot rect{fill:var(--coral-wash);stroke:var(--coral)}
.poi-diagram .bx.side rect{fill:var(--blue-wash);stroke:var(--blue)}
.poi-diagram .bx.pill rect{stroke:var(--blue)}
.poi-diagram .grp rect{fill:none;stroke:var(--blue);stroke-width:1.3;stroke-dasharray:5 4}
.poi-diagram .vol rect{fill:var(--bg);stroke:var(--blue);stroke-opacity:.6}
.poi-diagram .note rect{fill:var(--bg);stroke:var(--line-strong);stroke-dasharray:3 3}
.poi-diagram text{font-family:var(--mono);text-anchor:middle}
.poi-diagram .t{font-size:12.5px;font-weight:500;fill:var(--fg)}
.poi-diagram .s{font-size:10.5px;fill:var(--muted)}
.poi-diagram .gl{font-size:11.5px;fill:var(--blue-ink);text-anchor:start;font-weight:500}
.poi-diagram .gl.sm{fill:var(--muted);font-weight:400;font-size:10.5px}
.poi-diagram .lb{font-size:10.5px;fill:var(--body);paint-order:stroke;stroke:var(--surface);stroke-width:5px;stroke-linejoin:round}
.poi-diagram .lb.l{text-anchor:start}
.poi-diagram .ar{fill:none;stroke:var(--muted);stroke-width:1.2}
.poi-diagram .ar.dash{stroke-dasharray:4 3}
.poi-diagram .ah{fill:var(--muted)}
.poi-diagram .lane{stroke:var(--line-strong);stroke-dasharray:2 4}
.poi-diagram .num circle{fill:var(--coral)}
.poi-diagram .num text{font-size:9.5px;font-weight:600;fill:#0d2033}
</style>
