/* Perkons Mod Matrix front end: loader intro, sine scroller, the three steps, equaliser.
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

/* ---- equaliser: random bars for now (a module player can drive levels later) ---- */

const EQ = { levels: null, source: null };   // EQ.source = () => [0..1, ...] to drive it

function equaliser() {
  const cv = $("eq");
  const ctx = cv.getContext("2d");
  const BW = 20, GAP = 4, SEG = 8;
  let vals = [], peaks = [], targets = [], last = null;

  function frame(now) {
    const W = cv.clientWidth, H = cv.clientHeight;
    if (cv.width !== W * DPR || cv.height !== H * DPR) { cv.width = W * DPR; cv.height = H * DPR; }
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    const n = Math.max(4, Math.floor((W - GAP) / (BW + GAP)));
    while (vals.length < n) { vals.push(0); peaks.push(0); targets.push(0); }
    const dt = last === null ? 0 : Math.min(0.1, (now - last) / 1000);
    last = now;
    const src = EQ.source ? EQ.source(n) : null;
    for (let i = 0; i < n; i++) {
      if (src) targets[i] = src[i] || 0;
      else if (Math.random() < dt * (REDUCED ? 2 : 9)) targets[i] = Math.pow(Math.random(), 1.4);
      vals[i] += (targets[i] - vals[i]) * Math.min(1, dt * (REDUCED ? 4 : 18));
      targets[i] *= 1 - dt * 1.5;
      peaks[i] = Math.max(peaks[i] - dt * 0.5, vals[i]);
    }
    ctx.fillStyle = C64.black;
    ctx.fillRect(0, 0, W, H);
    const x0 = Math.floor((W - n * (BW + GAP) + GAP) / 2);
    const segs = Math.floor((H - 8) / SEG);
    for (let i = 0; i < n; i++) {
      const x = x0 + i * (BW + GAP);
      const lit = Math.round(vals[i] * segs);
      for (let s = 0; s < lit; s++) {
        const f = s / segs;
        ctx.fillStyle = f > 0.8 ? C64.lightred : f > 0.6 ? C64.yellow : f > 0.35 ? C64.lightgreen : C64.green;
        ctx.fillRect(x, H - 4 - (s + 1) * SEG + 2, BW, SEG - 2);
      }
      ctx.fillStyle = C64.white;
      ctx.fillRect(x, H - 4 - Math.round(peaks[i] * segs) * SEG - 2, BW, 2);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* ---- the three steps ---- */

const state = { status: null, options: [], image: null, info: null, chosen: new Set(), building: false };

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

function renderMods() {
  const ul = $("mods");
  ul.textContent = "";
  if (!state.options.length) {
    ul.append(pix("li", "dim", "NO MODS FOUND. SET PERKONS_MODS (SEE README)."));
  }
  for (const o of state.options) {
    const li = document.createElement("li");
    const ok = usable(o) && !clashes(o).length;
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
      updateSlop();
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
    li.append(label);
    ul.append(li);
  }
  ul.querySelectorAll(".pix").forEach(pixRender);
}

function updateSlop() {
  const ready = state.info && state.info.official && state.info.supported && state.status && state.status.gcc;
  lock("s2", !ready);
  lock("s3", !ready);
  $("slop").disabled = !ready || !state.chosen.size || state.building;
  if (ready) renderMods();
  pixAll();
}

async function loadFile(file) {
  const fw = $("fw");
  state.info = null;
  state.image = null;
  state.chosen.clear();
  $("dl").hidden = true;
  $("howto").hidden = true;
  $("log").textContent = "";
  say(fw, "dim", `READING ${file.name.toUpperCase()}...`);
  updateSlop();
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
  } catch (e) {
    say(fw, "err", `?FILE ERROR: ${e.message.toUpperCase()}`);
  }
  updateSlop();
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
  const btn = $("slop");
  btn.classList.add("busy");
  $("dl").hidden = true;
  $("howto").hidden = true;
  updateSlop();
  const all = [];
  try {
    const { job } = await api("/api/build", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: state.image, options: [...state.chosen], checks: true }),
    });
    all.push("SLOPPING...");
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
  updateSlop();
}

async function main() {
  $("app").hidden = false;
  pixAll();
  scroller();
  equaliser();
  try {
    state.status = await api("/api/status");
    state.options = (await api("/api/mods")).options;
  } catch (e) {
    say($("fw"), "err", `?CAN'T REACH THE MOD MATRIX SERVER: ${e.message.toUpperCase()}`);
  }
  renderMods();
  updateSlop();

  const input = $("file"), drop = $("drop");
  input.addEventListener("change", () => input.files[0] && loadFile(input.files[0]));
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); pixAll(); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); pixAll(); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && loadFile(e.dataTransfer.files[0]));
  $("slop").addEventListener("click", build);
  // hover/focus colours change the text colour, which the canvases have to redraw for
  for (const el of document.querySelectorAll(".drop, .slop, .dl")) {
    for (const ev of ["mouseenter", "mouseleave", "focus", "blur"]) {
      el.addEventListener(ev, () => requestAnimationFrame(() => el.querySelectorAll(".pix").forEach(pixRender)));
    }
  }
  let rt;
  addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(pixAll, 100); });
}

(async () => {
  let skip = new URLSearchParams(location.search).has("nointro");
  try { skip = skip || (await (await fetch("/api/status")).json()).intro === false; } catch (e) { /* offline */ }
  if (skip) { $("intro").remove(); main(); } else intro(main);
})();
