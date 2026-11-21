// What the site footer shows: link columns, and POIESIS spelled in the periodic table.

/**
 * @typedef {object} FooterLink
 * @property {string} text
 * @property {string} href site paths start with "/" and get the base prepended
 */

/** @type {{ title: string, links: FooterLink[] }[]} */
export const LINK_COLUMNS = [
  {
    title: "Product",
    links: [
      { text: "Docs", href: "/docs/start/what-is-poiesis" },
      { text: "Deploy", href: "/deploy" },
      { text: "GitHub", href: "https://github.com/JaeAeich/poiesis" },
    ],
  },
  {
    title: "Project",
    links: [
      { text: "GA4GH TES v1.1", href: "https://github.com/ga4gh/task-execution-schemas" },
      { text: "Apache 2.0", href: "https://github.com/JaeAeich/poiesis/blob/dev/LICENSE" },
      { text: "Helm chart", href: "/docs/reference/helm-values" },
    ],
  },
];

/**
 * @typedef {object} ChemicalElement
 * @property {string} name
 * @property {number} number atomic number
 * @property {string} symbol
 * @property {string} mass standard atomic weight, or [mass number] of the longest-lived isotope
 * @property {number[]} shells electrons per shell
 * @property {string} configuration electron configuration
 * @property {"curie" | "kelp" | "einstein" | "retort" | "vesuvius"} art illustration and accent
 * @property {boolean} darkArt whether the illustration has a dark-mode variant
 * @property {string} fact
 */

// Art: public-domain sources from Wikimedia Commons (Curie 1912 photo, Haeckel 1904 plate,
// Schmutzer 1921 etching, Lavoisier 1789 plate, Vesuvius 1872 engraving).
/** @type {ChemicalElement[]} */
export const ELEMENTS = [
  {
    name: "Polonium",
    number: 84,
    symbol: "Po",
    mass: "[209]",
    shells: [2, 8, 18, 32, 18, 6],
    configuration: "[Xe] 4f¹⁴ 5d¹⁰ 6s² 6p⁴",
    art: "curie",
    darkArt: true,
    fact: "Found by Marie and Pierre Curie in 1898. Named after Poland, her homeland.",
  },
  {
    name: "Iodine",
    number: 53,
    symbol: "I",
    mass: "126.90",
    shells: [2, 8, 18, 18, 7],
    configuration: "[Kr] 4d¹⁰ 5s² 5p⁵",
    art: "kelp",
    darkArt: false,
    fact: "Bernard Courtois found it in seaweed ash in 1811.",
  },
  {
    name: "Einsteinium",
    number: 99,
    symbol: "Es",
    mass: "[252]",
    shells: [2, 8, 18, 32, 29, 8, 2],
    configuration: "[Rn] 5f¹¹ 7s²",
    art: "einstein",
    darkArt: true,
    fact: "First seen in the debris of the 1952 H-bomb test. Named after Einstein.",
  },
  {
    name: "Iodine",
    number: 53,
    symbol: "I",
    mass: "126.90",
    shells: [2, 8, 18, 18, 7],
    configuration: "[Kr] 4d¹⁰ 5s² 5p⁵",
    art: "retort",
    darkArt: false,
    fact: "Heated with acid, the ash gave off a violet vapour. Greek iodes: violet.",
  },
  {
    name: "Sulfur",
    number: 16,
    symbol: "S",
    mass: "32.06",
    shells: [2, 8, 6],
    configuration: "[Ne] 3s² 3p⁴",
    art: "vesuvius",
    darkArt: true,
    fact: "The brimstone of old texts. Volcanoes breathe it out.",
  },
];

/** The coral tile: Einsteinium, the "E" in the middle of POIESIS. */
export const HIGHLIGHT_SYMBOL = "Es";
