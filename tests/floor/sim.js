// Headless floor simulation for tests/test_floor_sim.py: feed receipts, step time, report.
const fs = require("fs");
global.window = { __HERMES_PLUGIN_SDK__: { React: { createElement(){}, useRef(){}, useState(){return [0,()=>{}]}, useEffect(){} } }, __HERMES_PLUGINS__: { register(){} } };
global.document = { createElement: () => ({ getContext: () => new Proxy({}, { get: () => () => {} }) }) };
eval(fs.readFileSync(process.argv[2], "utf8"));
const F = window.__ARCADE_FLOOR__;
const rows = fs.readFileSync(process.argv[3], "utf8").trim().split("\n").map(JSON.parse)
  .filter(r => r.decision === "approved" || r.approver || r.decision === "denied" || r.decision === "handed_back")
  .map((r, i) => ({ seq: i + 1, ts: r.ts, role: r.role, profile: r.profile, via: r.via, tool: r.tool, toolkit: r.toolkit,
                    decision: r.decision, outcome: r.outcome, key: r.action_key, approver: r.approver, input: {} }));
const w = F.makeWorld(); w.mode = "live";
F.ingest(w, rows, true);
// activity: a thinker, a speaker, and a local tool that sends the analyst to the toolbox
F.ingestActivity(w, [{ n: 1, kind: "think", role: "cio", profile: "cio" },
                     { n: 2, kind: "say", role: "cio", profile: "cio", text: "Sizing the BTC trade." },
                     { n: 3, kind: "tool", role: "analyst", profile: "analyst-01", tool: "arcade_whoami" }], true);
let toolbox = 0, thought = !!(w.agents.cio && w.agents.cio.thought);
let coins = 0, t = 0;
for (; t < 240; t += 1/60) { F.step(w, 1/60); coins = Math.max(coins, w.coins.length); toolbox = Math.max(toolbox, w.toolbox);
  if (Object.values(w.agents).every(a => !a.busy && !a.queue.length && !a.path.length)) break; }
const idle = Object.values(w.agents).every(a => !a.busy && !a.queue.length && !a.path.length && Math.abs(a.x - a.hx) < 1 && Math.abs(a.y - a.hy) < 1);
console.log(JSON.stringify({ seconds: +t.toFixed(1), idle, coins, agents: Object.keys(w.agents).length, toolbox: toolbox > 0, thought,
                             thoughtCleared: !(w.agents.cio && w.agents.cio.thought), act: w.act }));
