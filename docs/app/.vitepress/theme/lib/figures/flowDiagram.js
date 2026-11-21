// A small animated flow: boxes joined by edges, with a labelled puck that hops from node to node
// while a caption explains each hop. Plays while on screen; pauses on hover or focus.
import { reducedMotion, whileVisible } from "../core.js";
import { parseCaption } from "./caption.js";
import { createDeltaClock } from "./clock.js";
import { captionNodes, htmlEl, showPlayState, svgEl } from "./dom.js";
import { edgeOnHop, hopHoldMs, layoutFlow, puckPosition, puckWidth } from "./flowGeometry.js";

/** Time for the puck to travel one hop, ms. */
const HOP_MS = 1700;
/** The puck fades out just after it arrives. */
const PUCK_VISIBLE_UNTIL = 1.02;
/** Where the puck rests when motion is reduced: halfway. */
const STATIC_PROGRESS = 0.5;
const NODE_RADIUS = 7;
const PUCK_HEIGHT = 22;

/** @param {ReturnType<typeof layoutFlow>} layout @param {import("./flowGeometry.js").FlowSpec} spec */
function buildFlow(layout, spec) {
  const lines = layout.edges.map(({ start, end }) =>
    svgEl("line", { class: "ed2", x1: start[0], y1: start[1], x2: end[0], y2: end[1] }),
  );
  const nodes = Object.entries(layout.boxes).map(([id, box]) => {
    const node = spec.nodes[id];
    const centerX = box.x + box.w / 2;
    const group = svgEl("g", { class: "nd" }, [
      svgEl("rect", { x: box.x, y: box.y, width: box.w, height: box.h, rx: NODE_RADIUS }),
      svgEl("text", { x: centerX, y: box.y + (node.sub ? 19 : 26), "text-anchor": "middle" }, [
        node.label,
      ]),
    ]);
    if (node.sub) {
      group.append(
        svgEl("text", { class: "s", x: centerX, y: box.y + 34, "text-anchor": "middle" }, [
          node.sub,
        ]),
      );
    }
    return { id, group };
  });
  const puckRect = svgEl("rect", { x: 0, y: -PUCK_HEIGHT / 2, height: PUCK_HEIGHT, rx: 5 });
  const puckText = svgEl("text", { x: 0, y: 4, "text-anchor": "middle" });
  const puck = svgEl("g", { class: "pk", style: "opacity:0" }, [puckRect, puckText]);

  const counter = htmlEl("span", { class: "n" });
  const captions = spec.hops.map((hop) => htmlEl("span", {}, captionNodes(parseCaption(hop.cap))));
  const prevButton = htmlEl("button", { class: "btn sm r", "aria-label": "Previous step" }, ["‹"]);
  const playButton = htmlEl("button", { class: "play", "aria-label": "Pause" });
  const nextButton = htmlEl("button", { class: "btn sm", "aria-label": "Next step" }, ["›"]);

  const root = htmlEl("div", { class: "flow" }, [
    svgEl(
      "svg",
      {
        viewBox: `0 0 ${layout.width} ${layout.height}`,
        role: "img",
        "aria-label": spec.title || "",
      },
      [...lines, ...nodes.map((node) => node.group), puck],
    ),
    htmlEl("div", { class: "fcap" }, [
      counter,
      htmlEl("span", { class: "c" }, captions),
      prevButton,
      playButton,
      nextButton,
    ]),
  ]);
  return {
    root,
    lines,
    nodes,
    puck,
    puckRect,
    puckText,
    counter,
    captions,
    prevButton,
    playButton,
    nextButton,
  };
}

/**
 * Render a flow diagram into `host`, replacing its content.
 * @param {HTMLElement} host
 * @param {import("./flowGeometry.js").FlowSpec} spec
 * @param {{ wide?: boolean }} [options] wide stretches the canvas for hosts 600px and up
 * @returns {() => void} cleanup; the drawing stays, frozen
 */
export function mountFlowDiagram(host, spec, { wide = false } = {}) {
  const reduce = reducedMotion();
  const layout = layoutFlow(spec, wide);
  const view = buildFlow(layout, spec);
  const hopCount = spec.hops.length;
  let hopIndex = 0;
  let progress = 0;
  let playing = !reduce;
  let shownPlaying = null;

  const showPlaying = () => {
    if (shownPlaying === playing) return;
    shownPlaying = playing;
    showPlayState(view.playButton, playing);
  };
  const showHop = () => {
    const hop = spec.hops[hopIndex];
    view.counter.textContent = `${hopIndex + 1}/${hopCount}`;
    view.captions.forEach((caption, i) => caption.classList.toggle("on", i === hopIndex));
    view.puckText.textContent = hop.label;
    const width = puckWidth(hop.label);
    view.puckRect.setAttribute("x", String(-width / 2));
    view.puckRect.setAttribute("width", String(width));
    view.puck.setAttribute("class", "pk " + (hop.tone || ""));
    view.nodes.forEach(({ id, group }) =>
      group.classList.toggle("on", id === hop.f || id === hop.t),
    );
    view.lines.forEach((line, i) => line.classList.toggle("on", edgeOnHop(layout.edges[i], hop)));
  };
  const placePuck = () => {
    const [x, y] = puckPosition(layout.boxes, spec.hops[hopIndex], progress);
    view.puck.style.opacity = progress < PUCK_VISIBLE_UNTIL ? "1" : "0";
    view.puck.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
  };
  const stepBy = (delta) => {
    hopIndex = (hopIndex + delta + hopCount) % hopCount;
    progress = reduce ? STATIC_PROGRESS : 0;
    showHop();
    placePuck();
  };
  const onPrev = () => stepBy(-1);
  const onNext = () => stepBy(1);
  const onPlay = () => {
    playing = !playing;
    showPlaying();
  };
  view.prevButton.addEventListener("click", onPrev);
  view.nextButton.addEventListener("click", onNext);
  view.playButton.addEventListener("click", onPlay);
  const removeListeners = () => {
    view.prevButton.removeEventListener("click", onPrev);
    view.nextButton.removeEventListener("click", onNext);
    view.playButton.removeEventListener("click", onPlay);
  };

  host.replaceChildren(view.root);
  showHop();
  showPlaying();

  if (reduce) {
    view.playButton.hidden = true;
    progress = STATIC_PROGRESS;
    placePuck();
    return removeListeners;
  }

  const elapsed = createDeltaClock();
  const stopLoop = whileVisible(host, (now) => {
    const delta = elapsed(now);
    if (progress < 1) {
      progress = Math.min(1, progress + delta / HOP_MS);
    } else if (playing && !host.matches(":hover,:focus-within")) {
      progress += delta / HOP_MS;
      if (progress > 1 + hopHoldMs(spec.hops[hopIndex]) / HOP_MS) {
        hopIndex = (hopIndex + 1) % hopCount;
        progress = 0;
        showHop();
      }
    }
    placePuck();
  });
  return () => {
    stopLoop();
    removeListeners();
  };
}
