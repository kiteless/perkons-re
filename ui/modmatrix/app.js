/* Perkons Mod Matrix front end: the start screen (loads the firmware), sine scroller, the mods
 * and engines, memory meters.
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
  if (!el.getClientRects().length) return;      // not shown (another screen or tab): drawn when it is
  pixInit(el);
  const text = el.dataset.text || "";
  const s = Number(el.dataset.scale || 2);
  const cw = 8 * s;
  let lines;
  if (el.dataset.nowrap) {
    lines = [text];
  } else {
    const w = el.clientWidth || (el.parentElement && el.parentElement.clientWidth) || 640;
    const cols = Math.max(1, Math.floor(w / cw));
    lines = wrap(text, cols);
    if (el.dataset.oneline && lines.length > 1) lines = [lines[0].slice(0, Math.max(0, cols - 3)) + "..."];
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

/* ---- intro: the start screen. READY. and the dashed drop box for the firmware; once it's
 * dropped or chosen, LOAD"<its name>",8,1 is typed at the cursor, with raster stripes in the border while
 * the server inspects it. A good image RUNs the Mod Matrix with it loaded (done(info)); a
 * bad one gets an error and the prompt again. Click or a key skips the animation; quick
 * (--no-intro) skips it always. ---- */

function intro(status, done, quick) {
  const box = $("intro");
  const cv = $("intro-canvas");
  const ctx = cv.getContext("2d");
  const COLS = 40, ROWS = 25;
  const DROP = wrap("DROP YOUR OFFICIAL PERKONS .IMG HERE OR CLICK TO BROWSE", COLS - 4);
  const BOX_ROWS = DROP.length + 2;                  // a blank row above and below the text
  const scr = [];
  let phase = "wait", typing = null, loading = false, finished = false, fast = false, skip = null;
  let lastStripes = 0, stripes = [], hot = false, dropBox = null;   // dropBox: [x, y, w, h], CSS px

  // print: word-wrapped like a message; hard: cut at the 40th column, as typed lines are
  const print = (text, hard) => {
    const lines = hard ? (text.match(/.{1,40}/g) || [""]) : text.length <= COLS ? [text] : wrap(text, COLS);
    scr.push(...lines);
    scr.splice(0, Math.max(0, scr.length - ROWS));
  };
  ["    **** PERKONS 64 MOD MATRIX V1 ****", " 64K RAM SYSTEM  38911 BASIC BYTES FREE", "", "READY."].forEach((l) => print(l));
  if (status && status.stale) {
    print("?OUT OF DATE ERROR");
    print("THE MOD MATRIX WAS UPDATED SINCE IT STARTED. STOP IT (CTRL-C) AND START IT AGAIN.");
    phase = "dead";
  }

  const picker = document.createElement("input");
  picker.type = "file";
  picker.accept = ".img";
  picker.className = "sr";
  box.append(picker);
  picker.addEventListener("change", () => picker.files[0] && load(picker.files[0]));

  const sleep = (sec) => new Promise((r) => {
    const t = setTimeout(r, fast ? 0 : sec * 1000);
    skip = () => { clearTimeout(t); r(); };
  });
  async function type(text) {
    for (let n = 1; n <= text.length; n++) { typing = text.slice(0, n); await sleep(1 / 24); }
    typing = null;
    print(text, true);
  }
  function problem(r) {
    if (r.error) return ["?FILE ERROR", r.error.message.toUpperCase()];
    const id = `PERKONS ${r.info.version} (${r.info.git.toUpperCase()})`;
    if (!r.info.official) return ["?NOT OFFICIAL ERROR", `${id} IS NOT AN OFFICIAL IMAGE WE KNOW (ALREADY MODDED?). LOAD THE ONE FROM ERICA SYNTHS.`];
    if (!r.info.supported) return ["?VERSION ERROR", `${id} IS OFFICIAL, BUT NOT SUPPORTED YET.`];
    return null;
  }

  async function load(file) {
    if (phase !== "wait") return;
    phase = "load";
    fast = !!quick;
    const name = file.name.toUpperCase();
    const result = api("/api/inspect", { method: "POST", body: file }).then((info) => ({ info }), (error) => ({ error }));
    await sleep(0.4);
    await type(`LOAD"${name}",8,1`);
    await sleep(0.4);
    print("");
    print(`SEARCHING FOR ${name}`, true);
    await sleep(0.6);
    print("LOADING");
    loading = true;
    const [r] = await Promise.all([result, sleep(2.2)]);
    loading = false;
    const err = problem(r);
    if (!err) {
      print("READY.");
      await type("RUN");
      await sleep(0.3);
      return finish(r.info);
    }
    err.forEach((l) => print(l));
    print("");
    print("READY.");
    picker.value = "";
    phase = "wait";
  }

  function onKey(e) {
    if (phase === "wait" && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); picker.click(); }
    else if (phase === "load") { fast = true; if (skip) skip(); }
  }
  const inBox = (e) => dropBox && e.clientX >= dropBox[0] && e.clientX < dropBox[0] + dropBox[2] &&
    e.clientY >= dropBox[1] && e.clientY < dropBox[1] + dropBox[3];
  box.addEventListener("click", (e) => {
    if (phase === "wait" && inBox(e)) picker.click();
    else if (phase === "load") { fast = true; if (skip) skip(); }
  });
  box.addEventListener("mousemove", (e) => {
    hot = phase === "wait" && inBox(e);
    box.style.cursor = hot || phase === "load" ? "pointer" : "default";
  });
  box.addEventListener("mouseleave", () => { hot = false; });
  addEventListener("keydown", onKey);
  ["dragenter", "dragover"].forEach((ev) => box.addEventListener(ev, (e) => { e.preventDefault(); hot = phase === "wait"; }));
  box.addEventListener("dragleave", () => { hot = false; });
  box.addEventListener("drop", (e) => {
    e.preventDefault();
    hot = false;
    if (e.dataTransfer.files[0]) load(e.dataTransfer.files[0]);
  });

  function finish(info) {
    if (finished) return;
    finished = true;
    box.remove();
    removeEventListener("keydown", onKey);
    done(info);
  }

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
    const W = (cv.width = innerWidth * DPR), H = (cv.height = innerHeight * DPR);
    // the 320x200 screen at an integer scale, framed as the page's screen is: padding and a
    // light-blue border b wide, on black
    const b = (innerWidth <= 600 ? 12 : 24) * DPR;
    const s = Math.max(1, Math.floor(Math.min((W - 6 * b) / 320, (H - 6 * b) / 200)));
    const sw = 320 * s, sh = 200 * s, sx = Math.floor((W - sw) / 2), sy = Math.floor((H - sh) / 2);
    const fx = sx - 2 * b, fy = sy - 2 * b, fw = sw + 4 * b, fh = sh + 4 * b;

    ctx.fillStyle = C64.black;
    ctx.fillRect(0, 0, W, H);
    if (loading) {                                   // raster stripes in the border
      if (!REDUCED || now - lastStripes > 500) { newStripes(H); lastStripes = now; }
      ctx.save();
      ctx.beginPath();
      ctx.rect(fx, fy, fw, fh);
      ctx.clip();
      for (const [y, h, c] of stripes) { ctx.fillStyle = c; ctx.fillRect(0, y, W, h); }
      ctx.restore();
    } else {
      ctx.fillStyle = C64.lightblue;
      ctx.fillRect(fx, fy, fw, fh);
    }
    ctx.fillStyle = C64.blue;
    ctx.fillRect(sx - b, sy - b, sw + 2 * b, sh + 2 * b);

    const out = scr.slice();
    if (typing !== null) out.push(...(typing.match(/.{1,40}/g) || [""]));
    // waiting: the cursor's row, then the drop box (the step 1 box of the page, on the 64)
    const rows = out.slice(-(phase === "wait" ? ROWS - 1 - BOX_ROWS : ROWS));
    rows.forEach((l, i) => drawText(ctx, l, sx, sy + i * 8 * s, s, C64.lightblue));
    dropBox = null;
    if (phase === "wait") {
      const p = 8 * s, bx = sx, by = sy + (rows.length + 1) * p, bw = sw, bh = BOX_ROWS * p;
      if (hot) { ctx.fillStyle = C64.lightblue; ctx.fillRect(bx, by, bw, bh); }
      dashedRect(ctx, bx, by, bw, bh, s, C64.lightblue);
      DROP.forEach((l, i) => drawText(ctx, l, bx + 2 * p, by + (i + 1) * p, s, hot ? C64.blue : C64.lightblue));
      dropBox = [bx / DPR, by / DPR, bw / DPR, bh / DPR];
    }
    if (!loading && phase !== "dead" && Math.floor(now / 400) % 2 === 0) {   // blinking cursor
      const typed = typing !== null;
      const row = typed ? rows.length - 1 : Math.min(rows.length, ROWS - 1);
      const col = typed ? rows[rows.length - 1].length : 0;
      ctx.fillStyle = C64.lightblue;
      ctx.fillRect(sx + col * 8 * s, sy + row * 8 * s, 8 * s, 8 * s);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  box.focus();
}

/* a dashed outline 2 pixels thick, dashes 4 on 4 (s: screen pixel size) */
function dashedRect(ctx, x, y, w, h, s, color) {
  const t = 2 * s, d = 4 * s;
  ctx.fillStyle = color;
  for (let i = 0; i < w; i += 2 * d) {
    ctx.fillRect(x + i, y, Math.min(d, w - i), t);
    ctx.fillRect(x + i, y + h - t, Math.min(d, w - i), t);
  }
  for (let i = 0; i < h; i += 2 * d) {
    ctx.fillRect(x, y + i, t, Math.min(d, h - i));
    ctx.fillRect(x + w - t, y + i, t, Math.min(d, h - i));
  }
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
  memory: null, hover: null, voices: [], tab: "mods", repos: [], ticked: new Set(), repoError: null };

const FIRST_VOICE_SLOT = 5, MAX_VOICES = 12;     // slots 1-4: the official voices
const isVoice = (o) => o.kind === "voice";
/* what the voices require (voice-map) sits on the ENGINES tab as its on/off switch */
const isEngineHost = (o) => state.options.some((v) => isVoice(v) && (v.requires || []).includes(o.id));

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
  el.querySelectorAll(".tab").forEach((t) => { t.disabled = locked; });   // tabs aren't re-rendered
}

function say(el, cls, text) {
  el.className = "pix " + cls;
  setPix(el, text);
}

function usable(o) {
  return state.info && state.info.official && state.info.supported && (!o.target || o.target === state.info.version);
}

/* what an option requires (transitively) that the ticked repos don't offer */
function unoffered(o) {
  const out = [], seen = new Set();
  const walk = (id) => {
    if (seen.has(id)) return;
    seen.add(id);
    const x = state.options.find((y) => y.id === id);
    if (!x) { out.push(id); return; }
    (x.requires || []).forEach(walk);
  };
  walk(o.id);
  return out;
}

const repoOf = (id) => id.includes(":") ? id.split(":")[0] : id;

/* FROM <its repo>, and its README beside it */
function fromLine(o) {
  if (!o.repo && !o.readme) return null;
  const div = document.createElement("div");
  div.className = "from";
  if (o.repo) div.append(pix("p", "by", `FROM ${o.repo.toUpperCase()}`, { nowrap: "1" }));
  if (o.readme) div.append(infoLink(o));
  return div;
}

/* the mod's page (its README on GitHub), in a new tab */
function infoLink(o) {
  const a = document.createElement("a");
  a.className = "info";
  a.href = o.readme;
  a.target = "_blank";
  a.rel = "noopener";
  a.append(pix("span", "", "README", { nowrap: "1" }));
  for (const ev of ["mouseenter", "mouseleave", "focus", "blur"]) {
    a.addEventListener(ev, () => requestAnimationFrame(() => a.querySelectorAll(".pix").forEach(pixRender)));
  }
  return a;
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
  for (const o of state.options) {
    if (!(o.requires || []).includes(id)) continue;
    if (isVoice(o)) state.voices = state.voices.filter((v) => v !== o.id);
    else deselect(o.id);
  }
}

/* voices need what they require (voice-map) ticked first; everything is staged until PATCH IT */
const voiceReady = (o) => (o.requires || []).every((r) => state.chosen.has(r));

function install(id) {
  if (state.voices.includes(id) || state.voices.length >= MAX_VOICES) return;
  state.voices.push(id);
}

function uninstall(id) {
  state.voices = state.voices.filter((v) => v !== id);
}

/* everything the build would take: ticked mods and installed voices */
const picked = () => [...state.chosen, ...state.voices];

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

/* the stock ranges taken over by these options: {area: Set of range names} */
function ramTaken(ids) {
  const out = {};
  for (const id of ids) {
    for (const [a, t] of Object.entries((state.memory.takeovers || {})[id] || {})) {
      for (const name of Object.keys(t)) (out[a] = out[a] || new Set()).add(name);
    }
  }
  return out;
}

/* a meter is a column of ring characters: the whole physical RAM block, its lowest address
   at the bottom. Grey: the firmware's own ranges; green: the mods' part as far as these
   options use it, and stock ranges a mod has taken over; white: what the option under the
   pointer would add; dark: free for mods. Red / yellow green when the mods' part is (nearly)
   full. */
const RING = [60, 126, 231, 195, 231, 126, 60, 0];
const RING_S = 3, CELL = 8 * RING_S;

function drawMeter(cv, area, used, extra, taken, ghostTaken) {
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * DPR;
  cv.height = H * DPR;
  const ctx = cv.getContext("2d");
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const n = Math.max(1, Math.floor(H / CELL)), x = Math.floor((W - CELL) / 2);
  const block = area && area.block;
  const full = area ? used / area.size : 0;
  const lit = full >= 0.85 ? C64.lightred : full >= 0.6 ? C64.yellow : C64.lightgreen;
  for (let i = 0; i < n; i++) {
    let color = C64.darkgrey;
    if (block) {
      const mid = block.start + (i + 0.5) / n * block.size;        // the address this ring stands for
      const r = block.ranges.find((g) => mid >= g.start && mid < g.start + g.size) || block.ranges[0];
      if (r.owner === "mods") {
        const at = mid - r.start;
        color = at < used ? lit : at < used + extra ? C64.white : C64.darkgrey;
      } else {
        color = taken.has(r.owner) ? C64.lightgreen : ghostTaken.has(r.owner) ? C64.white : C64.grey;
      }
    }
    ctx.fillStyle = color;
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
  const ids = withRequires(picked());
  const used = done ? ramUsed(ids) : null;
  const hov = done && state.hover && !ids.includes(state.hover) ? ramUsed(withRequires([...ids, state.hover])) : null;
  for (const col of document.querySelectorAll("#mem .col")) {
    const a = col.dataset.area, cap = col.querySelector(".cap"), free = col.querySelector(".free");
    if (!done) {
      setPix(cap, "-");
      setPix(free, "-");
      drawMeter(col.querySelector(".meter"), null, 0, 0, new Set(), new Set());
      continue;
    }
    const size = m.areas[a].size, left = size - used[a];
    setPix(cap, kb(m.areas[a].block.size));
    free.className = "pix free" + (left < 0 ? " out" : left < size * 0.15 ? " low" : "");
    setPix(free, left < 0 ? "0K" : kb(left));
    const taken = (ramTaken(ids)[a]) || new Set();
    const ghost = hov ? (ramTaken(withRequires([...ids, state.hover]))[a] || new Set()) : new Set();
    drawMeter(col.querySelector(".meter"), m.areas[a], used[a], hov ? Math.max(0, hov[a] - used[a]) : 0,
      taken, new Set([...ghost].filter((g) => !taken.has(g))));
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

/* ---- the screens: the repos, then the mods; the browser's back and forward move between
 * them (history states) ---- */

function showScreen(name) {
  document.body.dataset.screen = name;
  history.scrollRestoration = "manual";
  scrollTo(0, 0);
  updatePatch();
  renderMem();
}

/* ---- step 1: the mod repos (tools/perkons/repos.py). The ticked ones are kept in this
 * browser; until the user changes them, the config's "default" ones ---- */

const TICKED_KEY = "modmatrix.repos";

function savedTicks() {
  try { return JSON.parse(localStorage.getItem(TICKED_KEY)); } catch (e) { return null; }
}

function saveTicks() {
  try { localStorage.setItem(TICKED_KEY, JSON.stringify([...state.ticked])); } catch (e) { /* private mode */ }
}

async function loadRepos() {
  const r = await api("/api/repos");
  state.repos = r.repos;
  state.repoError = r.error;
  const saved = savedTicks();
  const names = new Set(state.repos.filter((x) => !x.error).map((x) => x.repo));
  state.ticked = new Set(Array.isArray(saved) ? saved.filter((n) => names.has(n))
    : state.repos.filter((x) => x.default && !x.error).map((x) => x.repo));
  renderRepos();
}

function renderRepos() {
  const ul = $("repos");
  ul.textContent = "";
  if (state.repoError) ul.append(pix("li", "err", `?CAN'T GET THE REPO LIST: ${state.repoError.toUpperCase().slice(0, 120)}`));
  for (const r of state.repos) {
    const li = document.createElement("li");
    li.classList.toggle("off", Boolean(r.error));
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "sr";
    box.checked = state.ticked.has(r.repo);
    box.disabled = Boolean(r.error) || state.building;
    box.addEventListener("change", () => {
      if (box.checked) state.ticked.add(r.repo); else state.ticked.delete(r.repo);
      saveTicks();
      renderRepos();
      setContinue();
      loadMods();
    });
    const row = document.createElement("div");
    row.className = "row";
    row.append(pix("p", "name", `[${box.checked ? "X" : " "}] ${r.repo.toUpperCase()}`, { nowrap: "1" }),
      pix("p", "req", r.error ? "UNAVAILABLE" : `${r.mods} MOD${r.mods === 1 ? "" : "S"}`, { nowrap: "1" }));
    label.append(box, row);
    if (r.note) label.append(pix("p", "note", r.note.toUpperCase()));
    label.append(pix("p", "by", `BY ${r.author.toUpperCase()}${r.local ? " (ON THIS COMPUTER)" : ""}`, { nowrap: "1" }));
    if (r.error) label.append(pix("p", "err", `?${r.error.toUpperCase().slice(0, 120)}`));
    li.append(label);
    ul.append(li);
  }
  if (!state.repos.length && !state.repoError) ul.append(pix("li", "dim", "NO REPOS CONFIGURED."));
  ul.querySelectorAll(".pix").forEach(pixRender);
}

/* the repos can be ticked again (lock() disabled them) */
function unlockRepos() {
  for (const li of $("repos").querySelectorAll("li")) {
    const box = li.querySelector("input");
    if (box) box.disabled = li.classList.contains("off");
  }
  setContinue();
}

/* CONTINUE needs a ticked repo */
function setContinue() {
  const b = $("repos-ok");
  b.disabled = !state.ticked.size;
  b.querySelectorAll(".pix").forEach(pixRender);   // its text colour follows
}

/* the options of the ticked repos; what was chosen from a repo no longer ticked goes */
async function loadMods() {
  const q = [...state.ticked].map(encodeURIComponent).join(",");
  state.options = (await api(`/api/mods?repos=${q}`)).options;
  const offered = new Set(state.options.map((o) => o.id));
  for (const id of [...state.chosen]) if (!offered.has(id)) deselect(id);
  state.voices = state.voices.filter((id) => offered.has(id));
  renderMods();
  updatePatch();
}

function renderMods() {
  const ul = $("mods");
  ul.textContent = "";
  if (!state.options.length) {
    ul.append(pix("li", "dim", state.ticked.size ? "NO MODS IN THE TICKED REPOS." : "GO BACK AND TICK A REPO."));
  }
  for (const o of state.options.filter((x) => !isVoice(x) && !isEngineHost(x))) ul.append(optionItem(o, o.title));
  ul.querySelectorAll(".pix").forEach(pixRender);
  renderVoices();
  renderMem();
}

/* a tickable option: [X] TITLE, what it needs, its summary, why it can't be ticked (the
 * descriptions stay in the manifests, not shown for now) */
function optionItem(o, title) {
  const li = document.createElement("li");
  const over = state.chosen.has(o.id) ? null : overArea(withRequires([...picked(), o.id]));
  const merr = state.memory && state.memory.errors && state.memory.errors[o.id];
  const ok = usable(o) && !clashes(o).length && !over && !merr && !unoffered(o).length;
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
  row.append(pix("p", "name", `[${box.checked ? "X" : " "}] ${title}`, { nowrap: "1" }),
    pix("p", "req", `REQUIRES ${o.target || "ANY FIRMWARE"}`, { nowrap: "1" }));
  const sum = pix("p", "sum", o.summary.toUpperCase());
  label.append(box, row, sum);
  const gone = unoffered(o);
  if (gone.length) label.append(pix("p", "err", `NEEDS ${gone.map(repoOf).join(", ").toUpperCase()}: GO BACK AND TICK IT`));
  if (state.info && o.target && o.target !== state.info.version) {
    label.append(pix("p", "err", `NOT AVAILABLE FOR ${state.info.version}`));
  }
  const cl = clashes(o);
  if (cl.length) label.append(pix("p", "err", `CAN'T BE COMBINED WITH ${cl.join(", ").toUpperCase()}`));
  if (over) label.append(pix("p", "err", `?OUT OF MEMORY ERROR IN ${over.toUpperCase()}`));
  if (merr) label.append(pix("p", "err", `?MEASURE ERROR: ${merr.toUpperCase().slice(0, 100)}`));
  li.append(label);
  const from = fromLine(o);
  if (from) li.append(from);
  li.addEventListener("mouseenter", () => { state.hover = o.id; renderMem(); });
  li.addEventListener("mouseleave", () => { state.hover = null; renderMem(); });
  box.addEventListener("focus", () => { state.hover = o.id; renderMem(); });
  box.addEventListener("blur", () => { state.hover = null; renderMem(); });
  return li;
}

function voiceButton(o, label, onClick, ok, note) {
  const li = document.createElement("li");
  const b = document.createElement("button");
  b.className = "voice";
  b.disabled = !ok || state.building;
  b.append(pix("span", "name", label, { nowrap: "1" }), pix("p", "sum", o.summary.toUpperCase()));
  if (note) b.append(pix("p", "err", note));
  b.addEventListener("click", () => { onClick(); renderMods(); updatePatch(); });
  for (const ev of ["mouseenter", "focus"]) b.addEventListener(ev, () => { state.hover = o.id; renderMem(); });
  for (const ev of ["mouseleave", "blur"]) b.addEventListener(ev, () => { state.hover = null; renderMem(); });
  li.append(b);
  const from = fromLine(o);
  if (from) li.append(from);
  return li;
}

/* ENGINES: [ ] ENABLE CUSTOM VOICE ENGINES, then INSTALLED in slot order from 5 and AVAILABLE
 * to its right; clicking moves a voice */
function renderVoices() {
  const host = $("enginehost"), inst = $("installed"), avail = $("available");
  host.textContent = "";
  inst.textContent = "";
  avail.textContent = "";
  for (const o of state.options.filter(isEngineHost)) host.append(optionItem(o, "ENABLE CUSTOM VOICE ENGINES"));
  const voices = state.options.filter(isVoice);
  const ready = voices.every(voiceReady);
  document.querySelector("#voices .vcols").hidden = !ready;
  $("slotnote").hidden = !ready;
  state.voices.forEach((id, n) => {
    const o = voices.find((x) => x.id === id);
    if (o) inst.append(voiceButton(o, `${FIRST_VOICE_SLOT + n}. ${o.title}`, () => uninstall(id), true));
  });
  if (!state.voices.length) inst.append(pix("li", "dim", "NONE YET."));
  const full = state.voices.length >= MAX_VOICES;
  for (const o of voices.filter((x) => !state.voices.includes(x.id))) {
    const over = overArea(withRequires([...picked(), o.id]));
    const merr = state.memory && state.memory.errors && state.memory.errors[o.id];
    const gone = unoffered(o);
    const note = !usable(o) && state.info ? `NOT AVAILABLE FOR ${state.info.version}`
      : gone.length ? `NEEDS ${gone.map(repoOf).join(", ").toUpperCase()}: GO BACK AND TICK IT`
      : over ? `?OUT OF MEMORY ERROR IN ${over.toUpperCase()}`
      : merr ? `?MEASURE ERROR: ${merr.toUpperCase().slice(0, 100)}` : full ? "ALL SLOTS TAKEN" : null;
    avail.append(voiceButton(o, o.title, () => install(o.id), usable(o) && !gone.length && !over && !merr && !full, note));
  }
  if (!voices.length) avail.append(pix("li", "dim", "NO VOICES FOUND."));
  for (const el of [host, inst, avail]) el.querySelectorAll(".pix").forEach(pixRender);
}

function showTab(tab) {
  state.tab = tab;
  for (const b of document.querySelectorAll(".tab")) b.setAttribute("aria-selected", String(b.dataset.tab === tab));
  $("mods").hidden = tab !== "mods";
  $("voices").hidden = tab !== "voices";
  pixAll();
}

function updatePatch() {
  const ready = state.info && state.info.official && state.info.supported && state.status && state.status.gcc;
  lock("s1", !ready || state.building);
  if (ready && !state.building) unlockRepos();
  lock("s2", !ready);
  $("patch").disabled = !ready || !picked().length || state.building;
  if (ready) renderMods();
  pixAll();
}

/* the image the start screen loaded: what it is, and measure it */
function showInfo(info) {
  const fw = $("fw");
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
      body: JSON.stringify({ image: state.image, options: [...state.chosen], voices: state.voices, checks: true }),
    });
    all.push("PATCHING...");
    logLines(all);
    let since = 0, snap;
    for (;;) {
      await new Promise((r) => setTimeout(r, 400));
      snap = await api(`/api/job/${job}?since=${since}`);
      since = snap.next;
      all.push(...snap.log);
      logLines(snap.partial ? [...all, snap.partial] : all);   // the renders' dots as they come
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

/* info: the image the intro loaded, if any */
async function main(info) {
  $("app").hidden = false;
  pixAll();
  scroller();
  try {
    state.status = await api("/api/status");
    await loadRepos();
    await loadMods();
  } catch (e) {
    say($("fw"), "err", `?CAN'T REACH THE MOD MATRIX SERVER: ${e.message.toUpperCase()}`);
  }
  if (state.status && state.status.stale) {
    say($("fw"), "err", "?THE MOD MATRIX WAS UPDATED SINCE IT STARTED. STOP IT (CTRL-C) AND START IT AGAIN.");
  }
  renderMods();
  if (info && state.status) showInfo(info);
  history.replaceState({ screen: "repos" }, "");
  showScreen("repos");

  $("patch").addEventListener("click", build);
  $("repos-ok").addEventListener("click", () => {
    history.pushState({ screen: "mods" }, "");
    showScreen("mods");
  });
  $("repos-back").addEventListener("click", () => history.back());
  addEventListener("popstate", (e) => showScreen((e.state && e.state.screen) || "repos"));
  for (const b of document.querySelectorAll(".tab")) b.addEventListener("click", () => showTab(b.dataset.tab));
  // hover/focus colours change the text colour, which the canvases have to redraw for
  for (const el of document.querySelectorAll(".patch, .dl, .tab, .go, .back")) {
    for (const ev of ["mouseenter", "mouseleave", "focus", "blur"]) {
      el.addEventListener(ev, () => requestAnimationFrame(() => el.querySelectorAll(".pix").forEach(pixRender)));
    }
  }
  // the text is wrapped to its pane's width: when the screen pane changes width (the memory
  // pane beside it grew or shrank, another screen), wrap it again
  let screenW = 0, rewrap = 0;
  if (window.ResizeObserver) new ResizeObserver((es) => {
    const w = Math.round(es[0].contentRect.width);
    if (w !== screenW) {
      screenW = w;
      cancelAnimationFrame(rewrap);
      rewrap = requestAnimationFrame(() => $("screen").querySelectorAll(".pix").forEach(pixRender));
    }
    renderMem();
  }).observe($("screen"));
  let rt;
  addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { pixAll(); renderMem(); }, 100); });
}

(async () => {
  let status = null;
  try { status = await (await fetch("/api/status")).json(); } catch (e) { /* offline: main says so */ }
  const quick = new URLSearchParams(location.search).has("nointro") || (status && status.intro === false);
  intro(status, main, quick);
})();
