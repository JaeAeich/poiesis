#!/usr/bin/env node
// Render every diagrams/*.mmd into public/diagrams/*.svg with mmdc.
// Idempotent: skips files whose .svg is newer than the .mmd source.

import { spawnSync } from "node:child_process";
import {
    existsSync,
    mkdirSync,
    readdirSync,
    statSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = dirname(here);
const srcDir = join(root, "diagrams");
const outDir = join(root, "public", "diagrams");

if (!existsSync(srcDir)) {
    console.error(`no diagrams source dir: ${srcDir}`);
    process.exit(0);
}
mkdirSync(outDir, { recursive: true });

const sources = readdirSync(srcDir).filter((f) => f.endsWith(".mmd"));
if (sources.length === 0) {
    console.log("no .mmd diagrams to render");
    process.exit(0);
}

let rendered = 0;
let skipped = 0;
for (const name of sources) {
    const src = join(srcDir, name);
    const out = join(outDir, name.replace(/\.mmd$/, ".svg"));

    if (existsSync(out)) {
        const srcMtime = statSync(src).mtimeMs;
        const outMtime = statSync(out).mtimeMs;
        if (outMtime >= srcMtime) {
            skipped++;
            continue;
        }
    }

    const result = spawnSync(
        "npx",
        [
            "--yes",
            "@mermaid-js/mermaid-cli",
            "-i",
            src,
            "-o",
            out,
            "-b",
            "transparent",
        ],
        { stdio: "inherit" },
    );
    if (result.status !== 0) {
        console.error(`mmdc failed on ${name}`);
        process.exit(result.status ?? 1);
    }
    rendered++;
}

console.log(`diagrams: rendered ${rendered}, skipped ${skipped}`);
