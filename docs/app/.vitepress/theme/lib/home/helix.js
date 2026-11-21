// A DNA double helix under the hero buttons. Hover it (or tap it on touch) and it reads out
// POIESIS, one codon per letter.
import { clamp, lerp } from "../core.js";

// M P O I E S I S stop: O is pyrrolysine, coded by TAG
export const SEQUENCE = "ATGCCGTAGATTGAATCTATTTCTTAA";
export const AMINO_ACIDS = ["M", "P", "O", "I", "E", "S", "I", "S", "*"];

const BASE_SPACING = 17; // px between base pairs
const WAVELENGTH = 260; // px per full turn
const MAX_AMPLITUDE = 30;
const AMPLITUDE_SCALE = 0.05; // of the stage width, on narrow stages
const EDGE_FADE = 0.2; // the helix fades in over this fraction of the width at each side
const STRAND_STEP = 5; // px between strand segments
const HIT_MARGIN = 60; // px beyond the amplitude that still counts as on the helix
const HOT_RATE = 0.14; // per frame, towards fully read out
const TWIST_RATE = 0.012; // radians per frame at rest
const TWIST_SPIN_RATE = 0.004; // extra per unit of wheel spin
const SCROLL_RATE = 0.18; // px per frame at rest
const SCROLL_SPIN_RATE = 0.08;
const BASE_FONT = "11px 'JetBrains Mono', monospace";
const AMINO_FONT = "600 14px 'JetBrains Mono', monospace";

/**
 * @typedef {object} Helix
 * @property {number} phase twist, radians
 * @property {number} seqOffset scroll, px
 * @property {boolean} hot reading out
 * @property {number} hotAlpha 0..1, eases towards `hot`
 * @property {number} amplitude px, as last drawn
 */

/** @returns {Helix} */
export const createHelix = () => ({
  phase: 0,
  seqOffset: 0,
  hot: false,
  hotAlpha: 0,
  amplitude: MAX_AMPLITUDE,
});

/**
 * Whether a pointer at `pointerY` is on a helix centred at `helixY`.
 * @param {Helix} helix
 */
export const isOnHelix = (helix, pointerY, helixY) =>
  Math.abs(pointerY - helixY) < helix.amplitude + HIT_MARGIN;

/**
 * Ease the read-out and, unless it is reading out, twist and scroll the helix.
 * @param {Helix} helix
 * @param {number} frames 60 fps frames since the last update
 * @param {number} spin absolute wheel spin speed
 * @param {boolean} reduce
 */
export function advanceHelix(helix, frames, spin, reduce) {
  helix.hotAlpha = lerp(helix.hotAlpha, helix.hot ? 1 : 0, reduce ? 1 : HOT_RATE * frames);
  if (!helix.hot && !reduce) {
    helix.phase += (TWIST_RATE + spin * TWIST_SPIN_RATE) * frames;
    helix.seqOffset += (SCROLL_RATE + spin * SCROLL_SPIN_RATE) * frames;
  }
}

/**
 * @param {CanvasRenderingContext2D} ctx
 * @param {Helix} helix
 * @param {{ width: number, y: number, colors: { blue: string, coral: string, muted: string } }} options
 */
export function drawHelix(ctx, helix, { width, y, colors }) {
  const amplitude = Math.min(MAX_AMPLITUDE, width * AMPLITUDE_SCALE);
  helix.amplitude = amplitude;
  const geometry = {
    width,
    y,
    amplitude,
    waveNumber: (2 * Math.PI) / WAVELENGTH,
    fade: (x) => clamp(x / (width * EDGE_FADE)) * clamp((width - x) / (width * EDGE_FADE)),
    shift: Math.floor(helix.seqOffset / BASE_SPACING),
    offset: helix.seqOffset % BASE_SPACING,
  };
  drawRungs(ctx, helix, geometry, colors);
  drawStrands(ctx, helix, geometry, colors);
  drawReadout(ctx, helix, geometry, colors);
  ctx.textAlign = "start";
  ctx.globalAlpha = 1;
}

/** Calls `fn(x, index)` for each base pair position across the width. */
function forEachBase({ width, offset }, fn) {
  for (let i = 0; ; i++) {
    const x = -BASE_SPACING - offset + i * BASE_SPACING;
    if (x > width + 20) break;
    fn(x, i);
  }
}

/** Base pairs: coral for G-C, blue for A-T, brighter on the near side. */
function drawRungs(ctx, helix, geometry, colors) {
  const { y, amplitude, waveNumber, fade, shift } = geometry;
  forEachBase(geometry, (x, i) => {
    const angle = x * waveNumber + helix.phase;
    const visibility = fade(x);
    if (visibility <= 0) return;
    const base = SEQUENCE[(i + shift) % SEQUENCE.length];
    const depth = Math.cos(angle);
    ctx.globalAlpha = visibility * (0.12 + (0.22 * (depth + 1)) / 2);
    ctx.strokeStyle = base === "G" || base === "C" ? colors.coral : colors.blue;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x, y + amplitude * Math.sin(angle));
    ctx.lineTo(x, y - amplitude * Math.sin(angle));
    ctx.stroke();
  });
}

/** The two backbones, one blue and one coral, brighter where they face you. */
function drawStrands(ctx, helix, { width, y, amplitude, waveNumber, fade }, colors) {
  for (const side of [1, -1]) {
    ctx.lineWidth = 2;
    ctx.strokeStyle = side > 0 ? colors.blue : colors.coral;
    let previous = null;
    for (let x = -20; x < width + 20; x += STRAND_STEP) {
      const angle = x * waveNumber + helix.phase;
      const pointY = y + side * amplitude * Math.sin(angle);
      const depth = side * Math.cos(angle);
      const visibility = fade(x);
      if (previous && visibility > 0) {
        ctx.globalAlpha = visibility * (0.18 + (0.5 * (depth + 1)) / 2);
        ctx.beginPath();
        ctx.moveTo(previous[0], previous[1]);
        ctx.lineTo(x, pointY);
        ctx.stroke();
      }
      previous = [x, pointY];
    }
  }
}

/** Base letters under the helix; while hot, each codon's amino acid under a bracket. */
function drawReadout(ctx, helix, geometry, colors) {
  const { y, amplitude, fade, shift } = geometry;
  const lettersY = y + amplitude + 26;
  const bracketTop = y + amplitude + 32;
  const bracketBottom = y + amplitude + 36;
  ctx.font = BASE_FONT;
  ctx.textAlign = "center";
  forEachBase(geometry, (x, i) => {
    const visibility = fade(x);
    if (visibility <= 0) return;
    const index = (i + shift) % SEQUENCE.length;
    ctx.globalAlpha = visibility * (0.24 + 0.5 * helix.hotAlpha);
    ctx.fillStyle = colors.muted;
    ctx.fillText(SEQUENCE[index], x, lettersY);

    const amino = AMINO_ACIDS[index / 3];
    if (helix.hotAlpha <= 0.02 || index % 3 !== 0 || amino === "*" || amino === "M") return;
    ctx.globalAlpha = visibility * helix.hotAlpha * 0.6;
    ctx.strokeStyle = colors.muted;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x - 6, bracketTop);
    ctx.lineTo(x - 6, bracketBottom);
    ctx.lineTo(x + 40, bracketBottom);
    ctx.lineTo(x + 40, bracketTop);
    ctx.stroke();
    ctx.globalAlpha = visibility * helix.hotAlpha;
    ctx.fillStyle = amino === "O" ? colors.coral : colors.blue;
    ctx.font = AMINO_FONT;
    ctx.fillText(amino, x + BASE_SPACING, y + amplitude + 54);
    ctx.font = BASE_FONT;
  });
}
