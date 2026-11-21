// Builds the task figure's DOM for a layout.
import { captionNodes, htmlEl, svgEl } from "./dom.js";
import { parseCaption } from "./caption.js";
import { CONTAINER_PADDING as PAD } from "./taskLayout.js";
import { CONTAINERS, FILES, POD_NAME, TASK_STEPS } from "./taskSteps.js";

const BADGE_WIDTH = 104;
const BADGE_HEIGHT = 22;
const BUCKET_WIDTH = 96;
const BUCKET_HEIGHT = 52;
const BUCKET_LIP = 10;
const MOVER_WIDTH = 100;
const MOVER_HEIGHT = 24;

/** A cylinder (object storage) with a caption under it and a file name inside. */
function bucket([x, y], label) {
  const half = BUCKET_WIDTH / 2;
  const fileName = svgEl("text", { class: "ts", x: x + half, y: y + 36, "text-anchor": "middle" });
  const group = svgEl("g", { class: "bucket" }, [
    svgEl("path", {
      d: `M${x} ${y}v${BUCKET_HEIGHT}a${half} ${BUCKET_LIP} 0 0 0 ${BUCKET_WIDTH} 0v-${BUCKET_HEIGHT}`,
    }),
    svgEl("ellipse", { cx: x + half, cy: y, rx: half, ry: BUCKET_LIP }),
    svgEl("text", { class: "t", x: x + half, y: y + 84, "text-anchor": "middle" }, [label]),
    fileName,
  ]);
  return { group, fileName };
}

/** A container box: name, role, status dot or check, and a progress bar. */
function containerBox([x, y, width, height], { name, role }) {
  const bar = svgEl("rect", {
    class: "pfg",
    x: x + PAD,
    y: y + height - PAD,
    width: 0,
    height: 3,
    rx: 1.5,
  });
  const group = svgEl("g", {}, [
    svgEl("rect", { class: "box", x, y, width, height, rx: 6 }),
    svgEl("text", { class: "t", x: x + PAD, y: y + 24 }, [name]),
    svgEl("text", { class: "ts", x: x + PAD, y: y + 42 }, [role]),
    svgEl("circle", { class: "dot", cx: x + width - 14, cy: y + 19, r: 4 }),
    svgEl("path", { class: "chk", d: `M${x + width - 19} ${y + 19}l3.5 3.5 6-7` }),
    svgEl("rect", {
      class: "pbg",
      x: x + PAD,
      y: y + height - PAD,
      width: width - 2 * PAD,
      height: 3,
      rx: 1.5,
    }),
    bar,
  ]);
  return { group, bar };
}

function fileChip([x, y, width, height], name) {
  return svgEl("g", { class: "file", style: "opacity:0" }, [
    svgEl("rect", { x, y, width, height, rx: 5 }),
    svgEl(
      "text",
      {
        class: "ts",
        x: x + width / 2,
        y: y + 19,
        "text-anchor": "middle",
        style: "fill:var(--fg)",
      },
      [name],
    ),
  ]);
}

/**
 * @typedef {ReturnType<typeof buildTaskFigure>} TaskFigureView
 */

/**
 * Build the figure: the SVG drawing, the step timeline and the captions.
 * @param {import("./taskLayout.js").TaskLayout} layout
 * @param {{ compact: boolean }} options compact hides the step labels (side panel)
 */
export function buildTaskFigure(layout, { compact }) {
  const inputBucket = bucket(layout.bucketIn, "s3://in");
  const outputBucket = bucket(layout.bucketOut, "s3://out");
  const wireIn = svgEl("path", { class: "wire", d: layout.wireIn });
  const wireOut = svgEl("path", { class: "wire", d: layout.wireOut });

  const [podX, podY, podWidth, podHeight] = layout.pod;
  const [badgeX, badgeY] = layout.badge;
  const badgeText = svgEl(
    "text",
    { x: badgeX + BADGE_WIDTH / 2, y: badgeY + 15, "text-anchor": "middle" },
    ["Pending"],
  );
  const badge = svgEl("g", { class: "badge" }, [
    svgEl("rect", {
      x: badgeX,
      y: badgeY,
      width: BADGE_WIDTH,
      height: BADGE_HEIGHT,
      rx: BADGE_HEIGHT / 2,
    }),
    badgeText,
  ]);

  const [volumeX, volumeY, volumeWidth, volumeHeight] = layout.volume;
  const containerWires = CONTAINERS.map((_, i) => {
    const [x, y, width, height] = layout.container(i);
    const d = layout.containerWires ? `M${x + width / 2} ${y + height}V${volumeY}` : "M0 0";
    return svgEl("path", { class: "wire", d });
  });
  const containers = CONTAINERS.map((container, i) => containerBox(layout.container(i), container));

  const volumeNote = svgEl("text", {
    class: "ts",
    x: layout.volumeNote[0],
    y: layout.volumeNote[1],
    "text-anchor": "end",
  });
  const files = FILES.map((name, i) => fileChip(layout.file(i), name));
  const volume = svgEl("g", { class: "vol" }, [
    svgEl("rect", {
      class: "box",
      x: volumeX,
      y: volumeY,
      width: volumeWidth,
      height: volumeHeight,
      rx: 6,
    }),
    svgEl("text", { class: "t", x: layout.volumeLabel[0], y: layout.volumeLabel[1] }, ["volume"]),
    volumeNote,
    ...files,
  ]);

  const moverText = svgEl("text", { x: 0, y: 4, "text-anchor": "middle" });
  const mover = svgEl("g", { class: "mover", style: "opacity:0" }, [
    svgEl("rect", {
      x: -MOVER_WIDTH / 2,
      y: -MOVER_HEIGHT / 2,
      width: MOVER_WIDTH,
      height: MOVER_HEIGHT,
      rx: 5,
    }),
    moverText,
  ]);

  const drawing = svgEl(
    "svg",
    { viewBox: layout.viewBox, role: "img", "aria-label": "How a task runs, step by step" },
    [
      inputBucket.group,
      outputBucket.group,
      wireIn,
      wireOut,
      svgEl("rect", { class: "pod", x: podX, y: podY, width: podWidth, height: podHeight, rx: 10 }),
      svgEl("text", { class: "ts", x: layout.podLabel[0], y: layout.podLabel[1] }, [POD_NAME]),
      badge,
      ...containerWires,
      ...containers.map((container) => container.group),
      volume,
      mover,
    ],
  );

  const playButton = htmlEl("button", { class: "play", "aria-label": "Pause" });
  const segmentBars = TASK_STEPS.map(() => htmlEl("b"));
  const segments = TASK_STEPS.map((step, i) =>
    htmlEl("button", { class: "seg", "aria-label": `Step ${i + 1}: ${step.label}` }, [
      htmlEl("i", {}, [segmentBars[i]]),
      htmlEl("span", {}, [step.label]),
    ]),
  );
  const timeline = htmlEl("div", { class: "tl" }, [
    playButton,
    htmlEl(
      "div",
      { class: "segs", style: `grid-template-columns:repeat(${TASK_STEPS.length},1fr)` },
      segments,
    ),
  ]);

  const captions = TASK_STEPS.map((step) =>
    htmlEl("span", {}, captionNodes(parseCaption(step.caption))),
  );
  const captionBox = htmlEl("div", { class: "tcap", "aria-live": "off" }, captions);

  const root = htmlEl("div", { class: compact ? "tfig compact" : "tfig" }, [
    drawing,
    timeline,
    captionBox,
  ]);

  return {
    root,
    inputBucket,
    outputBucket,
    wireIn,
    wireOut,
    badge,
    badgeText,
    containerWires,
    containers,
    volume,
    volumeNote,
    files,
    mover,
    moverText,
    playButton,
    segments,
    segmentBars,
    captions,
    captionBox,
  };
}
