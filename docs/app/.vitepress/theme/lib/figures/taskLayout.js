// Geometry of the task figure: landscape for wide hosts, portrait under NARROW_WIDTH.

/** Hosts narrower than this get the portrait layout, px. */
export const NARROW_WIDTH = 600;

/** Padding inside a container box; its progress bar spans the box minus this on each side. */
export const CONTAINER_PADDING = 12;

/** @typedef {[number, number]} Point */
/** @typedef {[number, number, number, number]} Rect x, y, width, height */

/**
 * @typedef {object} TaskLayout
 * @property {boolean} narrow
 * @property {string} viewBox
 * @property {Point} bucketIn top-left of the input bucket
 * @property {Point} bucketOut top-left of the output bucket
 * @property {Rect} pod
 * @property {Point} podLabel
 * @property {Point} badge top-left of the phase badge
 * @property {(i: number) => Rect} container box of container `i`
 * @property {boolean} containerWires whether containers draw a wire down to the volume
 * @property {Rect} volume
 * @property {Point} volumeLabel
 * @property {Point} volumeNote end-anchored note at the volume's top right
 * @property {string} volumeText the note while the volume exists
 * @property {(i: number) => Rect} file box of file `i` on the volume
 * @property {string} wireIn path from the input bucket to the Pod
 * @property {string} wireOut path from the Pod to the output bucket
 * @property {Point} moverFrom where the input file starts its trip
 * @property {Point} moverTo where the output file ends its trip
 */

/** @type {TaskLayout} */
const WIDE = {
  narrow: false,
  viewBox: "0 0 800 280",
  bucketIn: [22, 116],
  bucketOut: [682, 116],
  pod: [170, 22, 460, 238],
  podLabel: [186, 46],
  badge: [512, 31],
  container: (i) => [186 + i * 110, 62, 98, 62],
  containerWires: true,
  volume: [186, 160, 428, 84],
  volumeLabel: [200, 182],
  volumeNote: [600, 182],
  volumeText: "25 Gi · /inputs /work /outputs",
  file: (i) => [200 + i * 138, 196, 124, 30],
  wireIn: "M118 142H170",
  wireOut: "M630 142H682",
  moverFrom: [70, 150],
  moverTo: [730, 150],
};

/** @type {TaskLayout} */
const NARROW = {
  narrow: true,
  viewBox: "0 0 360 580",
  bucketIn: [132, 24],
  bucketOut: [132, 474],
  pod: [16, 124, 328, 320],
  podLabel: [30, 148],
  badge: [226, 132],
  // two by two
  container: (i) => [30 + (i % 2) * 154, 162 + Math.floor(i / 2) * 72, 146, 62],
  containerWires: false,
  volume: [30, 312, 300, 116],
  volumeLabel: [44, 334],
  volumeNote: [316, 334],
  volumeText: "25 Gi",
  file: (i) => [40 + i * 96, 356, 88, 30],
  wireIn: "M180 100V124",
  wireOut: "M180 444V474",
  moverFrom: [180, 60],
  moverTo: [180, 512],
};

/**
 * Layout for a host of the given width (0 when not laid out yet counts as wide).
 * @param {number} hostWidth
 * @returns {TaskLayout}
 */
export const taskLayout = (hostWidth) =>
  hostWidth > 0 && hostWidth < NARROW_WIDTH ? NARROW : WIDE;

/**
 * Centre of a rectangle.
 * @param {Rect} rect
 * @returns {Point}
 */
export const rectCenter = ([x, y, width, height]) => [x + width / 2, y + height / 2];
