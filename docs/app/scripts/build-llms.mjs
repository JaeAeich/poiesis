// Writes public/llms.txt (an index of the docs, https://llmstxt.org) and
// public/llms-full.txt (every docs page as Markdown), in sidebar order.
// Run from docs/app: node scripts/build-llms.mjs
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import sidebar from "../.vitepress/sidebar.mjs";

const SITE = "https://poiesis.jaeaeich.com";
// Pages outside docs/ (no body in llms-full.txt).
const EXTRA = {
    "/deploy": { description: "Build a Helm values.yaml step by step, or hand a prompt to your coding agent.", body: null },
};
const root = new URL("..", import.meta.url).pathname;

function read(link) {
    const file = join(root, link.replace(/^\//, "") + ".md");
    if (!existsSync(file)) return null;
    const src = readFileSync(file, "utf8");
    const fm = src.match(/^---\n([\s\S]*?)\n---\n/);
    const description = fm?.[1].match(/^description:\s*(.+)$/m)?.[1].trim() ?? "";
    const body = fm ? src.slice(fm[0].length) : src;
    return { description, body };
}

const index = [
    "# Poiesis",
    "",
    "> Poiesis is a GA4GH Task Execution Service (TES v1.1) for Kubernetes. Workflow engines submit tasks over a REST API; each task runs as one Pod with its own volume.",
    "",
    `Deploy with the Helm chart: ${SITE}/deploy writes a values.yaml. The chart never creates Secrets; the operator creates the database Secret (DATABASE_URL) and, unless using IRSA, the S3 Secret first. Full docs in one file: ${SITE}/llms-full.txt`,
    "",
];
const full = [];

for (const group of sidebar) {
    index.push(`## ${group.text}`, "");
    for (const item of group.items) {
        const page = item.link.startsWith("/docs/") ? read(item.link) : EXTRA[item.link];
        const url = `${SITE}${item.link}`;
        index.push(`- [${item.text}](${url})${page?.description ? `: ${page.description}` : ""}`);
        if (page?.body) full.push(`<!-- ${url} -->\n\n${page.body.trim()}\n`);
    }
    index.push("");
}

writeFileSync(join(root, "public/llms.txt"), index.join("\n"));
writeFileSync(join(root, "public/llms-full.txt"), full.join("\n\n"));
console.log(`llms.txt: ${full.length} pages`);
