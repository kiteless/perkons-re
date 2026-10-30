/* Perkons Mod Matrix front end: loader intro, sine scroller, the three steps, memory meters.
 * Talks to tools/modmatrix.py on the same origin. Needs font.js (FONT, C64, drawText, wrap). */
"use strict";

const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const DPR = Math.max(1, Math.round(window.devicePixelRatio || 1));
const SCROLL_TEXT = "PERKONS MOD MATRIX   BROUGHT TO YOU BY KITELESS   BIG UP GIRTS AND EVERYONE AT ERICA     " +
  "SUPPORT INDEPENDENT SYNTH MANUFACTURERS     PERKONS STRIKES THE OAK AND THE DEVILS RUN       " +
  "KEEPING IT BROWN WATER IN 2026    SUP NOX!          ";
const PALETTE = Object.values(C64);
const $ = (id) => document.getElementById(id);

/* ---- pixel text: <p class="pix">TEXT</p> becomes a canvas (text kept for screen readers) ---- */

function pixInit(el) {
  if (el._cv) return;
  el.dataset.text = el.textContent.trim();
  el.textContent = "";
  const sr = document.createElement("span");
  sr.className = "sr";
  sr.textContent = el.dataset.text;
  const cv = document.createElement("canvas");
  cv.setAttribute("aria-hidden", "true");
  el.append(sr, cv);
  el._cv = cv;
  el._sr = sr;
}

function pixRender(el) {
  pixInit(el);
  const text = el.dataset.text || "";
  const s = Number(el.dataset.scale || 2);
  const cw = 8 * s;
  let lines;
  if (el.dataset.nowrap) {
    lines = [text];
  } else {
    const w = el.clientWidth || (el.parentElement && el.parentElement.clientWidth) || 640;
    lines = wrap(text, Math.max(1, Math.floor(w / cw)));
  }
  const cols = Math.max(1, ...lines.map((l) => l.length));
  const cv = el._cv;
  cv.width = cols * cw * DPR;
  cv.height = lines.length * cw * DPR;
  cv.style.width = cols * cw + "px";
  cv.style.height = lines.length * cw + "px";
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  const color = getComputedStyle(el).color;
  lines.forEach((line, i) => {
    const pad = el.dataset.align === "center" ? Math.floor((cols - line.length) / 2) : 0;
    drawText(ctx, line, pad * cw * DPR, i * cw * DPR, s * DPR, color);
  });
}

function setPix(el, text) {
  pixInit(el);
  el.dataset.text = text;
  el._sr.textContent = text;
  pixRender(el);
}

function pixAll() {
  document.querySelectorAll(".pix").forEach(pixRender);
}

function pix(tag, cls, text, extra) {
  const el = document.createElement(tag);
  el.className = "pix " + (cls || "");
  el.textContent = text;
  Object.assign(el.dataset, extra || {});
  return el;
}

/* ---- intro: the loader screen with flashing raster stripes in the border ---- */

function intro(done) {
  const box = $("intro");
  const cv = $("intro-canvas");
  const ctx = cv.getContext("2d");
  const lines = [
    "    **** PERKONS 64 MOD MATRIX V1 ****",
    " 64K RAM SYSTEM  38911 BASIC BYTES FREE",
    "",
    "READY.",
  ];
  const typed = 'LOAD"*",8,1';
  const T_TYPE = 0.5, T_SEARCH = 1.4, T_LOAD = 1.9, T_END = 4.2;
  let start = null, finished = false, lastStripes = 0, stripes = [];

  function finish() {
    if (finished) return;
    finished = true;
    box.remove();
    removeEventListener("keydown", finish);
    done();
  }
  box.addEventListener("click", finish);
  addEventListener("keydown", finish);

  function newStripes(h) {
    stripes = [];
    for (let y = 0; y < h;) {
      const sh = (2 + Math.floor(Math.random() * 10)) * DPR;
      stripes.push([y, sh, PALETTE[Math.floor(Math.random() * PALETTE.length)]]);
      y += sh;
    }
  }

  function frame(now) {
    if (finished) return;
    if (start === null) start = now;
    const t = (now - start) / 1000;
    const W = (cv.width = innerWidth * DPR), H = (cv.height = innerHeight * DPR);
    // the 320x200 screen at an integer scale, with a border around it
    const s = Math.max(1, Math.floor(Math.min(W / 384, H / 272)));
    const sw = 320 * s, sh = 200 * s, sx = Math.floor((W - sw) / 2), sy = Math.floor((H - sh) / 2);

    if (t >= T_LOAD && t < T_END - 0.3) {
      if (!REDUCED || now - lastStripes > 500) { newStripes(H); lastStripes = now; }
      for (const [y, h, c] of stripes) { ctx.fillStyle = c; ctx.fillRect(0, y, W, h); }
    } else {
      ctx.fillStyle = C64.lightblue;
      ctx.fillRect(0, 0, W, H);
    }
    ctx.fillStyle = C64.blue;
    ctx.fillRect(sx, sy, sw, sh);

    const out = lines.slice();
    if (t >= T_TYPE) out.push(typed.slice(0, Math.floor((t - T_TYPE) * 14)));
    if (t >= T_SEARCH) out.push("", "SEARCHING FOR *");
    if (t >= T_LOAD) out.push("LOADING");
    if (t >= T_END - 0.3) out.push("READY.", "RUN");
    out.forEach((l, i) => drawText(ctx, l, sx, sy + i * 8 * s, s, C64.lightblue));
    if (Math.floor(t * 2.5) % 2 === 0) {   // blinking cursor after the last line
      const last = out[out.length - 1];
      const row = last === "" || t < T_TYPE ? out.length : out.length - 1;
      const col = row === out.length ? 0 : last.length;
      ctx.fillStyle = C64.lightblue;
      ctx.fillRect(sx + col * 8 * s, sy + row * 8 * s, 8 * s, 8 * s);
    }
    if (t >= T_END) return finish();
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* ---- banner: copper bars and a sine ("snake") scroller ---- */

function scroller() {
  const cv = $("scroller");
  const ctx = cv.getContext("2d");
  const S = 4;                        // font pixel size
  const CW = 8 * S;
  const speed = REDUCED ? 40 : 150;   // px per second
  let x0 = null, last = null;

  function frame(now) {
    const W = cv.clientWidth, H = cv.clientHeight;
    if (cv.width !== W * DPR || cv.height !== H * DPR) { cv.width = W * DPR; cv.height = H * DPR; }
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    const t = now / 1000;
    if (last === null) { last = now; x0 = W; }
    x0 -= ((now - last) / 1000) * speed;
    last = now;
    const total = SCROLL_TEXT.length * CW;
    if (x0 < -total) x0 += total;

    ctx.fillStyle = C64.black;
    ctx.fillRect(0, 0, W, H);
    // copper bars: three bands of shaded stripes bobbing up and down
    const bars = [[C64.blue, C64.lightblue, C64.cyan, C64.white], [C64.red, C64.lightred, C64.orange, C64.yellow],
      [C64.green, C64.lightgreen, C64.yellow, C64.white]];
    bars.forEach((shades, b) => {
      const cy = H / 2 + Math.sin(t * 1.3 + b * 2.1) * (H / 2 - 14);
      for (let i = -3; i <= 3; i++) {
        ctx.fillStyle = shades[3 - Math.abs(i)];
        ctx.fillRect(0, Math.round(cy + i * 3), W, 3);
      }
    });
    // letters: each glyph column follows the sine, so words wriggle like a snake
    const amp = (H - CW) / 2 - 4;
    for (const offset of [0, total]) {
      for (let i = 0; i < SCROLL_TEXT.length; i++) {
        const gx = x0 + offset + i * CW;
        if (gx > W || gx < -CW) continue;
        const g = glyph(SCROLL_TEXT[i]);
        for (let c = 0; c < 8; c++) {
          const px = gx + c * S;
          const y = H / 2 - CW / 2 + Math.sin(px * 0.012 + t * 3) * amp;
          ctx.fillStyle = PALETTE[1 + (Math.floor(px / 24 + t * 10) % 15 + 15) % 15];
          for (let r = 0; r < 8; r++) {
            if (g[r] & (0x80 >> c)) ctx.fillRect(px, Math.round(y + r * S), S, S);
          }
        }
      }
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* ---- the three steps ---- */

const state = { status: null, options: [], image: null, info: null, chosen: new Set(), building: false,
  memory: null, hover: null };

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

function lock(id, locked) {
  const el = $(id);
  el.classList.toggle("locked", locked);
  el.setAttribute("aria-disabled", String(locked));
  el.querySelectorAll("input, button").forEach((i) => { if (locked) i.disabled = true; });
}

function say(el, cls, text) {
  el.className = "pix " + cls;
  setPix(el, text);
}

function usable(o) {
  return state.info && state.info.official && state.info.supported && (!o.target || o.target === state.info.version);
}

function clashes(o) {
  return o.conflicts.filter((c) => state.chosen.has(c));
}

/* ticking an option ticks what it requires; unticking one unticks what requires it */
function select(id) {
  if (state.chosen.has(id)) return;
  state.chosen.add(id);
  const o = state.options.find((x) => x.id === id);
  for (const r of (o && o.requires) || []) select(r);
}

function deselect(id) {
  if (!state.chosen.delete(id)) return;
  for (const o of state.options) if ((o.requires || []).includes(id)) deselect(o.id);
}

/* ---- memory: MAIN (M4 patch RAM), VOICE (M7), STORE (AXI SRAM); see tools/perkons/ram.py ---- */

const AREAS = ["main", "voice", "store"];

/* ids plus what they require, transitively (catalog.with_requires) */
function withRequires(ids) {
  const out = [];
  const add = (id) => {
    const o = state.options.find((x) => x.id === id);
    if (!o || out.includes(id)) return;
    out.push(id);
    (o.requires || []).forEach(add);
  };
  ids.forEach(add);
  return out;
}

/* bytes per area for these options together: owners shared between options count once */
function ramUsed(ids) {
  const m = state.memory, owners = {};
  for (const id of ids) {
    for (const [a, own] of Object.entries(m.options[id] || {})) Object.assign(owners[a] = owners[a] || {}, own);
  }
  return Object.fromEntries(AREAS.map((a) => [a, Object.values(owners[a] || {}).reduce((s, n) => s + n, 0)]));
}

/* the first area these options don't fit in, or null */
function overArea(ids) {
  if (!state.memory || state.memory.state !== "done") return null;
  const used = ramUsed(ids);
  return AREAS.find((a) => used[a] > state.memory.areas[a].size) || null;
}

function kb(n) {
  const k = n / 1024;
  return (k < 10 ? (Math.floor(k * 10) / 10).toFixed(1) : String(Math.floor(k))) + "K";
}

/* a meter is a column of ring characters, filled from the bottom (white: what the mod under
   the pointer would add) */
const RING = [60, 126, 231, 195, 231, 126, 60, 0];
const RING_S = 3, CELL = 8 * RING_S;

function drawMeter(cv, frac, extra) {
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * DPR;
  cv.height = H * DPR;
  const ctx = cv.getContext("2d");
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const n = Math.max(1, Math.floor(H / CELL)), x = Math.floor((W - CELL) / 2);
  const lit = Math.ceil(Math.min(1, frac) * n - 1e-9);
  const ghost = Math.ceil(Math.min(1, frac + extra) * n - 1e-9);
  for (let i = 0; i < n; i++) {
    const f = i / n;
    ctx.fillStyle = i < lit ? (f >= 0.85 ? C64.lightred : f >= 0.6 ? C64.yellow : C64.lightgreen)
      : i < ghost ? C64.white : C64.darkgrey;
    const y = H - (i + 1) * CELL;
    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        if (RING[r] & (0x80 >> c)) ctx.fillRect(x + c * RING_S, y + r * RING_S, RING_S, RING_S);
      }
    }
  }
}

function renderMem() {
  const m = state.memory, done = m && m.state === "done";
  const ids = withRequires([...state.chosen]);
  const used = done ? ramUsed(ids) : null;
  const hov = done && state.hover && !state.chosen.has(state.hover) ? ramUsed(withRequires([...ids, state.hover])) : null;
  for (const col of document.querySelectorAll("#mem .col")) {
    const a = col.dataset.area, cap = col.querySelector(".cap"), free = col.querySelector(".free");
    if (!done) {
      setPix(cap, "-");
      setPix(free, "-");
      drawMeter(col.querySelector(".meter"), 0, 0);
      continue;
    }
    const size = m.areas[a].size, left = size - used[a];
    setPix(cap, kb(size));
    free.className = "pix free" + (left < 0 ? " out" : left < size * 0.15 ? " low" : "");
    setPix(free, left < 0 ? "0K" : kb(left));
    drawMeter(col.querySelector(".meter"), used[a] / size, hov ? Math.max(0, hov[a] - used[a]) / size : 0);
  }
  const note = $("memnote");
  note.hidden = done;
  note.className = "pix " + (m && m.state === "error" ? "err" : "dim");
  if (!m) setPix(note, "LOAD FIRMWARE TO MEASURE.");
  else if (m.state === "error") {
    setPix(note, `?CAN'T MEASURE: ${m.error.toUpperCase()}. RESTART THE MOD MATRIX (AN OLD ONE MAY STILL BE RUNNING).`);
  } else if (!done) setPix(note, "MEASURING THE MODS...");
}

async function measure(image) {
  state.memory = { state: "measuring" };
  renderMem();
  for (;;) {
    let m;
    try { m = await api(`/api/memory/${image}`); } catch (e) { m = { state: "error", error: e.message }; }
    if (state.image !== image) return;             // another file loaded meanwhile
    if (m.state !== "measuring") { state.memory = m; break; }
    await new Promise((r) => setTimeout(r, 400));
  }
  renderMods();
  updatePatch();
}

function renderMods() {
  const ul = $("mods");
  ul.textContent = "";
  if (!state.options.length) {
    ul.append(pix("li", "dim", "NO MODS FOUND. SET PERKONS_MODS (SEE README)."));
  }
  for (const o of state.options) {
    const li = document.createElement("li");
    const over = state.chosen.has(o.id) ? null : overArea(withRequires([...state.chosen, o.id]));
    const merr = state.memory && state.memory.errors && state.memory.errors[o.id];
    const ok = usable(o) && !clashes(o).length && !over && !merr;
    li.classList.toggle("off", !ok);
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "sr";
    box.checked = state.chosen.has(o.id);
    box.disabled = !ok || state.building;
    box.addEventListener("change", () => {
      if (box.checked) select(o.id); else deselect(o.id);
      renderMods();
      updatePatch();
    });
    const row = document.createElement("div");
    row.className = "row";
    row.append(pix("p", "name", `[${box.checked ? "X" : " "}] ${o.title}`, { nowrap: "1" }),
      pix("p", "req", `REQUIRES ${o.target || "ANY FIRMWARE"}`, { nowrap: "1" }));
    const sum = pix("p", "sum", o.summary.toUpperCase());
    label.append(box, row, sum);
    if (state.info && o.target && o.target !== state.info.version) {
      label.append(pix("p", "err", `NOT AVAILABLE FOR ${state.info.version}`));
    }
    const cl = clashes(o);
    if (cl.length) label.append(pix("p", "err", `CAN'T BE COMBINED WITH ${cl.join(", ").toUpperCase()}`));
    if (over) label.append(pix("p", "err", `?OUT OF MEMORY ERROR IN ${over.toUpperCase()}`));
    if (merr) label.append(pix("p", "err", `?MEASURE ERROR: ${merr.toUpperCase().slice(0, 100)}`));
    li.append(label);
    li.addEventListener("mouseenter", () => { state.hover = o.id; renderMem(); });
    li.addEventListener("mouseleave", () => { state.hover = null; renderMem(); });
    box.addEventListener("focus", () => { state.hover = o.id; renderMem(); });
    box.addEventListener("blur", () => { state.hover = null; renderMem(); });
    ul.append(li);
  }
  ul.querySelectorAll(".pix").forEach(pixRender);
  renderMem();
}

function updatePatch() {
  const ready = state.info && state.info.official && state.info.supported && state.status && state.status.gcc;
  lock("s2", !ready);
  lock("s3", !ready);
  $("patch").disabled = !ready || !state.chosen.size || state.building;
  if (ready) renderMods();
  pixAll();
}

async function loadFile(file) {
  const fw = $("fw");
  state.info = null;
  state.image = null;
  state.chosen.clear();
  state.memory = null;
  $("dl").hidden = true;
  $("howto").hidden = true;
  $("log").textContent = "";
  say(fw, "dim", `READING ${file.name.toUpperCase()}...`);
  updatePatch();
  try {
    const info = await api("/api/inspect", { method: "POST", body: file });
    state.info = info;
    state.image = info.image;
    const id = `PERKONS ${info.version} (${info.git.toUpperCase()})`;
    if (!info.official) {
      say(fw, "err", `${id}: NOT AN OFFICIAL IMAGE WE KNOW (ALREADY MODDED?). LOAD THE ONE FROM ERICA SYNTHS.`);
    } else if (!info.supported) {
      say(fw, "err", `${id}: OFFICIAL, BUT NOT SUPPORTED YET. MODS NEED ${state.status.supported.join(" OR ")}.`);
    } else if (!state.status.gcc) {
      say(fw, "err", `${id}: OK, BUT ARM-NONE-EABI-GCC WAS NOT FOUND. INSTALL IT TO BUILD (SEE README).`);
    } else {
      say(fw, "ok", `FOUND ${id}. OFFICIAL IMAGE, CRC OK. READY TO MOD!`);
    }
    if (info.official && info.supported) measure(info.image);
  } catch (e) {
    say(fw, "err", `?FILE ERROR: ${e.message.toUpperCase()}`);
  }
  updatePatch();
}

function logLines(lines) {
  const box = $("log");
  const keep = lines.filter((l) => l.trim()).slice(-10);
  box.textContent = "";
  for (const l of keep) {
    const cls = l.startsWith("?") ? "err" : l === "READY." ? "ok" : "";
    const el = pix("p", cls, l.trim().toUpperCase().slice(0, 120));
    box.append(el);
    pixRender(el);
  }
}

async function build() {
  state.building = true;
  const btn = $("patch");
  btn.classList.add("busy");
  $("dl").hidden = true;
  $("howto").hidden = true;
  updatePatch();
  const all = [];
  try {
    const { job } = await api("/api/build", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: state.image, options: [...state.chosen], checks: true }),
    });
    all.push("PATCHING...");
    logLines(all);
    let since = 0, snap;
    for (;;) {
      await new Promise((r) => setTimeout(r, 400));
      snap = await api(`/api/job/${job}?since=${since}`);
      since = snap.next;
      all.push(...snap.log);
      logLines(all);
      if (snap.state !== "running") break;
    }
    if (snap.state === "done") {
      const a = $("dl");
      a.href = snap.download;
      a.download = snap.name;
      setPix(a.querySelector(".pix"), `DOWNLOAD ${snap.name.toUpperCase()}`);
      a.hidden = false;
      $("howto").hidden = false;
      pixRender($("howto"));
    }
  } catch (e) {
    all.push(`?BUILD ERROR: ${e.message}`);
    logLines(all);
  }
  state.building = false;
  btn.classList.remove("busy");
  updatePatch();
}

async function main() {
  $("app").hidden = false;
  pixAll();
  scroller();
  try {
    state.status = await api("/api/status");
    state.options = (await api("/api/mods")).options;
  } catch (e) {
    say($("fw"), "err", `?CAN'T REACH THE MOD MATRIX SERVER: ${e.message.toUpperCase()}`);
  }
  renderMods();
  updatePatch();

  const input = $("file"), drop = $("drop");
  input.addEventListener("change", () => input.files[0] && loadFile(input.files[0]));
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); pixAll(); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); pixAll(); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && loadFile(e.dataTransfer.files[0]));
  $("patch").addEventListener("click", build);
  // hover/focus colours change the text colour, which the canvases have to redraw for
  for (const el of document.querySelectorAll(".drop, .patch, .dl")) {
    for (const ev of ["mouseenter", "mouseleave", "focus", "blur"]) {
      el.addEventListener(ev, () => requestAnimationFrame(() => el.querySelectorAll(".pix").forEach(pixRender)));
    }
  }
  if (window.ResizeObserver) new ResizeObserver(() => renderMem()).observe($("screen"));
  let rt;
  addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { pixAll(); renderMem(); }, 100); });
}

(async () => {
  let skip = new URLSearchParams(location.search).has("nointro");
  try { skip = skip || (await (await fetch("/api/status")).json()).intro === false; } catch (e) { /* offline */ }
  if (skip) { $("intro").remove(); main(); } else intro(main);
})();
