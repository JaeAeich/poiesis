// Shared helpers for the Poiesis theme. Browser-only code runs inside mount functions (onMounted).
export const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const lerp = (a, b, t) => a + (b - a) * t;
export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const ease = t => (t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
export const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
export const reducedMotion = () => typeof window !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// Collects teardown work so a component can undo everything on unmount.
export function bag() {
  const fns = [];
  const b = {
    add(fn) { fns.push(fn); return fn; },
    on(target, ev, fn, opts) { target.addEventListener(ev, fn, opts); fns.push(() => target.removeEventListener(ev, fn, opts)); },
    timeout(fn, ms) { const id = setTimeout(fn, ms); fns.push(() => clearTimeout(id)); return id; },
    dispose() { while (fns.length) { try { fns.pop()(); } catch (e) { /* ignore */ } } },
  };
  return b;
}

// Run fn every animation frame while el is on screen. Returns a stop function.
export function whileVisible(el, fn) {
  let on = false, id = 0, dead = false;
  const loop = t => { if (dead) return; fn(t); if (on) id = requestAnimationFrame(loop); };
  const io = new IntersectionObserver(es => {
    const v = es[0].isIntersecting;
    if (v && !on) { on = true; id = requestAnimationFrame(loop); } else if (!v) { on = false; cancelAnimationFrame(id); }
  });
  io.observe(el);
  return () => { dead = true; on = false; cancelAnimationFrame(id); io.disconnect(); };
}

// Call fn whenever VitePress toggles dark mode (html.dark). Returns a stop function.
export function onThemeChange(fn) {
  const mo = new MutationObserver(() => fn());
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => mo.disconnect();
}

/* The logo as SVG, so it can turn. Geometry traced from logo.png (512 px). */
export function logoParts() {
  const c = 256, B = "#1f6aae", C = "#f0684c";
  const P = (r, a) => [c + Math.cos(a * Math.PI / 180) * r, c + Math.sin(a * Math.PI / 180) * r];
  let handles = ""; for (let i = 0; i < 8; i++) handles += `<path transform="translate(256 256) rotate(${i * 45})" d="M-18 -136Q-7.5 -146 -7.5 -164L-9 -195A9 9 0 0 1 9 -195L7.5 -164Q7.5 -146 18 -136Z" fill="${B}"/>`;
  const ring = `<circle cx="256" cy="256" r="140" fill="none" stroke="${B}" stroke-width="24"/><circle class="halo" cx="256" cy="256" r="125" fill="none" stroke-width="6"/>`;
  const hx = [-90, -30, 30, 90, 150, 210].map(a => P(122, a));
  const hex = `<polygon points="${hx.map(p => p.join(",")).join(" ")}" fill="none" stroke="${B}" stroke-width="5.5" stroke-linejoin="round"/>`;
  const chain = [...Array(10)].map((_, i) => P(90 - i * 1.2, -90 + i * 36));
  const inner = `<line x1="${hx[0][0]}" y1="${hx[0][1]}" x2="${chain[0][0]}" y2="${chain[0][1]}" stroke="${B}" stroke-width="4"/><line x1="${hx[3][0]}" y1="${hx[3][1]}" x2="${P(85, 90)[0]}" y2="${P(85, 90)[1]}" stroke="${B}" stroke-width="4"/><polyline points="${chain.map(p => p.join(",")).join(" ")}" fill="none" stroke="${B}" stroke-width="5" stroke-linejoin="round"/>` + chain.map(p => `<circle class="halo" cx="${p[0]}" cy="${p[1]}" r="8.5" fill="${B}" stroke-width="2.5"/>`).join("");
  const nodes = hx.map((p, i) => `<circle class="halo hn" cx="${p[0]}" cy="${p[1]}" r="${i % 3 === 0 ? 14 : 12}" fill="${C}" stroke-width="4"/>`).join("");
  let d = ""; for (let t = 0; t <= 5.6 * Math.PI; t += .05) { const r = 3 + t * 3.05, ph = Math.PI - .84; d += (d ? "L" : "M") + (c + Math.cos(t + ph) * r).toFixed(1) + " " + (c + Math.sin(t + ph) * r).toFixed(1); }
  const spiral = `<path class="sp" d="${d}" fill="none" stroke="${C}" stroke-width="10" stroke-linecap="round"/>`;
  return { handles, ring, hex, inner, nodes, spiral };
}
