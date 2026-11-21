// Engine logos: drag, throw, bounce off each other and the table. Hovering a logo highlights
// its row in the table, and the other way round.
import { bag, clamp, whileVisible } from "../core.js";
import { phoneSlots, stepBodies, tableSlots, throwVelocity } from "./enginePhysics.js";
import { isCovered } from "./shared.js";

const PHONE_WIDTH = 760; // px viewport
const DESKTOP_FLOOR = 36; // px kept clear at the bottom of the field
const TABLE_MARGIN = 14; // px around the table the logos bounce off
const MAX_STEP_MS = 40;
const DEFAULT_STEP_MS = 16;
const PHASE_STEP = 1.7; // bob phase between logos
const POINTER_HISTORY = 8;
const CLICK_MAX_MOVE = 5; // px; a drag further than this is not a click

/**
 * @param {HTMLElement} root the home page root
 * @param {{ reduce: boolean }} options
 * @returns {() => void} cleanup
 */
export function mountEngines(root, { reduce }) {
  const section = root.querySelector("#s-eng");
  const field = root.querySelector("#eng-field");
  const table = root.querySelector("#eng-center");
  const logos = [...field.querySelectorAll(".pl")];
  const rows = [...root.querySelectorAll(".eng li")];
  const cleanup = bag();
  /** @type {import("./enginePhysics.js").World} */
  const world = {
    width: 0,
    height: 0,
    floor: DESKTOP_FLOOR,
    table: { x: 0, y: 0, w: 0, h: 0 },
    clock: 0,
  };
  /** @type {import("./enginePhysics.js").Body[]} */
  let bodies = [];
  let drag = null;
  let lastFrame = 0;
  let lastDragDistance = 0;
  let ready = false;

  const visibleLogos = () => logos.filter((el) => el.offsetWidth > 0);
  const findBody = (el) => bodies.find((body) => body.el === el);
  const draw = () => {
    for (const body of bodies) {
      body.el.style.transform = `translate(${(body.x - body.r).toFixed(1)}px,${(body.y - body.r).toFixed(1)}px)`;
    }
  };

  function resize() {
    const rect = field.getBoundingClientRect();
    if (!rect.width) return;
    world.width = rect.width;
    world.height = rect.height;
    const phone = innerWidth <= PHONE_WIDTH;
    ready = true;
    world.floor = phone ? 0 : DESKTOP_FLOOR;
    if (phone) {
      world.table = { x: -1e4, y: -1e4, w: 0, h: 0 };
    } else {
      const box = table.getBoundingClientRect();
      world.table = {
        x: box.left - rect.left - TABLE_MARGIN,
        y: box.top - rect.top - TABLE_MARGIN,
        w: box.width + TABLE_MARGIN * 2,
        h: box.height + TABLE_MARGIN * 2,
      };
    }
    const visible = visibleLogos();
    const slots = phone
      ? phoneSlots(visible.length, world.width, world.height)
      : tableSlots(logos.length, world.width, world.height, world.table);
    bodies = bodies.filter((body) => visible.includes(body.el));
    visible.forEach((el, i) => {
      const radius = el.offsetWidth / 2;
      const slot = phone ? slots[i] : slots[logos.indexOf(el)];
      let body = findBody(el);
      if (!body) {
        body = { el, x: slot.x, y: slot.y, vx: 0, vy: 0, held: false, ph: i * PHASE_STEP };
        bodies.push(body);
      }
      body.r = radius;
      body.m = radius * radius;
      body.ax = slot.x;
      body.ay = slot.y;
    });
    draw();
  }

  cleanup.on(field, "pointerdown", (event) => {
    if (!ready) return;
    const el = event.target.closest(".pl");
    if (!el) return;
    event.preventDefault();
    const body = findBody(el);
    if (!body) return;
    const rect = field.getBoundingClientRect();
    drag = {
      body,
      offsetX: event.clientX - rect.left - body.x,
      offsetY: event.clientY - rect.top - body.y,
      startX: event.clientX,
      startY: event.clientY,
      history: [[performance.now(), event.clientX, event.clientY]],
      moved: 0,
    };
    body.held = true;
    body.vx = 0;
    body.vy = 0;
    el.classList.add("held");
    el.setPointerCapture(event.pointerId);
  });

  cleanup.on(field, "pointermove", (event) => {
    if (!drag) return;
    const rect = field.getBoundingClientRect();
    const { body } = drag;
    body.x = clamp(event.clientX - rect.left - drag.offsetX, body.r, world.width - body.r);
    body.y = clamp(
      event.clientY - rect.top - drag.offsetY,
      body.r,
      world.height - world.floor - body.r,
    );
    const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    drag.moved = Math.max(drag.moved, distance);
    drag.history.push([performance.now(), event.clientX, event.clientY]);
    if (drag.history.length > POINTER_HISTORY) drag.history.shift();
    if (reduce) draw();
  });

  const release = () => {
    if (!drag) return;
    const { body } = drag;
    const { vx, vy } = throwVelocity(drag.history, performance.now());
    body.vx = vx;
    body.vy = vy;
    body.held = false;
    body.el.classList.remove("held");
    lastDragDistance = drag.moved;
    drag = null;
    // with reduced motion nothing animates: snap back to the slot
    if (reduce) {
      body.x = body.ax;
      body.y = body.ay;
      draw();
    }
  };
  cleanup.on(field, "pointerup", release);
  cleanup.on(field, "pointercancel", release);
  // a logo is a link; dragging it must not follow the link
  cleanup.on(field, "click", (event) => {
    if (event.target.closest(".pl") && lastDragDistance >= CLICK_MAX_MOVE) event.preventDefault();
    lastDragDistance = 0;
  });

  const highlight = (index, on) => {
    const logo = logos.find((el) => el.dataset.i == index);
    const row = rows.find((el) => el.dataset.i == index);
    if (logo) logo.classList.toggle("hl", on);
    if (row) row.classList.toggle("hl", on);
  };
  for (const el of [...logos, ...rows]) {
    cleanup.on(el, "pointerenter", () => highlight(el.dataset.i, true));
    cleanup.on(el, "pointerleave", () => highlight(el.dataset.i, false));
  }

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(field);
  cleanup.add(() => resizeObserver.disconnect());
  cleanup.add(
    whileVisible(section, (now) => {
      const dt = Math.min(MAX_STEP_MS, now - (lastFrame || now)) || DEFAULT_STEP_MS;
      lastFrame = now;
      if (!ready || !world.width || isCovered(section)) return;
      if (!reduce || drag) stepBodies(bodies, dt, world);
      draw();
    }),
  );
  return () => cleanup.dispose();
}
