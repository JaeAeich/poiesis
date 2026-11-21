// The engines shown on the home page. Status is only what we have run end to end; keep it honest.

/**
 * A logo is either an inline single-path SVG (24x24 viewBox) or an image in /public/logos.
 * @typedef {{ path: string, fill: string } | { file: string, crop?: boolean }} EngineLogo
 *
 * @typedef {object} Engine
 * @property {string} name
 * @property {string} doc anchor in the workflow engines guide
 * @property {string} detail
 * @property {"" | "part" | "no"} status CSS modifier: tested, partly tested, not tested yet
 * @property {string} label status text
 * @property {EngineLogo} logo
 * @property {number} size logo diameter in the playground, px
 */

const NEXTFLOW_PATH =
  "M.005 4.424V0c6.228.259 11.227 5.268 11.477 11.506H7.058C6.828 7.715 3.786 4.673.005 4.424m7.082 8.089h4.424C11.251 18.741 6.242 23.741.005 23.99v-4.423c3.79-.231 6.832-3.273 7.082-7.054m9.826-1.036h-4.424C12.749 5.249 17.758.25 23.995 0v4.424c-3.79.23-6.832 3.263-7.082 7.053m7.082 8.099V24c-6.228-.259-11.227-5.268-11.477-11.506h4.424c.23 3.791 3.272 6.833 7.053 7.082";
const CWL_PATH =
  "M13.905 0L8.571 5.4l.037.037.096.096 3.586 3.395-2.24 2.252h-.01l-1.576 1.586 3.737 3.766-3.735 3.803.126.139v.012L12.052 24l1.608-1.64-1.98-2.034 3.737-3.79-1.608-1.642-.01.012-2.13-2.129 3.867-3.866-.017-.015.016-.016-3.641-3.524 3.64-3.694z";

/** @type {Engine[]} */
export const ENGINES = [
  {
    name: "Nextflow",
    doc: "nextflow",
    detail: "nf-ga4gh 1.5.0",
    status: "",
    label: "Tested · 25.10.4",
    logo: { path: NEXTFLOW_PATH, fill: "#0DC09D" },
    size: 96,
  },
  {
    name: "Snakemake",
    doc: "snakemake",
    detail: "TES executor 0.1.3",
    status: "",
    label: "Tested · 9.27.2",
    logo: { file: "snakemake.svg" },
    size: 88,
  },
  {
    name: "py-tes",
    doc: "py-tes",
    detail: "GA4GH Python client",
    status: "",
    label: "Tested · 1.1.4",
    logo: { file: "ga4gh.png" },
    size: 76,
  },
  {
    name: "TES compliance suite",
    doc: "tes-compliance-suite",
    detail: "GA4GH conformance tests",
    status: "",
    label: "Passing",
    logo: { file: "ga4gh.png" },
    size: 70,
  },
  {
    name: "Sprocket",
    doc: "sprocket",
    detail: "WDL",
    status: "",
    label: "Tested · 0.34.1",
    logo: { file: "sprocket.png", crop: true },
    size: 80,
  },
  {
    name: "cwl-tes",
    doc: "cwl-tes",
    detail: "API key as Basic password",
    status: "part",
    label: "Partly tested",
    logo: { path: CWL_PATH, fill: "currentColor" },
    size: 68,
  },
  {
    name: "Cromwell",
    doc: "cromwell",
    detail: "WDL",
    status: "no",
    label: "Not tested yet",
    logo: { file: "cromwell.png" },
    size: 82,
  },
  {
    name: "Toil",
    doc: "toil",
    detail: "CWL, WDL",
    status: "no",
    label: "Not tested yet",
    logo: { file: "toil.svg" },
    size: 72,
  },
];

/** Size of the "another engine?" bubble in the playground, px. */
export const ASK_BUBBLE_SIZE = 66;

/** New-issue link, prefilled, for asking us to test another engine. */
export const ENGINE_REQUEST_URL =
  "https://github.com/JaeAeich/poiesis/issues/new?title=Engine%20support%3A%20&body=Engine%20and%20version%3A%0ALink%3A%0AWhat%20you%20tried%3A";
