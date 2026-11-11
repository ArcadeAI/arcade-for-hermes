// Thought clouds never overlap each other, whatever the crowd; speakers always get one when there is room.
const fs = require("fs");
global.window = {}; global.document = { createElement: () => ({ getContext: () => new Proxy({}, { get: () => () => {} }) }) };
new Function(fs.readFileSync(process.argv[2], "utf8"))();
const F = window.__ARCADE_FLOOR__;
const ov = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
let worst = 0, speakersShown = 0, speakers = 0, looks = new Set();
for (let trial = 0; trial < 60; trial++) {
  const w = F.makeWorld(); w.mode = "live";
  const n = 3 + (trial * 7) % 60, evs = [];
  for (let i = 1; i <= n; i++) evs.push({ seq: i, role: "analyst", profile: "analyst-" + String(i).padStart(3, "0"), tool: "x", decision: "allowed" });
  ["red", "blue", "cio", "cos"].forEach((r, i) => evs.push({ seq: n + i + 1, role: r, profile: r === "cos" ? "default" : r === "cio" ? "cio" : r + "-trader", tool: "x", decision: "allowed" }));
  F.ingest(w, evs, false);
  const acts = [];
  for (let i = 1; i <= n; i++) if ((i * 13 + trial) % 3 === 0) acts.push({ n: i, kind: "think", role: "analyst", profile: "analyst-" + String(i).padStart(3, "0") });
  acts.push({ n: 900, kind: "say", role: "red", profile: "red-trader", text: "Buying SOL on the 10s pop, $3,000." },
            { n: 901, kind: "say", role: "blue", profile: "blue-trader", text: "Trimming DOGE before it rolls over." });
  F.ingestActivity(w, acts, true);
  for (let t = 0; t < 1; t += 0.066) F.step(w, 0.066);
  const list = Object.values(w.agents).sort((p, q) => p.y - q.y);
  const L = F.layoutThoughts(list, []);
  for (let i = 0; i < L.length; i++) for (let j = i + 1; j < L.length; j++) if (ov(L[i].r, L[j].r)) worst++;
  speakers += 2; const got = L.filter((p) => p.a.thought).length; speakersShown += got; if (got < 2 && process.env.DEBUG) console.error("trial", trial, "n", n, JSON.stringify(L.map((p) => [p.a.id, p.r.x, p.r.y])), JSON.stringify(["red-trader","blue-trader"].map((id) => [w.agents[id].x, w.agents[id].y, !!w.agents[id].bubble])));
}
console.log(JSON.stringify({ overlaps: worst, speakers, speakersShown }));
// Jitter: on an arena floor, a cloud whose text did not change must not move between frames.
{
  const w = F.makeWorld(); w.mode = "live";
  F.ingest(w, [{ seq: 1, role: "red", profile: "red-trader", tool: "arena_market", decision: "allowed" },
               { seq: 2, role: "blue", profile: "blue-trader", tool: "arena_market", decision: "allowed" }], false);
  let moves = 0, frames = 0, last = {}, t = 0, n = 1000;
  for (let i = 0; i < 300; i++) {
    if (i % 40 === 0) F.ingestActivity(w, [{ n: n++, kind: "think", role: "red", profile: "red-trader", model: "anthropic/claude-sonnet-5.5" },
                                           { n: n++, kind: "think", role: "blue", profile: "blue-trader", model: "openai/gpt-5.6-luna" }], true);
    if (i % 90 === 20) F.ingestActivity(w, [{ n: n++, kind: "say", role: "red", profile: "red-trader", text: "Buying SOL on the 10s pop, $3,000." }], true);
    F.step(w, 0.066);
    const L = F.layoutThoughts(Object.values(w.agents).sort((p, q) => p.y - q.y), []);
    L.forEach((p) => { const k = (p.r.lines || []).join("|"), prev = last[p.a.id]; if (prev && prev.k === k && (prev.x !== p.r.cx || prev.y !== p.r.cy)) moves++; last[p.a.id] = { k, x: p.r.cx, y: p.r.cy }; });
    frames++;
  }
  console.log(JSON.stringify({ jitterMoves: moves, frames }));
}
