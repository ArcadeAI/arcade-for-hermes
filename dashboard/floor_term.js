#!/usr/bin/env node
/**
 * The Floor in a terminal (Rex, or any 24-bit color terminal).
 *
 * Runs the exact simulation and drawing code of the dashboard tab (dist/index.js) against a tiny
 * software canvas, then paints it with octant cells: each terminal cell is a 2x4 grid of sub-pixels in
 * two colors (Unicode 16 block octants; Ghostty-based terminals such as Rex draw them natively). Press
 * g, or pass --cells half, for the older half blocks (two pixels a cell) on terminals without octants. Text the renderer would draw as 3x5 pixels is
 * printed as real terminal characters instead, so it stays readable at any pane size. Only cells that
 * changed are rewritten, inside synchronized-output brackets, so it does not flicker.
 *
 * Data comes straight from the Hermes home, read-only and trimmed exactly like the dashboard API: no
 * principals, session keys, URLs or task ids ever reach the screen.
 *
 *   node dashboard/floor_term.js                 # LIVE, follows new receipts
 *   node dashboard/floor_term.js --replay BC-2026-003 --speed 4
 *   node dashboard/floor_term.js --roles red,blue   # only these roles (the arena)
 *   keys: l live, r replay, [ ] pick work order, s speed, g octant/half cells, q quit
 *   env:  HERMES_HOME (default ~/.hermes), ARCADE_FLOOR_FIRM
 */
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

// ------------------------------------------------------------------ software canvas
function parseColor(s) {
  if (typeof s !== "string") return [0, 0, 0, 1];
  if (s[0] === "#") { const n = parseInt(s.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1]; }
  const m = s.match(/rgba?\(([^)]+)\)/);
  if (m) { const p = m[1].split(",").map(Number); return [p[0] | 0, p[1] | 0, p[2] | 0, p.length > 3 ? p[3] : 1]; }
  return [0, 0, 0, 1];
}

class SoftCanvas {
  constructor(w = 1, h = 1) { this._w = w; this._h = h; this.px = new Uint8ClampedArray(w * h * 4); }
  // Like a real canvas, setting a dimension resizes (and clears) the pixel buffer.
  get width() { return this._w; }
  set width(v) { this._w = v | 0; this.px = new Uint8ClampedArray(this._w * this._h * 4); }
  get height() { return this._h; }
  set height(v) { this._h = v | 0; this.px = new Uint8ClampedArray(this._w * this._h * 4); }
  getContext() {
    if (!this.ctx) this.ctx = new SoftContext(this);
    return this.ctx;
  }
}

class SoftContext {
  constructor(canvas) {
    this.c = canvas;
    this.state = { tx: 0, ty: 0, sx: 1, sy: 1, clip: null };
    this.stack = [];
    this._fill = [0, 0, 0, 1];
    this.textOverlay = null;
  }
  set fillStyle(v) { this._fill = parseColor(v); }
  get fillStyle() { return this._fill; }
  save() { this.stack.push({ ...this.state }); }
  restore() { if (this.stack.length) this.state = this.stack.pop(); }
  translate(x, y) { this.state.tx += x * this.state.sx; this.state.ty += y * this.state.sy; }
  scale(x, y) { this.state.sx *= x; this.state.sy *= y; }
  beginPath() { this._rect = null; }
  rect(x, y, w, h) { this._rect = [x, y, w, h]; }
  clip() { if (this._rect) { const [x, y, w, h] = this._rect; this.state.clip = [x, y, x + w, y + h]; } }
  _put(x, y, r, g, b, a) {
    const cl = this.state.clip;
    if (cl && (x < cl[0] || y < cl[1] || x >= cl[2] || y >= cl[3])) return;
    if (x < 0 || y < 0 || x >= this.c.width || y >= this.c.height) return;
    const i = (y * this.c.width + x) * 4, p = this.c.px;
    if (a >= 1) { p[i] = r; p[i + 1] = g; p[i + 2] = b; p[i + 3] = 255; return; }
    p[i] = p[i] * (1 - a) + r * a; p[i + 1] = p[i + 1] * (1 - a) + g * a; p[i + 2] = p[i + 2] * (1 - a) + b * a; p[i + 3] = 255;
  }
  fillRect(x, y, w, h) {
    const s = this.state;
    let x0 = Math.round(s.tx + x * s.sx), x1 = Math.round(s.tx + (x + w) * s.sx);
    let y0 = Math.round(s.ty + y * s.sy), y1 = Math.round(s.ty + (y + h) * s.sy);
    if (x0 > x1) [x0, x1] = [x1, x0];
    if (y0 > y1) [y0, y1] = [y1, y0];
    const [r, g, b, a] = this._fill;
    for (let yy = Math.max(0, y0); yy < Math.min(this.c.height, y1); yy++)
      for (let xx = Math.max(0, x0); xx < Math.min(this.c.width, x1); xx++) this._put(xx, yy, r, g, b, a);
  }
  drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh) {
    if (dx === undefined) { dx = sx; dy = sy; sx = 0; sy = 0; sw = dw = img.width; sh = dh = img.height; }
    const s = this.state, src = img.px;
    for (let j = 0; j < dh; j++) for (let i = 0; i < dw; i++) {
      const u = sx + Math.floor(i * sw / dw), v = sy + Math.floor(j * sh / dh), k = (v * img.width + u) * 4;
      if (!src[k + 3]) continue;
      const X = Math.round(s.tx + (dx + i) * s.sx + (s.sx < 0 ? -1 : 0)), Y = Math.round(s.ty + (dy + j) * s.sy);
      this._put(X, Y, src[k], src[k + 1], src[k + 2], 1);
    }
  }
}

// ------------------------------------------------------------------ load the shared floor
global.window = {};
global.document = { createElement: () => new SoftCanvas() };
global.performance = global.performance || { now: () => Date.now() };
const bundle = fs.readFileSync(path.join(__dirname, "dist", "index.js"), "utf8");
new Function(bundle)();
const F = window.__ARCADE_FLOOR__;
if (!F || !F.draw) { console.error("floor bundle did not load"); process.exit(1); }

// ------------------------------------------------------------------ data (same trimming as plugin_api.py)
const HOME = process.env.HERMES_HOME || path.join(os.homedir(), ".hermes");
const DATA = path.join(HOME, "plugin-data", "arcade-for-hermes");
const INPUT_KEYS = ["symbol", "notional_usd", "notional", "side", "proposal_id", "issue_number", "state", "title"];
const short = (v, n) => { if (v == null) return null; const t = String(v).split(/\s+/).join(" "); return t.length <= n ? t : t.slice(0, n - 3) + "..."; };

function toEvent(row, seq) {
  const raw = row.input && typeof row.input === "object" ? row.input : {};
  const ap = row.approver && typeof row.approver === "object" ? row.approver : null;
  const input = {};
  INPUT_KEYS.forEach((k) => { if (k in raw) input[k] = short(raw[k], 40); });
  return { seq, id: row.id, key: row.action_key, ts: row.ts, role: row.role, profile: row.profile, via: row.via,
           tool: row.tool, toolkit: row.toolkit, verb: row.verb, decision: row.decision, outcome: row.outcome,
           reason: short(row.reason, 120), work_order: row.work_order, input,
           approver: ap ? { choice: ap.choice, decided_by: ap.decided_by, surface: ap.surface } : null };
}
const ONLY = (process.argv.includes("--roles") ? process.argv[process.argv.indexOf("--roles") + 1] : process.env.FLOOR_ROLES || "")
  .split(",").map((r) => r.trim()).filter(Boolean);
// a firm's crew (red_crew) is still the red team
const keep = (row) => !ONLY.length || ONLY.includes(row.role) || ONLY.includes(String(row.role || "").split("_")[0])
  || ONLY.includes(String(row.profile || "").split("-")[0]);   // a quant seat's role is its job; its team is its profile
function readEvents(after, wo) {
  let text = "";
  try { text = fs.readFileSync(path.join(DATA, "receipts.jsonl"), "utf8"); } catch (e) { return []; }
  const out = [];
  text.split("\n").forEach((line, i) => {
    const seq = i + 1;
    if (seq <= after || !line.trim()) return;
    let row; try { row = JSON.parse(line); } catch (e) { return; }
    if (!row || typeof row !== "object" || (wo && row.work_order !== wo) || !keep(row)) return;
    if (!row.role) return;   // the founder's own switches (halt, resume, mode) are not an agent on the floor
    out.push(toEvent(row, seq));
  });
  return after === 0 ? out.slice(-600) : out.slice(0, 600);
}
function readActivity(after) {
  let text = "";
  try { text = fs.readFileSync(path.join(DATA, "activity.jsonl"), "utf8"); } catch (e) { return []; }
  const outRows = [];
  text.split("\n").forEach((line) => {
    let row; try { row = JSON.parse(line); } catch (e) { return; }
    if (!row || typeof row !== "object" || !(Number(row.n) > after) || !keep(row)) return;
    outRows.push({ n: Number(row.n), kind: short(row.kind, 16), role: short(row.role, 32), profile: short(row.profile, 32),
                   tool: short(row.tool, 48), text: short(row.text, 96), model: short(row.model, 48) });
  });
  return outRows.slice(-300);
}
// The control team (arena.py --no-arcade) has no Arcade receipts: the arena plugin's witness records
// its calls and what the gate would have said, plus its thinking. Own cursors: both feeds are clocked
// in nanoseconds, so sharing one would skip rows.
const ARENA_DIR = path.join(HOME, "plugin-data", "arena");
let witAfter = 0, rawAfter = 0;
function readJsonl(file) {
  let text = ""; try { text = fs.readFileSync(path.join(ARENA_DIR, file), "utf8"); } catch (e) { return []; }
  const rows = []; text.split("\n").forEach((l) => { try { const r = JSON.parse(l); if (r && typeof r === "object") rows.push(r); } catch (e) { /* partial line */ } });
  return rows;
}
function readWitness() {
  const out = readJsonl("witness.jsonl").filter((r) => Number(r.n) > witAfter && keep(r));
  if (out.length) witAfter = Math.max(...out.map((r) => Number(r.n)));
  return out.map((r) => ({ ...toEvent({ ...r, ts: new Date((r.ts || 0) * 1000).toISOString(), decision: "unguarded", reason: r.would_reason }, 0),
                           breach: r.would === "denied" || r.would === "approval" }));
}
function readRawActivity() {
  const out = readJsonl("activity-raw.jsonl").filter((r) => Number(r.n) > rawAfter && keep(r));
  if (out.length) rawAfter = Math.max(...out.map((r) => Number(r.n)));
  return out.map((row) => ({ n: Number(row.n), kind: short(row.kind, 16), role: short(row.role, 32), profile: short(row.profile, 32),
                             tool: short(row.tool, 48), text: short(row.text, 96), model: short(row.model, 48) }));
}
function ingestRaw(animate) {
  F.ingest(world, readWitness(), animate);
  const act = world.act; F.ingestActivity(world, readRawActivity(), animate); world.act = act;
}
function readWaiting() {
  let data; try { data = JSON.parse(fs.readFileSync(path.join(DATA, "waiting.json"), "utf8")); } catch (e) { return []; }
  const now = Date.now() / 1000;
  return Object.entries(data || {}).filter(([, v]) => v && now - (v.since || 0) <= 900)
    .map(([key, v]) => ({ key, role: v.role, profile: v.profile, via: v.via, tool: v.tool, toolkit: v.toolkit, work_order: v.work_order, since: v.since }));
}
function readBook() {
  const dir = path.join(HOME, "plugin-data", "koopa");
  let acct; try { acct = JSON.parse(fs.readFileSync(path.join(dir, "account.json"), "utf8")); } catch (e) { return null; }
  const prices = {}; Object.entries(acct.prices || {}).forEach(([s, p]) => { prices[s] = Number((p || {}).price || 0); });
  let held = 0; Object.entries(acct.positions || {}).forEach(([s, q]) => { held += Number(q || 0) * (prices[s] || 0); });
  let fills = 0;
  try { fs.readFileSync(path.join(dir, "ledger.jsonl"), "utf8").split("\n").forEach((l) => { try { if (JSON.parse(l).kind === "fill") fills++; } catch (e) {} }); } catch (e) {}
  const cash = Number(acct.cash_usd || 0);
  return { label: acct.label || "PAPER MODE", cash_usd: cash, book_usd: cash + held, fills };
}
function workOrders() {
  const seen = new Map();
  readEvents(0).forEach((e) => {
    if (!e.work_order) return;
    const w = seen.get(e.work_order) || { work_order: e.work_order, events: 0, last: e.ts };
    w.events++; w.last = e.ts; seen.set(e.work_order, w);
  });
  return [...seen.values()].sort((a, b) => (b.events - a.events) || String(b.last).localeCompare(String(a.last)));
}

// ------------------------------------------------------------------ the loop
const args = process.argv.slice(2);
const argVal = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const ui = { term: true, hover: null, buttons: [], workOrders: workOrders(), woIndex: 0, speed: Number(argVal("--speed")) || 1,
             cells: argVal("--cells") || process.env.FLOOR_CELLS || "octant" };
const world = F.makeWorld();
// The firm's name: the env, else the founded company's name, else the original demo's.
function companyName() {
  try { const m = /^name:\s*(.+)$/m.exec(fs.readFileSync(path.join(HOME, "arcade", "company.yaml"), "utf8")); return m ? m[1].trim().replace(/^["']|["']$/g, "") : null; }
  catch (e) { return null; }
}
// The company's apps, in role order, become the shelves (block lists under "apps:").
function companyApps() {
  let text = ""; try { text = fs.readFileSync(path.join(HOME, "arcade", "company.yaml"), "utf8"); } catch (e) { return []; }
  const apps = []; let inApps = false;
  text.split("\n").forEach((line) => {
    if (/^\s+apps:\s*$/.test(line)) { inApps = true; return; }
    const m = /^\s+-\s+(\S+)\s*$/.exec(line);
    if (inApps && m) { if (!apps.includes(m[1])) apps.push(m[1]); return; }
    inApps = false;
  });
  return apps;
}
if (F.setKits) F.setKits(companyApps());
const firm = (process.env.ARCADE_FLOOR_FIRM || companyName() || "BOWSER CAPITAL").toUpperCase();
let timers = [];

function reset(mode) { timers.forEach(clearTimeout); timers = []; const fresh = F.makeWorld(); Object.keys(fresh).forEach((k) => { world[k] = fresh[k]; }); world.mode = mode; world.firm = firm; world.arena = readArena(); }
// --fresh: open on an empty floor and show only what happens from now (the studio films from a clean start).
let freshStart = process.argv.includes("--fresh");
function goLive() {
  reset("live"); world.book = readBook();
  if (freshStart) {
    freshStart = false;
    const evs = readEvents(0), acts = readActivity(0);
    world.seq = evs.length ? evs[evs.length - 1].seq : 0;
    world.act = acts.length ? acts[acts.length - 1].n : 0;
    readJsonl("witness.jsonl").forEach((r) => { witAfter = Math.max(witAfter, Number(r.n) || 0); });
    readJsonl("activity-raw.jsonl").forEach((r) => { rawAfter = Math.max(rawAfter, Number(r.n) || 0); });
    return;
  }
  F.ingest(world, readEvents(0), false);
  F.ingestActivity(world, readActivity(0), false);
  witAfter = 0; rawAfter = 0; ingestRaw(false);
  readWaiting().forEach((w) => F.holdAtDoor(world, w));
}
function replay(wo) {
  if (!wo) return;
  reset("replay"); world.replayWo = wo; world.book = readBook();
  const evs = readEvents(0, wo); let t = 0, prev = null;
  evs.forEach((e) => F.ensureAgent(world, e));
  evs.forEach((e) => { const ts = Date.parse(e.ts) || 0; const gap = prev == null ? 0.4 : Math.min(2.4, Math.max(0.25, (ts - prev) / 1000 / 20)); prev = ts; t += gap / ui.speed;
    const founder = e.decision === "approved" || (e.decision === "denied" && e.approver) || e.decision === "handed_back";
    timers.push(setTimeout(() => { if (world.mode === "replay") F.ingest(world, [e], true); }, t * 1000));
    if (founder) t += 3.5; });
}
const startWo = argVal("--replay");
if (startWo) { ui.woIndex = Math.max(0, ui.workOrders.findIndex((w) => w.work_order === startWo)); replay(startWo); } else goLive();

function readArena() {
  try { return JSON.parse(fs.readFileSync(path.join(HOME, "plugin-data", "arena", "scoreboard.json"), "utf8")); } catch (e) { return null; }
}
setInterval(() => { world.arena = readArena(); }, 1000);
setInterval(() => {
  if (world.mode !== "live") return;
  world.book = readBook();
  readWaiting().forEach((w) => F.holdAtDoor(world, w));
  F.ingest(world, readEvents(world.seq), true);
  F.ingestActivity(world, readActivity(world.act), true);
  ingestRaw(true);
}, 1500);

// ------------------------------------------------------------------ cell painters
// Pixel-art scale: at 1x or more, snap to a whole number so every game pixel is the same size.
function fitScale(subW, subH) {
  const s = Math.min(subW / F.W, subH / F.H);
  return s >= 1 ? Math.floor(s) : s;
}
// The color of one target sub-pixel. Shrinking pixel art by averaging turns sprites to mud, so keep
// the most distinct pixel in the source box (a shirt, a lamp, a coin) when it stands well apart.
function sampler(scale) {
  return (tx, ty) => {
    const x0 = Math.floor(tx / scale), x1 = Math.max(x0 + 1, Math.floor((tx + 1) / scale));
    const y0 = Math.floor(ty / scale), y1 = Math.max(y0 + 1, Math.floor((ty + 1) / scale));
    const ys = Math.min(F.H, y1), xs = Math.min(F.W, x1);
    if (x1 - x0 === 1 && y1 - y0 === 1) { const i = (y0 * F.W + x0) * 4; return x0 < F.W && y0 < F.H ? [canvas.px[i], canvas.px[i + 1], canvas.px[i + 2]] : [0, 0, 0]; }
    let r = 0, gg = 0, b = 0, n = 0;
    for (let y = y0; y < ys; y++) for (let x = x0; x < xs; x++) { const i = (y * F.W + x) * 4; r += canvas.px[i]; gg += canvas.px[i + 1]; b += canvas.px[i + 2]; n++; }
    if (!n) return [0, 0, 0];
    r /= n; gg /= n; b /= n;
    let best = null, bd = 0;
    for (let y = y0; y < ys; y++) for (let x = x0; x < xs; x++) {
      const i = (y * F.W + x) * 4, d = Math.abs(canvas.px[i] - r) + Math.abs(canvas.px[i + 1] - gg) + Math.abs(canvas.px[i + 2] - b);
      if (d > bd) { bd = d; best = i; }
    }
    return bd > 90 ? [canvas.px[best], canvas.px[best + 1], canvas.px[best + 2]] : [r | 0, gg | 0, b | 0];
  };
}
function paintHalf(cols, rows) {
  const scale = fitScale(cols, rows * 2), sample = sampler(scale);
  const gw = Math.min(cols, Math.floor(F.W * scale)), gh = Math.min(rows, Math.ceil(F.H * scale / 2));
  const ox = Math.floor((cols - gw) / 2), oy = Math.floor((rows - gh) / 2);
  const cells = new Array(rows * cols).fill(null);
  for (let cy = 0; cy < gh; cy++) for (let cx = 0; cx < gw; cx++)
    cells[(cy + oy) * cols + cx + ox] = { ch: "\u2580", fg: sample(cx, cy * 2), bg: sample(cx, cy * 2 + 1) };
  cells.geo = { scale, ox, oy, sx: 1, sy: 2 };
  return cells;
}
// Octants (Unicode 16): a cell is 2x4 sub-pixels, so four times the detail of half blocks. A cell
// still has only two colors, so each one keeps the two most different colors it covers.
const OCTANT = [0x20,0x1cea8,0x1ceab,0x1fb82,0x1cd00,0x2598,0x1cd01,0x1cd02,0x1cd03,0x1cd04,0x259d,0x1cd05,0x1cd06,0x1cd07,0x1cd08,0x2580,0x1cd09,0x1cd0a,0x1cd0b,0x1cd0c,0x1fbe6,0x1cd0d,0x1cd0e,0x1cd0f,0x1cd10,0x1cd11,0x1cd12,0x1cd13,0x1cd14,0x1cd15,0x1cd16,0x1cd17,0x1cd18,0x1cd19,0x1cd1a,0x1cd1b,0x1cd1c,0x1cd1d,0x1cd1e,0x1cd1f,0x1fbe7,0x1cd20,0x1cd21,0x1cd22,0x1cd23,0x1cd24,0x1cd25,0x1cd26,0x1cd27,0x1cd28,0x1cd29,0x1cd2a,0x1cd2b,0x1cd2c,0x1cd2d,0x1cd2e,0x1cd2f,0x1cd30,0x1cd31,0x1cd32,0x1cd33,0x1cd34,0x1cd35,0x1fb85,0x1cea3,0x1cd36,0x1cd37,0x1cd38,0x1cd39,0x1cd3a,0x1cd3b,0x1cd3c,0x1cd3d,0x1cd3e,0x1cd3f,0x1cd40,0x1cd41,0x1cd42,0x1cd43,0x1cd44,0x2596,0x1cd45,0x1cd46,0x1cd47,0x1cd48,0x258c,0x1cd49,0x1cd4a,0x1cd4b,0x1cd4c,0x259e,0x1cd4d,0x1cd4e,0x1cd4f,0x1cd50,0x259b,0x1cd51,0x1cd52,0x1cd53,0x1cd54,0x1cd55,0x1cd56,0x1cd57,0x1cd58,0x1cd59,0x1cd5a,0x1cd5b,0x1cd5c,0x1cd5d,0x1cd5e,0x1cd5f,0x1cd60,0x1cd61,0x1cd62,0x1cd63,0x1cd64,0x1cd65,0x1cd66,0x1cd67,0x1cd68,0x1cd69,0x1cd6a,0x1cd6b,0x1cd6c,0x1cd6d,0x1cd6e,0x1cd6f,0x1cd70,0x1cea0,0x1cd71,0x1cd72,0x1cd73,0x1cd74,0x1cd75,0x1cd76,0x1cd77,0x1cd78,0x1cd79,0x1cd7a,0x1cd7b,0x1cd7c,0x1cd7d,0x1cd7e,0x1cd7f,0x1cd80,0x1cd81,0x1cd82,0x1cd83,0x1cd84,0x1cd85,0x1cd86,0x1cd87,0x1cd88,0x1cd89,0x1cd8a,0x1cd8b,0x1cd8c,0x1cd8d,0x1cd8e,0x1cd8f,0x2597,0x1cd90,0x1cd91,0x1cd92,0x1cd93,0x259a,0x1cd94,0x1cd95,0x1cd96,0x1cd97,0x2590,0x1cd98,0x1cd99,0x1cd9a,0x1cd9b,0x259c,0x1cd9c,0x1cd9d,0x1cd9e,0x1cd9f,0x1cda0,0x1cda1,0x1cda2,0x1cda3,0x1cda4,0x1cda5,0x1cda6,0x1cda7,0x1cda8,0x1cda9,0x1cdaa,0x1cdab,0x2582,0x1cdac,0x1cdad,0x1cdae,0x1cdaf,0x1cdb0,0x1cdb1,0x1cdb2,0x1cdb3,0x1cdb4,0x1cdb5,0x1cdb6,0x1cdb7,0x1cdb8,0x1cdb9,0x1cdba,0x1cdbb,0x1cdbc,0x1cdbd,0x1cdbe,0x1cdbf,0x1cdc0,0x1cdc1,0x1cdc2,0x1cdc3,0x1cdc4,0x1cdc5,0x1cdc6,0x1cdc7,0x1cdc8,0x1cdc9,0x1cdca,0x1cdcb,0x1cdcc,0x1cdcd,0x1cdce,0x1cdcf,0x1cdd0,0x1cdd1,0x1cdd2,0x1cdd3,0x1cdd4,0x1cdd5,0x1cdd6,0x1cdd7,0x1cdd8,0x1cdd9,0x1cdda,0x2584,0x1cddb,0x1cddc,0x1cddd,0x1cdde,0x2599,0x1cddf,0x1cde0,0x1cde1,0x1cde2,0x259f,0x1cde3,0x2586,0x1cde4,0x1cde5,0x2588].map((cp) => String.fromCodePoint(cp));
const dist = (a, b) => Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]);
function paintOctant(cols, rows) {
  const scale = fitScale(cols * 2, rows * 4), sample = sampler(scale);
  const sw = Math.floor(F.W * scale), shh = Math.floor(F.H * scale);
  const gw = Math.min(cols, Math.ceil(sw / 2)), gh = Math.min(rows, Math.ceil(shh / 4));
  const ox = Math.floor((cols - gw) / 2), oy = Math.floor((rows - gh) / 2);
  const cells = new Array(rows * cols).fill(null);
  const px = new Array(8);
  for (let cy = 0; cy < gh; cy++) for (let cx = 0; cx < gw; cx++) {
    for (let k = 0; k < 8; k++) {
      const tx = cx * 2 + (k & 1), ty = cy * 4 + (k >> 1);
      px[k] = tx < sw && ty < shh ? sample(tx, ty) : [0, 0, 0];
    }
    let a = 0, b = 0, far = -1;
    for (let i = 0; i < 8; i++) for (let j = i + 1; j < 8; j++) { const d = dist(px[i], px[j]); if (d > far) { far = d; a = i; b = j; } }
    let cell;
    if (far < 24) cell = { ch: " ", fg: px[0], bg: px[0], bgText: px[0] };
    else {
      let mask = 0;
      for (let k = 0; k < 8; k++) if (dist(px[k], px[a]) <= dist(px[k], px[b])) mask |= 1 << k;
      // the background for text printed over this cell: whichever color covers more of it
      let on = 0; for (let k = 0; k < 8; k++) if (mask >> k & 1) on++;
      cell = { ch: OCTANT[mask], mask, fg: px[a], bg: px[b], bgText: on > 4 ? px[a] : px[b] };
    }
    cells[(cy + oy) * cols + cx + ox] = cell;
  }
  cells.geo = { scale, ox, oy, sx: 2, sy: 4 };
  return cells;
}

// ------------------------------------------------------------------ paint
const out = process.stdout;
const canvas = new SoftCanvas(F.W, F.H);
const g = canvas.getContext();
let overlays = [];
// Text keeps the clip it was drawn under (the header ticker scrolls inside one strip).
g.textOverlay = (s, x, y, color) => overlays.push({ s, x, y, color: parseColor(color), clip: g.state.clip ? g.state.clip.slice() : null });
let prev = null, prevCols = 0, prevRows = 0;

function frame(dt) {
  F.setSayScale(world.mode === "replay" ? ui.speed * 1.5 : 1);
  world.speed = ui.speed;
  F.step(world, dt * (world.mode === "replay" ? ui.speed : 1));
  canvas.px.fill(0); overlays = [];
  g.state = { tx: 0, ty: 0, sx: 1, sy: 1, clip: null }; g.stack = [];
  F.draw(g, world, ui);

  const forced = (argVal("--size") || "").match(/^(\d+)x(\d+)$/);
  const cols = forced ? +forced[1] : out.columns || 160, rows = Math.max(10, (forced ? +forced[2] : out.rows || 48) - 1);
  const cells = ui.cells === "half" ? paintHalf(cols, rows) : paintOctant(cols, rows);
  const { scale, ox, oy, sx, sy } = cells.geo;
  // text as real characters, on the color already under it
  const taken = new Uint8Array(rows * cols);
  overlays.forEach((o) => {
    const cx0 = Math.round(o.x * scale / sx) + ox;
    let cy = Math.round((o.y + 2) * scale / sy) + oy;
    // At small sizes several pixel rows of text share one terminal row: move down instead of overwriting.
    const clash = (row) => { for (let i = 0; i < o.s.length; i++) { const cx = cx0 + i; if (cx >= 0 && cx < cols && taken[row * cols + cx]) return true; } return false; };
    // Clipped text (the ticker) never moves rows: it keeps to its strip and gives way to what is there.
    const inClip = (cx) => !o.clip || ((cx - ox) * sx / scale >= o.clip[0] && (cx - ox) * sx / scale < o.clip[2]);
    if (!o.clip) for (let tries = 0; tries < 3 && cy < rows && clash(cy); tries++) cy++;
    if (cy < 0 || cy >= rows) return;
    for (let i = 0; i < o.s.length; i++) { const cx = cx0 + i; if (cx >= 0 && cx < cols && inClip(cx) && !(o.clip && taken[cy * cols + cx])) taken[cy * cols + cx] = o.clip ? 2 : 1; }
    for (let i = 0; i < o.s.length; i++) {
      const cx = cx0 + i;
      if (cx < 0 || cx >= cols || !inClip(cx)) continue;
      if (o.clip && taken[cy * cols + cx] !== 2) continue;
      const under = cells[cy * cols + cx];
      const bg = under ? (o.s[i] === " " ? under.bg : under.bgText || blend(under.fg, under.bg)) : [0, 0, 0];
      cells[cy * cols + cx] = { ch: o.s[i], fg: o.color.slice(0, 3), bg };
    }
  });

  if (snapshot && Date.now() >= snapshot.at) { writeSnapshot(cells, cols, rows); process.exit(0); }
  const full = !prev || cols !== prevCols || rows !== prevRows;
  const keys = cells.map((c) => (c ? c.ch + c.fg.join() + c.bg.join() : " "));
  let buf = "\x1b[?2026h" + (full ? "\x1b[0m\x1b[2J" : "");
  let lastFg = null, lastBg = null;
  for (let y = 0; y < rows; y++) {
    let cursorAt = -1;
    for (let x = 0; x < cols; x++) {
      const k = y * cols + x, c = cells[k];
      if (!full && prev[k] === keys[k]) continue;
      if (cursorAt !== x) buf += `\x1b[${y + 1};${x + 1}H`;
      if (!c) { buf += "\x1b[0m "; lastFg = lastBg = null; }
      else {
        const fg = c.fg.join(";"), bg = c.bg.join(";");
        if (fg !== lastFg) { buf += `\x1b[38;2;${fg}m`; lastFg = fg; }
        if (bg !== lastBg) { buf += `\x1b[48;2;${bg}m`; lastBg = bg; }
        buf += c.ch;
      }
      cursorAt = x + 1;
    }
  }
  prev = keys; prevCols = cols; prevRows = rows;
  if (!snapPath) out.write(buf + "\x1b[0m\x1b[?2026l");
}
const snapPath = argVal("--snapshot");
const snapshot = snapPath ? { at: Date.now() + 1000 * (Number(argVal("--after")) || 6) } : null;
// A PNG of what a terminal with 7x14 cells would show: octant and half cells drawn exactly, text cells
// as their background with a bar in the text color. For checking the renderer without a terminal.
function writePng(cells, cols, rows, file) {
  const zlib = require("zlib"), CW = 8, CH = 16, w = cols * CW, h = rows * CH, raw = Buffer.alloc((w * 3 + 1) * h);
  const put = (x, y, c) => { const i = y * (w * 3 + 1) + 1 + x * 3; raw[i] = c[0]; raw[i + 1] = c[1]; raw[i + 2] = c[2]; };
  for (let cy = 0; cy < rows; cy++) for (let cx = 0; cx < cols; cx++) {
    const c = cells[cy * cols + cx];
    for (let y = 0; y < CH; y++) for (let x = 0; x < CW; x++) {
      let col = [0, 0, 0];
      if (c) {
        if (c.mask !== undefined) col = (c.mask >> ((y >> 2) * 2 + (x >> 2)) & 1) ? c.fg : c.bg;
        else if (c.ch === "\u2580") col = y < CH / 2 ? c.fg : c.bg;
        else if (c.ch === " ") col = c.bg;
        else col = (y >= 5 && y <= 11 && x >= 1 && x <= 6) ? c.fg : c.bg;
      }
      put(cx * CW + x, cy * CH + y, col);
    }
  }
  const crc = (buf) => { let c = ~0; for (const b of buf) { c ^= b; for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1)); } return ~c >>> 0; };
  const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const cr = Buffer.alloc(4); cr.writeUInt32BE(crc(td)); return Buffer.concat([len, td, cr]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  fs.writeFileSync(file, Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]));
}
function writeSnapshot(cells, cols, rows) {
  if (snapPath.endsWith(".png")) return writePng(cells, cols, rows, snapPath);
  const esc = (ch) => (ch === "<" ? "&lt;" : ch === ">" ? "&gt;" : ch === "&" ? "&amp;" : ch);
  let html = '<!doctype html><meta charset="utf-8"><body style="background:#000;margin:16px">' +
             '<pre style="font:13px/1 Menlo,monospace;margin:0">';
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const c = cells[y * cols + x];
      html += c ? `<span style="color:rgb(${c.fg})background:rgb(${c.bg})">${esc(c.ch)}</span>`.replace(")background", ");background") : " ";
    }
    html += "\n";
  }
  fs.writeFileSync(snapPath, html + "</pre>");
}
function blend(a, b) { return [(a[0] + b[0]) >> 1, (a[1] + b[1]) >> 1, (a[2] + b[2]) >> 1]; }

if (!snapPath) out.write("\x1b[?1049h\x1b[?25l");
const restore = () => { if (!snapPath) out.write("\x1b[0m\x1b[?25h\x1b[?1049l"); };
process.on("exit", restore);
process.on("SIGINT", () => process.exit(0));
process.on("SIGTERM", () => process.exit(0));
out.on("resize", () => { prev = null; });

if (process.stdin.isTTY && !snapPath) {
  process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdin.on("data", (d) => {
    const k = d.toString();
    if (k === "q" || k === "\u0003") process.exit(0);
    else if (k === "l") goLive();
    else if (k === "r") { const w = ui.workOrders[ui.woIndex]; if (w) replay(w.work_order); }
    else if (k === "[" || k === "]") { ui.workOrders = workOrders(); if (ui.workOrders.length) ui.woIndex = (ui.woIndex + (k === "]" ? 1 : -1) + ui.workOrders.length) % ui.workOrders.length; }
    else if (k === "g") { ui.cells = ui.cells === "half" ? "octant" : "half"; prev = null; }
    else if (k === "s") ui.speed = { 1: 2, 2: 4, 4: 8, 8: 1 }[ui.speed] || 1;
  });
}

let last = Date.now();
setInterval(() => { const now = Date.now(); frame(Math.min(0.05, (now - last) / 1000)); last = now; }, 66);
