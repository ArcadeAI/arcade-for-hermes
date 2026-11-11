/**
 * The Floor: an 8-bit view of Arcade for Hermes receipts.
 *
 * Every governed tool call is a little worker walking from their desk to the policy GATE.
 *   look / draft allowed  -> gate lamp green, through to the toolkit door, back to the desk
 *   local Hermes tool     -> walk to the toolbox on the floor (no gate: Arcade does not govern it)
 *   thinking / intent     -> a thought cloud: dots while the model runs, then the line it said
 *   denied by policy      -> gate slams red, bonk, the policy's reason in a bubble, walk back
 *   handed back           -> the worker drops a note at the gate; it flies to the chief of staff
 *   ship                  -> down the corridor to the FOUNDER's door; the phone rings; the door
 *                            opens green on an approve (then through to the toolkit, coins on a
 *                            Koopa fill) or flashes red on a deny or a timeout
 * Nothing moves unless a receipt says so; the floor is a view, never a source. LIVE polls the
 * plugin's read-only API; REPLAY plays one work order's receipts back.
 *
 * Plain IIFE, no build step, no network assets: palette, sprites and the 3x5 font are drawn here.
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var HOSTED = !!(SDK && window.__HERMES_PLUGINS__);
  var React = HOSTED ? SDK.React : null;
  var h = HOSTED ? React.createElement : null;
  var API = "/api/plugins/arcade-for-hermes";

  // ---------------------------------------------------------------- palette (original)
  var C = {
    ink: "#0d0b14", night: "#16132a", wall: "#262142", wallHi: "#332c58", trim: "#4a3f7a",
    floorA: "#2e2851", floorB: "#29234a", desk: "#6b4a2f", deskTop: "#9a6b3c", deskEdge: "#4a321f",
    metal: "#8a93b8", metalDk: "#4d5478", cream: "#f4ecd8", dim: "#8f86b3",
    green: "#3ddc84", red: "#ff4d5e", amber: "#ffb43a", gold: "#ffd75e", goldDk: "#c98a1b",
    skin: "#f1b98c", skinDk: "#c98a62", screen: "#5ef2d6", screenDk: "#1f6f68", led: "#ff9f1c", ledDk: "#3a2208",
  };
  var ROLE = {
    cos: { body: "#ff7a3d", hair: "#3b1f0f", tag: "COS" },
    cio: { body: "#4fb3ff", hair: "#14233b", tag: "CIO" },
    analyst: { body: "#7bd36b", hair: "#1f2d14", tag: "ANALYST" },
    skeptic: { body: "#c77dff", hair: "#2a1238", tag: "SKEPTIC" },
    risk: { body: "#ffd23f", hair: "#3b2a07", tag: "RISK" },
    reporter: { body: "#ff6fb1", hair: "#3b0f24", tag: "REPORTER" },
    red: { body: "#e8323f", hair: "#3b0a0f", tag: "RED" },
    blue: { body: "#2f7dff", hair: "#0a1a3b", tag: "BLUE" },
    other: { body: "#a6a2bf", hair: "#2a2838", tag: "AGENT" },
  };
  // a firm's crew (red_crew) plays for its team: same colors, same room
  // A founded company's own roles (coo, eng_lead, support...) get a color of their own and their name as the tag.
  var SPARE = [["#3ddc84", "#12301e"], ["#4fb3ff", "#14233b"], ["#ff7a3d", "#3b1f0f"], ["#c77dff", "#2a1238"],
               ["#ffd23f", "#3b2a07"], ["#ff6fb1", "#3b0f24"], ["#5ef2d6", "#103a35"], ["#f4ecd8", "#3a3428"]];
  var spareUsed = 0;
  function roleOf(r) {
    r = String(r || ""); if (/^(red|blue)_crew$/.test(r)) r = r.split("_")[0];
    if (ROLE[r]) return r;
    if (!/^[a-z][a-z0-9_]{0,31}$/.test(r)) return "other";
    var c = SPARE[spareUsed++ % SPARE.length];
    ROLE[r] = { body: c[0], hair: c[1], tag: r.replace(/_/g, " ").toUpperCase().slice(0, 10), dyn: true };
    return r;
  }
  // the seat a team profile sits in: red-cio -> cio, blue-analyst-2 -> analyst-2, red-trader -> trader
  function seatOf(id) { var m = /^(red|blue)-(.+?)(-raw)?$/.exec(String(id || "")); return m ? m[2] : ""; }
  var SEAT_TAG = { cio: "CIO", trader: "TRADER", skeptic: "SKEP", "analyst-1": "AN1", "analyst-2": "AN2",
                   exec: "EXEC", pm: "PM", data: "DATA", "researcher-1": "RS1", "researcher-2": "RS2", quantdev: "QDEV",
                   riskmgr: "RISK", compliance: "COMP", ir: "IR" };
  function seatTag(a) { return SEAT_TAG[a.seat] || String(a.seat || a.role).toUpperCase().slice(0, 6); }
  function isLead(a) { return !a.seat || a.seat === "cio" || a.seat === "trader" || a.seat === "exec"; }

  // ---------------------------------------------------------------- 3x5 bitmap font
  // 3 wide x 5 tall, one string per row.
  var GLYPH_ROWS = { "A": ".#. #.# ### #.# #.#", "B": "##. #.# ##. #.# ##.", "C": ".## #.. #.. #.. .##", "D": "##. #.# #.# #.# ##.", "E": "### #.. ##. #.. ###", "F": "### #.. ##. #.. #..", "G": ".## #.. #.# #.# .##", "H": "#.# #.# ### #.# #.#", "I": "### .#. .#. .#. ###", "J": "..# ..# ..# #.# .#.", "K": "#.# #.# ##. #.# #.#", "L": "#.. #.. #.. #.. ###", "M": "#.# ### ### #.# #.#", "N": "##. #.# #.# #.# #.#", "O": ".#. #.# #.# #.# .#.", "P": "##. #.# ##. #.. #..", "Q": ".#. #.# #.# ##. .##", "R": "##. #.# ##. #.# #.#", "S": ".## #.. .#. ..# ##.", "T": "### .#. .#. .#. .#.", "U": "#.# #.# #.# #.# ###", "V": "#.# #.# #.# #.# .#.", "W": "#.# #.# ### ### #.#", "X": "#.# #.# .#. #.# #.#", "Y": "#.# #.# .#. .#. .#.", "Z": "### ..# .#. #.. ###", "0": "### #.# #.# #.# ###", "1": ".#. ##. .#. .#. ###", "2": "##. ..# .#. #.. ###", "3": "##. ..# .#. ..# ##.", "4": "#.# #.# ### ..# ..#", "5": "### #.. ##. ..# ##.", "6": ".## #.. ### #.# ###", "7": "### ..# .#. .#. .#.", "8": "### #.# ### #.# ###", "9": "### #.# ### ..# ##.", ".": "... ... ... ... .#.", ",": "... ... ... .#. #..", ":": "... .#. ... .#. ...", "-": "... ... ### ... ...", "/": "..# ..# .#. #.. #..", "$": ".## ##. .#. .## ##.", "!": ".#. .#. .#. ... .#.", "?": "##. ..# .#. ... .#.", "'": ".#. .#. ... ... ...", "(": "..# .#. .#. .#. ..#", ")": "#.. .#. .#. .#. #..", "%": "#.# ..# .#. #.. #.#", "+": "... .#. ### .#. ...", ">": "#.. .#. ..# .#. #..", "<": "..# .#. #.. .#. ..#", "_": "... ... ... ... ###", "=": "... ### ... ### ...", "#": "#.# ### #.# ### #.#", "@": ".#. #.# ### #.. .##", "*": "... #.# .#. #.# ...", "&": ".#. #.# .#. #.# .##" };
  var GLYPHS = {};
  Object.keys(GLYPH_ROWS).forEach(function (k) { GLYPHS[k] = GLYPH_ROWS[k].split(" ").join(""); });

  function textW(s) { return String(s).length * 4 - 1; }
  function text(g, s, x, y, color, shadow, keepCase) {
    var raw = String(s);
    s = raw.toUpperCase();
    if (g.textOverlay) { g.textOverlay(keepCase ? raw : s, x, y, color); return; }
    if (shadow) text(g, s, x + 1, y + 1, shadow);
    g.fillStyle = color;
    for (var i = 0; i < s.length; i++) {
      var gl = GLYPHS[s[i]];
      if (!gl) continue;
      for (var p = 0; p < 15; p++) if (gl[p] === "#") g.fillRect(x + i * 4 + (p % 3), y + ((p / 3) | 0), 1, 1);
    }
  }

  // ---------------------------------------------------------------- sprites
  var WALKER = [
    ["..HHHH..", ".HHHHHH.", ".HSSSSH.", ".SESSES.", "..SSSS..", ".BBBBBB.", "SBBBBBBS", ".BBbbBB.", ".LL..LL.", ".FF..FF."],
    ["..HHHH..", ".HHHHHH.", ".HSSSSH.", ".SESSES.", "..SSSS..", ".BBBBBB.", "SBBBBBBS", ".BBbbBB.", "..LLLL..", "..FF.FF."],
    ["..HHHH..", ".HHHHHH.", ".HSSSSH.", ".SESSES.", "..SSSS..", ".BBBBBB.", "SBBBBBBS", ".BBbbBB.", ".LLLL...", ".FF.FF.."],
  ];
  // Every agent looks like itself: a look is picked from its id (hair style and color, skin, glasses or
  // a headset, a shirt print), while the shirt color keeps the role readable at a glance.
  var SKINS = ["#f1b98c", "#e0a476", "#c4875a", "#9a6239", "#6e4425"];
  var HAIRS = ["#1a1410", "#5a3a1e", "#e8c25a", "#b8462a", "#9a9aa8", "#ff7ab8", "#3fc9b5", "#f4ecd8"];
  var HEADS = {
    short: ["..HHHH..", ".HHHHHH.", ".HSSSSH."],
    tall: [".HHHHHH.", "HHHHHHHH", ".HSSSSH."],
    cap: ["..CCCC..", ".CCCCCCC", "..SSSS.."],
    long: ["..HHHH..", ".HHHHHH.", "HHSSSSHH"],
    bun: ["...HH...", ".HHHHHH.", ".HSSSSH."],
    bald: ["........", "..SSSS..", ".SSSSSS."],
  };
  var STYLES = Object.keys(HEADS);
  function hash(s) { var h = 2166136261; s = String(s); for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function lookOf(id) {
    var h = hash(id);
    return { style: STYLES[h % STYLES.length], hair: HAIRS[(h >>> 3) % HAIRS.length], skin: SKINS[(h >>> 6) % SKINS.length],
             gear: ["none", "none", "glasses", "headset", "shades"][(h >>> 9) % 5], print: ["solid", "stripe", "tie", "solid"][(h >>> 12) % 4] };
  }
  function framesFor(look) {
    return WALKER.map(function (fr) {
      var rows = fr.slice();
      var head = HEADS[look.style];
      rows[0] = head[0]; rows[1] = head[1]; rows[2] = head[2];
      if (look.style === "long") rows[3] = "HSESSESH", rows[4] = "H.SSSS.H";
      if (look.gear === "glasses") rows[3] = rows[3].slice(0, 1) + "GEGGEG" + rows[3].slice(7);
      if (look.gear === "shades") rows[3] = rows[3].slice(0, 1) + "KKSSKK" + rows[3].slice(7);
      if (look.gear === "headset") { rows[2] = "M" + rows[2].slice(1, 7) + "M"; rows[4] = rows[4].slice(0, 6) + "MM"; }
      if (look.print === "stripe") rows[6] = rows[6].replace(/B/g, function (c, i) { return i % 2 ? "b" : "B"; });
      if (look.print === "tie") rows[5] = rows[5].slice(0, 3) + "TT" + rows[5].slice(5), rows[6] = rows[6].slice(0, 3) + "TT" + rows[6].slice(5);
      return rows;
    });
  }
  var sheetCache = {};
  function walkerSheet(role, id) {
    var key = role + "|" + (id || "");
    if (sheetCache[key]) return sheetCache[key];
    var R = ROLE[role], look = id ? lookOf(id) : { style: "short", hair: R.hair, skin: C.skin, gear: "none", print: "solid" };
    if (role === "red" || role === "blue") {
      // the team cap stays; the seat shows in the outfit: CIO in a tie, analysts on headsets, the skeptic in glasses
      var seat = seatOf(id);
      look.style = "cap";
      look.print = { cio: "tie", pm: "tie", ir: "tie", trader: "stripe", exec: "stripe", compliance: "stripe" }[seat] || "solid";
      look.gear = seat.indexOf("analyst") === 0 || seat === "data" ? "headset"
        : seat === "skeptic" || seat === "quantdev" || seat.indexOf("researcher") === 0 ? "glasses"
        : seat === "riskmgr" ? "shades" : "none";
    }
    var map = { H: look.hair, S: look.skin, E: C.ink, B: R.body, b: shade(R.body), L: C.ink, F: "#000000",
                C: role === "red" || role === "blue" ? R.body : shade(R.body), G: C.metal, K: "#000000", M: C.metalDk, T: C.gold };
    var frames = framesFor(look);
    var cv = document.createElement("canvas");
    cv.width = 8 * frames.length; cv.height = 10;
    var g = cv.getContext("2d");
    frames.forEach(function (fr, f) {
      fr.forEach(function (row, y) {
        for (var x = 0; x < 8; x++) { var k = row[x]; if (map[k]) { g.fillStyle = map[k]; g.fillRect(f * 8 + x, y, 1, 1); } }
      });
    });
    sheetCache[key] = cv;
    return cv;
  }
  function shade(hex) {
    var n = parseInt(hex.slice(1), 16), r = (n >> 16) & 255, gg = (n >> 8) & 255, b = n & 255;
    return "rgb(" + ((r * 0.7) | 0) + "," + ((gg * 0.7) | 0) + "," + ((b * 0.7) | 0) + ")";
  }

  // ---------------------------------------------------------------- geometry (384 x 216)
  var W = 384, H = 216;
  var TOP = 22, BOTTOM = 188;
  var AISLE_X = 184, CORR_X = 252, GATE_X = 272, GATE_Y = 116, ROOM_X = 290;
  var DOOR_Y = 160;              // founder's door, bottom of the corridor
  var KIT_X = 330;
  var KITS = ["github", "googledocs", "alpaca", "koopa", "other"];
  var KIT_LABEL = { github: "GITHUB", googledocs: "DOCS", alpaca: "ALPACA", koopa: "TRADES", other: "OTHER" };
  // The toolbox sits on the floor, before the gate: Hermes's own tools (whoami, search, delegate, files)
  // are not Arcade calls, so nobody stops at the gate for them.
  var TB_X = 188, TB_Y = 176, TB_STAND = [AISLE_X, 165];
  // Arena: two rooms side by side, RED left and BLUE right, a wall between. Each room has its crew
  // in a row at the back, the lead (CIO or solo trader) in front, a trade kiosk on the outer wall and
  // the desk's dialogue box along the bottom.
  var ROOM_W = 190, ROOM_X0 = { red: 0, blue: W - 190 }, WALL_X = 190;
  var BOX = { red: [6, 120], blue: [W - 190 + 6, 120], w: 178, h: 66 };
  var KIOSK = { red: [4, 76], blue: [W - 14, 76] };          // terminal box, 10 x 16
  function kioskStand(team) { return team === "red" ? [KIOSK.red[0] + 14, KIOSK.red[1] + 6] : [KIOSK.blue[0] - 10, KIOSK.blue[1] + 6]; }
  // A founded company's shelves: up to four of its apps, then OTHER. The trading demo keeps its own.
  var companyKits = false;
  function setKits(apps) {
    var keys = [];
    (apps || []).forEach(function (a) { var k = String(a || "").toLowerCase().replace(/[^a-z0-9]/g, ""); if (k && keys.indexOf(k) < 0) keys.push(k); });
    if (!keys.length) return;
    keys = keys.slice(0, 4);
    KITS = keys.concat(["other"]); KIT_LABEL = { other: "OTHER" };
    keys.forEach(function (k, i) { KIT_LABEL[k] = String(apps.filter(function (a) { return String(a).toLowerCase().replace(/[^a-z0-9]/g, "") === k; })[0]).replace(/^(Google|Arcade)(?=[A-Z])/, "").toUpperCase().slice(0, 8); });
    companyKits = true;
  }
  function kitOf(e) {
    var t = String((e && (e.toolkit || e.tool)) || "").toLowerCase();
    if (companyKits) {
      var n = t.replace(/[^a-z0-9.]/g, "").split(".")[0];
      for (var i = 0; i < KITS.length - 1; i++) if (n === KITS[i]) return KITS[i];
      return "other";
    }
    if (t.indexOf("github") === 0) return "github";
    if (t.indexOf("google") === 0 || t.indexOf("docs") >= 0) return "googledocs";
    if (t.indexOf("alpaca") >= 0) return "alpaca";
    if (t.indexOf("koopa") >= 0 || t.indexOf("arena") >= 0) return "koopa";
    return "other";
  }
  function kitY(k) { return 36 + KITS.indexOf(k) * 30; }

  // ---------------------------------------------------------------- world state
  function makeWorld() {
    return {
      agents: {}, order: [], log: [], fx: [], coins: [], notes: [],
      gate: { lamp: null, t: 0, bar: 0 }, door: { lamp: null, t: 0, open: 0, ring: 0, waiting: 0 },
      kits: {}, book: null, firm: "", seq: 0, act: 0, clock: 0, ticker: "", tickerX: W, toolbox: 0, wrench: 0,
    };
  }

  function agentIdFor(e) {
    if (e.profile && e.profile !== "default") return e.profile;
    return e.via || e.role || "agent";
  }
  function displayRole(e) {
    var tm = /^(red|blue)-/.exec(String(e.profile || ""));
    if (tm) return tm[1];   // arena seats play for the team in their profile name, whatever job the policy gives them
    if (e.profile && e.profile !== "default") return roleOf(e.role);
    return roleOf(e.via || e.role);
  }

  function ensureAgent(world, e) {
    var id = agentIdFor(e);
    var a = world.agents[id];
    if (!a) {
      a = { id: id, role: displayRole(e), seat: seatOf(id), x: 0, y: 0, hx: 0, hy: 0, path: [], queue: [], busy: false,
            frame: 0, ft: 0, bubble: null, bt: 0, wait: 0, hold: null, flip: false, shake: 0, last: null,
            thinking: 0, thought: null, tht: 0, mind: 0 };
      world.agents[id] = a;
      world.order.push(id);
      layout(world);
      a.x = a.hx; a.y = a.hy;
    }
    return a;
  }

  var CORNER = { cos: [214, 150], cio: [214, 50], reporter: [214, 100] };
  function layout(world) {
    var pit = [], corners = {};
    world.arenaMode = false;
    world.order.forEach(function (id) {
      var a = world.agents[id];
      if (CORNER[a.role] && !corners[a.role]) { corners[a.role] = a; return; }
      pit.push(a);
    });
    Object.keys(corners).forEach(function (r) { var a = corners[r]; a.hx = CORNER[r][0]; a.hy = CORNER[r][1]; a.corner = true; });
    // Arena teams get their own ends of the pit when they are all that is on the floor.
    if (pit.length && pit.every(function (a) { return a.role === "red" || a.role === "blue"; })) {
      ["red", "blue"].forEach(function (team) {
        var x0 = ROOM_X0[team], mine = pit.filter(function (a) { return a.role === team; });
        var crew = mine.filter(function (a) { return !isLead(a); }).sort(function (p, q) { return p.id < q.id ? -1 : 1; });
        var leads = mine.filter(isLead);
        // a big crew sits in two rows; the lead (the one who trades) sits in front
        var rows = crew.length > 4 ? 2 : 1, per = Math.ceil(crew.length / rows);
        crew.forEach(function (a, i) {
          var r = Math.floor(i / per), c = i % per, n = Math.min(per, crew.length - r * per);
          a.hx = x0 + Math.round((c + 1) * ROOM_W / (n + 1)) - 4; a.hy = rows === 2 ? 40 + r * 26 : 44; a.corner = false;
        });
        leads.forEach(function (a, i) { a.hx = x0 + Math.round((i + 1) * ROOM_W / (leads.length + 1)) - 4; a.hy = crew.length ? (rows === 2 ? 94 : 80) : 62; a.corner = false; });
      });
      world.cell = 30; world.pitN = pit.length; world.arenaMode = true;
      world.order.forEach(function (id) { var a = world.agents[id]; if (!a.busy && !a.path.length && !a.hold && !a.queue.length) { a.x = a.hx; a.y = a.hy; } });
      return;
    }
    var rank = { red: -2, blue: -1, analyst: 0, skeptic: 1, risk: 2, cio: 3, reporter: 4, cos: 5, other: 6 };
    pit.sort(function (p, q) { return (rank[p.role] - rank[q.role]) || (p.id < q.id ? -1 : 1); });
    var x0 = 12, y0 = 40, w = AISLE_X - 18 - x0, hgt = BOTTOM - 14 - y0;
    var n = Math.max(1, pit.length);
    var cell = 30;
    while (cell > 12) {
      var cols = Math.max(1, Math.floor(w / cell)), rows = 0, cur = null, used = 0;
      pit.forEach(function (a) { if (a.role !== cur || used >= cols) { rows++; used = 0; cur = a.role; } used++; });
      if (rows * Math.round(cell * 0.78) <= hgt) break;
      cell -= 1;
    }
    var colsN = Math.max(1, Math.floor(w / cell)), rowH = Math.round(cell * 0.78), r = -1, c = colsN, role = null;
    pit.forEach(function (a) {
      if (a.role !== role || c >= colsN) { r++; c = 0; role = a.role; }
      a.hx = x0 + c * cell + ((cell - 8) >> 1);
      a.hy = y0 + r * rowH;
      a.corner = false;
      c++;
    });
    world.cell = cell;
    world.pitN = n;
    // Idle workers go straight to their (possibly new) desk; busy ones walk home there after the trip.
    world.order.forEach(function (id) {
      var a = world.agents[id];
      if (!a.busy && !a.path.length && !a.hold && !a.queue.length) { a.x = a.hx; a.y = a.hy; }
    });
  }

  // ---------------------------------------------------------------- trips
  function routeTo(a, pts) { a.path = a.path.concat(pts.map(function (p) { return { x: p[0], y: p[1], act: p[2] }; })); }
  function toCorridor(a) { return [[AISLE_X, a.hy], [CORR_X, a.hy]]; }
  function home(a) { return [[CORR_X, a.y < 0 ? a.hy : a.hy], [AISLE_X, a.hy], [a.hx, a.hy]]; }

  function planTrip(world, e) {
    var a = ensureAgent(world, e);
    a.last = e;
    var kit = kitOf(e), d = e.decision, tool = shortTool(e.tool);
    var steps = [];
    var atDoor = a.hold && e.key && a.hold === e.key;
    if (!atDoor) {
      steps = steps.concat(toCorridor(a));
      if (d === "approved" || (d === "denied" && e.approver)) {
        steps.push([CORR_X, GATE_Y, { gate: "amber", say: tool }]);
        steps.push([CORR_X, DOOR_Y - 12, { ring: true }]);
      } else {
        steps.push([GATE_X - 10, GATE_Y]);
      }
    }
    var bubble = { tool: tool };
    if (d === "approved") {
      steps.push([CORR_X, DOOR_Y - 12, { ring: true, wait: 1.2 }]);
      steps.push([CORR_X, DOOR_Y - 12, { door: "green", say: approverWord(e), wait: 1.2 }]);
      steps = steps.concat([[CORR_X, GATE_Y], [GATE_X + 6, GATE_Y, { gate: "green" }], [ROOM_X + 4, kitY(kit) + 12],
                            [KIT_X - 6, kitY(kit) + 12, { kit: kit, enter: true, fill: isFill(e), wait: 0.5 }]]);
      steps.push([ROOM_X + 4, kitY(kit) + 12]); steps.push([GATE_X + 6, GATE_Y]);
    } else if (d === "denied" && e.approver) {
      steps.push([CORR_X, DOOR_Y - 12, { ring: true, wait: 1.2 }]);
      steps.push([CORR_X, DOOR_Y - 12, { door: "red", say: approverWord(e), bonk: true, wait: 1.6 }]);
    } else if (d === "denied" || d === "needs_human") {
      steps.push([GATE_X - 10, GATE_Y, { gate: "red", say: "DENIED", reason: e.reason, bonk: true, wait: 1.4 }]);
    } else if (d === "handed_back") {
      steps.push([GATE_X - 10, GATE_Y, { gate: "amber", say: "HANDOFF", note: true, wait: 0.9 }]);
    } else {
      steps = steps.concat([[GATE_X + 6, GATE_Y, { gate: "green", say: tool }], [ROOM_X + 4, kitY(kit) + 12],
                            [KIT_X - 6, kitY(kit) + 12, { kit: kit, enter: true, err: e.outcome === "error", auth: e.outcome === "authorization_required", wait: 0.35 }],
                            [ROOM_X + 4, kitY(kit) + 12], [GATE_X + 6, GATE_Y]]);
    }
    steps = steps.concat([[CORR_X, GATE_Y], [CORR_X, a.hy], [AISLE_X, a.hy], [a.hx, a.hy, { done: true }]]);
    if (atDoor) a.hold = null;
    a.queue.push({ steps: steps, e: e, bubble: bubble });
  }

  // Arena trips stay inside the team's room: a market read lights the desk screen, a desk-talk line
  // flies a memo to the lead, and an order is a walk to the kiosk (coins on a fill, a bonk on a refusal
  // or on the Arcade gate's denial).
  function planArenaTrip(world, e) {
    var a = ensureAgent(world, e), tool = String(e.tool || "").toLowerCase(), d = e.decision, team = a.role;
    a.last = e;
    var denied = d === "denied" || d === "needs_human";
    var borrow = tool.indexOf("arena_borrow") >= 0;
    // the control team's calls carry what Arcade would have said; a would-be denial that ran anyway is a breach
    var breach = !!e.breach;
    if (tool.indexOf("arena_market") >= 0 && !denied && !breach) { a.glance = 1.5; return; }
    if ((tool.indexOf("arena_history") >= 0 || tool.indexOf("arena_thesis") >= 0) && !denied && !breach) {
      a.glance = 1.5; if (tool.indexOf("thesis") >= 0) say(a, "THESIS SET"); return;
    }
    if (tool.indexOf("arena_") !== 0 && tool.indexOf("arena_") < 0) {
      // an Arcade catalog tool (E2B, news, docs): worked at the desk, named in a bubble
      var word = /e2b|runcode/.test(tool) ? "CODE" : /news/.test(tool) ? "NEWS" : /search/.test(tool) ? "SEARCH" : /docs/.test(tool) ? "LP LETTER" : localTool(e.tool);
      a.glance = 2;
      if (denied) { say(a, "DENIED", e.reason); a.shake = 0.35; beep("deny"); }
      else say(a, e.outcome === "error" ? word + " ERROR" : word);
      return;
    }
    if (tool.indexOf("arena_note") >= 0 && !denied && !breach) { act(world, a, { memo: true }); return; }
    var st = kioskStand(team), steps = [[a.hx, st[1]], [st[0], st[1]]];
    if (denied) steps[1].push({ kiosk: team, gateLamp: true, say: "DENIED", reason: e.reason, bonk: true, wait: 1.8 });
    else if (e.outcome === "error") steps[1].push({ kiosk: team, say: "REFUSED", bonk: true, wait: 1.0 });
    else if (breach) steps[1].push({ kiosk: team, alarm: true, say: borrow ? "BREACH: BORROWED" : "BREACH", reason: e.reason, fill: true, wait: 1.8 });
    else steps[1].push({ kiosk: team, say: borrow ? "BORROWED" : "FILLED", fill: true, wait: 0.6 });
    steps.push([a.hx, st[1]]); steps.push([a.hx, a.hy, { done: true }]);
    a.queue.push({ steps: steps, e: e, bubble: {} });
  }

  function holdAtDoor(world, w) {
    var a = ensureAgent(world, w);
    if (a.hold === w.key || a.busy || a.queue.length) return;
    a.hold = w.key;
    a.path = [];
    routeTo(a, toCorridor(a).concat([[CORR_X, GATE_Y, { gate: "amber", say: shortTool(w.tool) }], [CORR_X, DOOR_Y - 12, { ring: true, holding: true }]]));
    a.busy = true;
  }

  function localTool(t) {
    t = String(t || "tool");
    if (t === "delegate_task") return "DELEGATE";
    return t.replace(/^arcade_/, "").replace(/[_.]+/g, " ").toUpperCase().slice(0, 18);
  }
  function planToolbox(world, e) {
    var a = ensureAgent(world, e), name = localTool(e.tool);
    // A burst of local calls should not queue a parade: one trip, the rest only flash the box.
    if (a.hold || a.queue.length >= 1) { world.toolbox = 0.5; if (!a.bubble) say(a, name); return; }
    var steps = [[AISLE_X, a.hy], [TB_STAND[0], TB_STAND[1]], [TB_STAND[0] + 2, TB_STAND[1], { toolbox: true, say: name, wait: 0.45 }],
                 [AISLE_X, a.hy], [a.hx, a.hy, { done: true }]];
    a.queue.push({ steps: steps, e: e, bubble: { tool: name } });
  }

  function isFill(e) { return e.outcome === "ok" && /koopa_execute|SubmitOrder|arena_trade/i.test(e.tool || ""); }
  function approverWord(e) {
    var ap = e.approver || {};
    if (e.decision === "approved") return ap.decided_by === "human" ? "YES" : "ALLOWLIST";
    if (ap.decided_by === "nobody") return "TIMEOUT";
    return "NO";
  }
  function shortTool(t) {
    t = String(t || "?");
    var dot = t.lastIndexOf(".");
    t = dot >= 0 ? t.slice(dot + 1) : t;
    return t.replace(/^koopa_/, "KOOPA ").replace(/([a-z])([A-Z])/g, "$1 $2").toUpperCase().slice(0, 18);
  }

  // ---------------------------------------------------------------- sound (muted by default)
  var audio = { on: false, ctx: null };
  function beep(kind) {
    if (!audio.on) return;
    try {
      audio.ctx = audio.ctx || new (window.AudioContext || window.webkitAudioContext)();
      var seq = { ok: [[880, 0.05]], deny: [[140, 0.18], [110, 0.18]], ring: [[1320, 0.04], [0, 0.03], [1320, 0.04]],
                  yes: [[660, 0.07], [880, 0.07], [1320, 0.12]], no: [[330, 0.1], [220, 0.2]], coin: [[988, 0.06], [1319, 0.14]],
                  note: [[520, 0.05], [780, 0.08]] }[kind] || [];
      var t = audio.ctx.currentTime;
      seq.forEach(function (s) {
        if (s[0]) {
          var o = audio.ctx.createOscillator(), gn = audio.ctx.createGain();
          o.type = "square"; o.frequency.value = s[0]; gn.gain.value = 0.04;
          o.connect(gn); gn.connect(audio.ctx.destination); o.start(t); o.stop(t + s[1]);
        }
        t += s[1];
      });
    } catch (err) { /* sound is a nicety */ }
  }

  // ---------------------------------------------------------------- simulation step
  function step(world, dt) {
    world.clock += dt;
    var speed = 70; // px per second at 1x
    world.order.forEach(function (id) {
      var a = world.agents[id];
      if (!a.busy && a.queue.length && !a.hold) {
        var trip = a.queue.shift();
        a.busy = true;
        routeTo(a, trip.steps);
      } else if (a.hold && a.queue.length && a.queue[0].e.key === a.hold) {
        var t2 = a.queue.shift();
        a.path = [];
        routeTo(a, t2.steps);
        a.hold = null;
        a.wait = 0;
      }
      if (a.wait > 0) { a.wait -= dt; return; }
      if (!a.path.length) { a.busy = !!a.hold; return; }
      var p = a.path[0], dx = p.x - a.x, dy = p.y - a.y, dist = Math.abs(dx) + Math.abs(dy);
      var mv = speed * dt;
      if (dist <= mv) {
        a.x = p.x; a.y = p.y;
        a.path.shift();
        if (p.act) act(world, a, p.act);
      } else {
        if (Math.abs(dx) > 0.01) { var sx = Math.sign(dx) * Math.min(Math.abs(dx), mv); a.x += sx; a.flip = dx < 0; }
        else a.y += Math.sign(dy) * Math.min(Math.abs(dy), mv);
        a.ft += dt;
        if (a.ft > 0.12) { a.ft = 0; a.frame = a.frame === 1 ? 2 : 1; }
      }
      if (!a.path.length) a.frame = 0;
    });
    ["gate", "door"].forEach(function (k) { var o = world[k]; if (o.t > 0) { o.t -= dt; if (o.t <= 0) o.lamp = null; } });
    world.door.ring = Math.max(0, world.door.ring - dt);
    world.door.open += ((world.door.lamp === "green" ? 1 : 0) - world.door.open) * Math.min(1, dt * 6);
    world.gate.bar += ((world.gate.lamp === "green" ? 1 : 0) - world.gate.bar) * Math.min(1, dt * 10);
    world.door.waiting = world.order.filter(function (id) { return world.agents[id].hold; }).length;
    if (world.door.waiting) world.door.ring = 0.5;
    Object.keys(world.kits).forEach(function (k) { world.kits[k] = Math.max(0, world.kits[k] - dt); });
    ["kiosk", "alarm", "shield"].forEach(function (f) { if (world[f]) Object.keys(world[f]).forEach(function (k) { world[f][k] = Math.max(0, world[f][k] - dt); }); });
    world.order.forEach(function (id) {
      var a = world.agents[id];
      if (a.bt > 0) { a.bt -= dt; if (a.bt <= 0) a.bubble = null; }
      if (a.shake > 0) a.shake -= dt;
      if (a.glance > 0) a.glance -= dt;
      if (a.thinking > 0) { a.thinking -= dt; a.mind = world.clock; }
      if (a.tht > 0) { a.tht -= dt; if (a.tht <= 0) a.thought = null; }
    });
    world.toolbox = Math.max(0, world.toolbox - dt); world.wrench = Math.max(0, world.wrench - dt);
    world.coins = world.coins.filter(function (c) { c.vy += 260 * dt; c.x += c.vx * dt; c.y += c.vy * dt; c.t -= dt; if (c.y > c.floor) { c.y = c.floor; c.vy *= -0.45; c.vx *= 0.7; } return c.t > 0; });
    world.notes = world.notes.filter(function (n) { n.t += dt * 1.4; return n.t < 1; });
    world.tickerX -= dt * 28;
    if (world.tickerX < -textW(world.ticker) - 20) world.tickerX = W;
  }

  function act(world, a, s) {
    if (s.say) say(a, s.say, s.reason);
    if (s.gate) { world.gate.lamp = s.gate; world.gate.t = 1.1; beep(s.gate === "red" ? "deny" : s.gate === "green" ? "ok" : "note"); }
    if (s.ring) { world.door.ring = 1.2; beep("ring"); }
    if (s.door) { world.door.lamp = s.door; world.door.t = 1.6 * (world.mode === "replay" ? (world.speed || 1) : 1); beep(s.door === "green" ? "yes" : "no"); }
    if (s.bonk) a.shake = 0.35;
    if (s.kit) { world.kits[s.kit] = 0.6; if (s.err) say(a, "ERROR"); if (s.auth) say(a, "NEEDS AUTH"); }
    if (s.alarm) { world.alarm = world.alarm || {}; world.alarm[a.role] = 2.2; beep("deny"); }
    if (s.gateLamp) { world.shield = world.shield || {}; world.shield[a.role] = 1.8; }
    if (s.kiosk) {
      world.kiosk = world.kiosk || {}; world.kiosk[s.kiosk] = 0.9;
      if (s.fill) { burst(world, KIOSK[s.kiosk][0] + 5, KIOSK[s.kiosk][1] + 4); beep("coin"); }
    } else if (s.fill) { burst(world, KIT_X, kitY("koopa") + 8); beep("coin"); }
    if (s.memo) {
      var lead = world.order.map(function (id) { return world.agents[id]; }).filter(function (b) { return b.role === a.role && isLead(b); })[0];
      if (lead && lead !== a) world.notes.push({ x0: a.x, y0: a.y, x1: lead.hx + 4, y1: lead.hy, t: 0 });
    }
    if (s.toolbox) { world.toolbox = 0.9; world.wrench = 0.9; beep("ok"); }
    if (s.note) {
      var cos = world.order.map(function (id) { return world.agents[id]; }).filter(function (b) { return b.role === "cos"; })[0];
      world.notes.push({ x0: a.x, y0: a.y, x1: cos ? cos.hx : CORNER.cos[0], y1: cos ? cos.hy : CORNER.cos[1], t: 0 });
    }
    if (s.wait) a.wait = s.wait * ((s.door || s.ring) && world.mode === "replay" ? (world.speed || 1) : 1);
    if (s.holding) { a.wait = 0; }
    if (s.done) {
      // The desks may have been re-laid out while this agent was away: walk on to the current one.
      if (Math.abs(a.x - a.hx) > 0.5 || Math.abs(a.y - a.hy) > 0.5) routeTo(a, world.arenaMode ? [[a.x, a.hy], [a.hx, a.hy, { done: true }]] : [[AISLE_X, a.y], [AISLE_X, a.hy], [a.hx, a.hy, { done: true }]]);
      else a.busy = false;
    }
  }
  function say(a, word, reason) { a.bubble = { word: String(word || "").toUpperCase().slice(0, 18), reason: reason ? String(reason).toUpperCase() : null }; a.bt = (reason ? 3.2 : 1.5) * (/^(YES|NO|TIMEOUT|ALLOWLIST)$/.test(a.bubble.word) ? sayScale : 1); }
  var sayScale = 1;
  function burst(world, x, y) {
    for (var i = 0; i < 14; i++) world.coins.push({ x: x, y: y, vx: (Math.random() - 0.5) * 120, vy: -60 - Math.random() * 90, t: 1.6 + Math.random() * 0.6, floor: y + 14 + Math.random() * 6 });
  }

  // ---------------------------------------------------------------- drawing
  function draw(g, world, ui) {
    g.fillStyle = C.night; g.fillRect(0, 0, W, H);
    // floor checker
    for (var y = TOP; y < BOTTOM; y += 8) for (var x = 0; x < W; x += 8) { g.fillStyle = ((x + y) / 8) % 2 ? C.floorA : C.floorB; g.fillRect(x, y, 8, 8); }
    // back wall + data wall
    g.fillStyle = C.wall; g.fillRect(0, TOP, ROOM_X - 4, 14); g.fillStyle = C.wallHi; g.fillRect(0, TOP + 13, ROOM_X - 4, 1);
    for (var s = 0; s < 9; s++) {
      var sx = 8 + s * 28;
      g.fillStyle = C.ink; g.fillRect(sx, TOP + 2, 22, 10); g.fillStyle = C.screenDk; g.fillRect(sx + 1, TOP + 3, 20, 8);
      g.fillStyle = C.screen;
      for (var k = 0; k < 6; k++) { var hh = 1 + (((Math.sin(world.clock * 1.3 + s * 1.7 + k) + 1) * 3) | 0); g.fillRect(sx + 2 + k * 3, TOP + 10 - hh, 2, hh); }
    }
    if (world.arenaMode) { drawArenaRooms(g, world); }
    else {
    // the right-hand rooms: toolkit doors behind the gate
    g.fillStyle = C.wall; g.fillRect(ROOM_X - 4, TOP, W - ROOM_X + 4, BOTTOM - TOP);
    for (var yy = TOP; yy < BOTTOM; yy += 8) for (var xx = ROOM_X; xx < W; xx += 8) { g.fillStyle = ((xx + yy) / 8) % 2 ? "#221d3d" : "#1f1a38"; g.fillRect(xx, yy, 8, 8); }
    KITS.forEach(function (kname) {
      var ky = kitY(kname), lit = world.kits[kname] > 0;
      g.fillStyle = C.trim; g.fillRect(KIT_X - 2, ky - 2, 44, 26);
      g.fillStyle = lit ? "#3b3270" : C.ink; g.fillRect(KIT_X, ky, 40, 22);
      g.fillStyle = lit ? C.amber : C.metalDk; g.fillRect(KIT_X + 33, ky + 11, 2, 2);
      text(g, KIT_LABEL[kname], KIT_X + 20 - (textW(KIT_LABEL[kname]) >> 1), ky + 4, lit ? C.gold : C.dim);
    });
    // corridor and the gate
    g.fillStyle = "#3a3366"; g.fillRect(CORR_X - 6, TOP + 14, 14, BOTTOM - TOP - 14);
    drawGate(g, world);
    drawDoor(g, world);
    }
    // desks
    world.order.forEach(function (id) { drawDesk(g, world, world.agents[id]); });
    drawToolbox(g, world);
    // notes flying to the chief of staff
    world.notes.forEach(function (n) {
      var t = n.t, x = n.x0 + (n.x1 - n.x0) * t, y = n.y0 + (n.y1 - n.y0) * t - Math.sin(t * Math.PI) * 30;
      g.fillStyle = C.cream; g.fillRect(x | 0, y | 0, 5, 4); g.fillStyle = C.dim; g.fillRect((x | 0) + 1, (y | 0) + 1, 3, 1);
    });
    // agents sorted by y
    var list = world.order.map(function (id) { return world.agents[id]; }).sort(function (p, q) { return p.y - q.y; });
    list.forEach(function (a) { drawAgent(g, a, ui.hover === a.id); });
    world.coins.forEach(function (c) { g.fillStyle = C.goldDk; g.fillRect(c.x | 0, c.y | 0, 3, 3); g.fillStyle = C.gold; g.fillRect(c.x | 0, c.y | 0, 2, 2); });
    // Bubbles by priority: verdicts (denied, the founder's yes/no, handoffs) always show; plain tool
    // names only for the two freshest, so a 100-agent stampede stays readable.
    var LOUD = { DENIED: 1, NO: 1, YES: 1, TIMEOUT: 1, HANDOFF: 1, ERROR: 1, "NEEDS AUTH": 1, ALLOWLIST: 1 };
    var withB = list.filter(function (a) { return a.bubble; });
    var loud = withB.filter(function (a) { return LOUD[a.bubble.word]; }).sort(function (p, q) { return q.bt - p.bt; }).slice(0, 3);
    var quiet = withB.filter(function (a) { return !LOUD[a.bubble.word]; }).sort(function (p, q) { return q.bt - p.bt; }).slice(0, 2);
    // Thought clouds: what an agent is chewing on. Speech wins when both want the same head.
    worldRef = world;
    // The terminal floor renders text at half-block resolution: clouds and tool names turn to noise
    // there, so it keeps only the verdicts (DENIED, YES, NO...). The browser floor shows everything.
    if (ui.term) quiet = [];
    else layoutThoughts(list, quiet.concat(loud)).forEach(function (p) { drawThought(g, world, p.a, p.r); });
    if (world.arenaMode) { drawDialogue(g, world, "red"); drawDialogue(g, world, "blue"); }
    // only think when it pays: a sleeping desk wears its Zs
    if (world.arenaMode) ["red", "blue"].forEach(function (team) {
      var tt = ((world.arena || {}).teams || {})[team] || {};
      if (tt.awake !== false) return;
      list.forEach(function (a) {
        if (a.role !== team || a.thinking > 0 || a.busy) return;
        var ph = (world.clock * 1.5 + hash(a.id) % 7) % 3;
        text(g, ph < 1 ? "z" : ph < 2 ? "zz" : "zzz", Math.round(a.x) + 6, Math.round(a.y) - 6 - Math.round(ph * 2), "#8f86b3", null, true);
      });
    });
    quiet.concat(loud).forEach(function (a) { drawBubble(g, a); });
    drawTicker(g, world, ui);
    drawBottom(g, world, ui);
    if (ui.hover && world.agents[ui.hover]) drawCard(g, world.agents[ui.hover]);
  }

  function drawGate(g, world) {
    var lamp = world.gate.lamp, top = GATE_Y - 22, bot = GATE_Y + 12;
    g.fillStyle = C.metalDk; g.fillRect(GATE_X - 2, TOP + 14, 5, top - TOP - 14); g.fillRect(GATE_X - 2, bot + 2, 5, BOTTOM - bot - 2);
    g.fillStyle = C.metal; g.fillRect(GATE_X - 1, top - 4, 3, 4); g.fillRect(GATE_X - 1, bot, 3, 4);
    // lamp housing
    g.fillStyle = C.ink; g.fillRect(GATE_X - 4, top - 12, 9, 8);
    g.fillStyle = lamp === "green" ? C.green : lamp === "red" ? C.red : lamp === "amber" ? C.amber : "#3a2d2d";
    g.fillRect(GATE_X - 3, top - 11, 7, 6);
    // bars slide up when the lamp is green
    var lift = Math.round(world.gate.bar * 20);
    g.fillStyle = lamp === "red" ? "#b02a3a" : C.metal;
    for (var i = 0; i < 4; i++) g.fillRect(GATE_X - 1, top + i * 8 - lift, 3, 6);
    text(g, "GATE", GATE_X - 7, top - 19, C.dim);
  }

  function drawDoor(g, world) {
    var dx = CORR_X - 10, dy = DOOR_Y - 6, open = world.door.open, lamp = world.door.lamp;
    g.fillStyle = C.trim; g.fillRect(dx - 2, dy - 2, 24, 20);
    g.fillStyle = C.ink; g.fillRect(dx, dy, 20, 18);
    var panel = Math.round(20 * (1 - open));
    g.fillStyle = lamp === "red" ? "#7a2232" : C.desk; g.fillRect(dx, dy, panel, 18);
    if (panel > 3) { g.fillStyle = C.gold; g.fillRect(dx + panel - 3, dy + 9, 1, 2); }
    g.fillStyle = lamp === "green" ? C.green : lamp === "red" ? C.red : world.door.waiting ? C.amber : "#3a2d2d";
    g.fillRect(dx + 8, dy - 6, 4, 3);
    text(g, "FOUNDER", dx - 4, dy + 21, C.cream, C.ink);
    // the phone on a little stand, shaking while it rings
    var ring = world.door.ring > 0, j = ring ? ((world.clock * 30) | 0) % 2 : 0;
    var px = dx + 27 + j, py = dy + 3;
    g.fillStyle = C.ink; g.fillRect(px - 1, py - 1, 8, 13);
    g.fillStyle = ring ? C.screen : C.metalDk; g.fillRect(px, py, 6, 11);
    g.fillStyle = C.ink; g.fillRect(px + 2, py + 9, 2, 1);
    if (ring) {
      g.fillStyle = C.amber;
      g.fillRect(px + 8, py + 1, 1, 3); g.fillRect(px + 10, py, 1, 5); g.fillRect(px - 3, py + 1, 1, 3);
      if (world.door.waiting) text(g, world.door.waiting + " WAITING", px - 2, py - 8, C.amber, C.ink);
    }
  }

  var TEAM_RUG = { red: ["#4a1420", "#e8323f"], blue: ["#12244f", "#2f7dff"] };
  function drawArenaRooms(g, world) {
    // each room's floor takes a faint wash of its team, so the halves read before any sprite does
    g.fillStyle = "rgba(232,50,63,0.10)"; g.fillRect(0, TOP + 14, WALL_X, BOTTOM - TOP - 14);
    g.fillStyle = "rgba(47,125,255,0.10)"; g.fillRect(WALL_X + 4, TOP + 14, W - WALL_X - 4, BOTTOM - TOP - 14);
    // back wall runs the full width, each room with its own six screens
    g.fillStyle = C.wall; g.fillRect(0, TOP, W, 14); g.fillStyle = C.wallHi; g.fillRect(0, TOP + 13, W, 1);
    ["red", "blue"].forEach(function (team, ti) {
      for (var s = 0; s < 6; s++) {
        var sx = ROOM_X0[team] + 8 + s * 30;
        g.fillStyle = C.ink; g.fillRect(sx, TOP + 2, 22, 10); g.fillStyle = C.screenDk; g.fillRect(sx + 1, TOP + 3, 20, 8);
        g.fillStyle = C.screen;
        for (var k = 0; k < 6; k++) { var hh = 1 + (((Math.sin(world.clock * 1.3 + (s + ti * 6) * 1.7 + k) + 1) * 3) | 0); g.fillRect(sx + 2 + k * 3, TOP + 10 - hh, 2, hh); }
      }
    });
    // the wall between the rooms
    g.fillStyle = C.wall; g.fillRect(WALL_X, TOP, 4, BOTTOM - TOP);
    g.fillStyle = C.wallHi; g.fillRect(WALL_X, TOP, 1, BOTTOM - TOP);
    // a breach in the control room flashes the whole floor of that room
    var sbt = (world.arena || {}).teams || {};
    ["red", "blue"].forEach(function (team) {
      var al = (world.alarm || {})[team] || 0;
      if (al > 0 && ((world.clock * 6) | 0) % 2) { g.fillStyle = "rgba(255,40,60,0.22)"; g.fillRect(ROOM_X0[team] + (team === "blue" ? 4 : 0), TOP + 14, ROOM_W - 4, BOTTOM - TOP - 14); }
    });
    // trade kiosks on the outer walls; the governed desk's kiosk stands behind the Arcade gate
    ["red", "blue"].forEach(function (team) {
      var gate = (sbt[team] || {}).gate;
      if (gate === "arcade") {
        var k0 = KIOSK[team], gx = team === "red" ? k0[0] + 12 : k0[0] - 4, sh = (world.shield || {})[team] > 0;
        g.fillStyle = sh ? C.red : C.gold; g.fillRect(gx, k0[1] - 2, 2, 22);
        g.fillStyle = sh ? "#ff9aa5" : C.goldDk; g.fillRect(gx, k0[1] - 4, 2, 2);
      }
      var k = KIOSK[team], lit = (world.kiosk && world.kiosk[team]) > 0, ink = TEAM_INK[team];
      g.fillStyle = C.trim; g.fillRect(k[0] - 1, k[1] - 1, 12, 18);
      g.fillStyle = C.ink; g.fillRect(k[0], k[1], 10, 16);
      g.fillStyle = lit ? ink : TEAM_DEEP[team]; g.fillRect(k[0] + 1, k[1] + 1, 8, 6);
      g.fillStyle = C.metalDk; g.fillRect(k[0] + 2, k[1] + 9, 6, 1); g.fillRect(k[0] + 2, k[1] + 11, 6, 1);
      var lab = "TRADE", lx = team === "red" ? k[0] : k[0] + 10 - textW(lab);
      text(g, lab, lx, k[1] - 8, lit ? ink : C.dim);
    });
  }
  function drawDesk(g, world, a) {
    var rug = TEAM_RUG[a.role];
    if (rug) {
      g.fillStyle = rug[1]; g.fillRect(a.hx - 6, a.hy - 4, 20, 26);
      g.fillStyle = rug[0]; g.fillRect(a.hx - 5, a.hy - 3, 18, 24);
      for (var ry = a.hy - 1; ry < a.hy + 19; ry += 4) { g.fillStyle = rug[1]; g.fillRect(a.hx - 3, ry, 14, 1); }
    }
    var big = a.corner || world.cell >= 22;
    var w = big ? 16 : 10, x = Math.round(a.hx + 4 - w / 2), y = a.hy + 9;
    g.fillStyle = C.deskEdge; g.fillRect(x, y + 2, w, big ? 4 : 2);
    g.fillStyle = C.deskTop; g.fillRect(x, y, w, 2);
    if (big) { g.fillStyle = C.ink; g.fillRect(x + w - 6, y - 5, 5, 5); g.fillStyle = C.screen; g.fillRect(x + w - 5, y - 4, 3, 3); }
    if (a.corner) text(g, ROLE[a.role].tag, a.hx + 4 - (textW(ROLE[a.role].tag) >> 1), y + 8, C.dim);
    else if (rug) {
      var solo = a.seat === "trader" || !a.seat;
      var tt = solo ? ROLE[a.role].tag + (a.model ? " " + modelWord(a.model) : "") : seatTag(a);
      text(g, tt, a.hx + 4 - (textW(tt) >> 1), y + 12, ROLE[a.role].body);
      if (a.glance > 0) { g.fillStyle = TEAM_INK[a.role]; g.fillRect(x + w - 5, y - 4, 3, 3); }   // reading the market
    }
    else if (world.cell >= 14) { var tg = (ROLE[a.role].dyn || companyKits) ? ROLE[a.role].tag : nameTag(a.id); text(g, tg, a.hx + 4 - (textW(tg) >> 1), y + 4, ROLE[a.role].body); }
  }

  function drawAgent(g, a, hovered) {
    var sh = walkerSheet(a.role, a.id), jx = a.shake > 0 ? (((a.shake * 40) | 0) % 2 ? 1 : -1) : 0;
    var x = Math.round(a.x) + jx, y = Math.round(a.y);
    g.fillStyle = "rgba(0,0,0,0.35)"; g.fillRect(x + 1, y + 9, 6, 2);
    if (a.flip) { g.save(); g.translate(x + 8, y); g.scale(-1, 1); g.drawImage(sh, a.frame * 8, 0, 8, 10, 0, 0, 8, 10); g.restore(); }
    else g.drawImage(sh, a.frame * 8, 0, 8, 10, x, y, 8, 10);
    if (hovered) { g.fillStyle = C.cream; g.fillRect(x + 3, y - 3, 2, 1); }
  }

  function drawBubble(g, a) {
    var b = a.bubble, lines = [b.word];
    if (b.reason) wrap(b.reason, 22).slice(0, 3).forEach(function (l) { lines.push(l); });
    var w = Math.max.apply(null, lines.map(textW)) + 6, hgt = lines.length * 7 + 4;
    var x = Math.round(a.x + 4 - w / 2), y = Math.round(a.y) - hgt - 4;
    x = Math.max(2, Math.min(W - w - 2, x)); y = Math.max(TOP + 1, y);
    g.fillStyle = C.ink; g.fillRect(x - 1, y - 1, w + 2, hgt + 2);
    g.fillStyle = C.cream; g.fillRect(x, y, w, hgt);
    g.fillRect(Math.round(a.x) + 3, y + hgt, 2, 2);
    lines.forEach(function (l, i) { text(g, l, x + 3, y + 3 + i * 7, i === 0 ? (b.word === "DENIED" || b.word === "NO" || b.word === "TIMEOUT" ? C.red : b.word === "YES" ? "#1e8a4e" : C.ink) : C.ink); });
  }
  function drawToolbox(g, world) {
    if (world.arenaMode) return;   // traders have no local tools; the floor below the desks is theirs
    var x = TB_X, y = TB_Y, open = world.toolbox > 0, lift = open ? 3 : 0;
    g.fillStyle = "rgba(0,0,0,0.35)"; g.fillRect(x + 1, y + 9, 18, 2);
    // body
    g.fillStyle = "#8f1d2c"; g.fillRect(x, y + 3, 18, 7);
    g.fillStyle = "#d8344a"; g.fillRect(x, y + 3, 18, 5);
    g.fillStyle = C.gold; g.fillRect(x + 8, y + 5, 2, 2);
    // lid and handle, lifted while someone is inside
    g.fillStyle = "#b52638"; g.fillRect(x - 1, y + 1 - lift, 20, 2);
    g.fillStyle = C.ink; g.fillRect(x + 6, y - 1 - lift, 6, 1); g.fillRect(x + 6, y - 1 - lift, 1, 2); g.fillRect(x + 11, y - 1 - lift, 1, 2);
    if (world.wrench > 0) {
      var wy = y - 3 - Math.round((0.9 - world.wrench) * 10);
      g.fillStyle = C.metal; g.fillRect(x + 4, wy, 1, 5); g.fillRect(x + 3, wy - 1, 3, 1); g.fillRect(x + 3, wy - 2, 1, 1); g.fillRect(x + 5, wy - 2, 1, 1);
      g.fillStyle = C.gold; g.fillRect(x + 13, wy - 1, 1, 1); g.fillRect(x + 15, wy + 1, 1, 1);
    }
    text(g, "TOOLS", x + 20, y + 4, open ? C.gold : C.dim);
  }

  // 8-bit cloud: a rounded body with puffs on top and bottom, two dots trailing to the head.
  function cloud(g, x, y, w, hgt, fill, edge) {
    g.fillStyle = edge;
    g.fillRect(x + 1, y - 1, w - 2, hgt + 2); g.fillRect(x - 1, y + 1, w + 2, hgt - 2); g.fillRect(x, y, w, hgt);
    for (var px = x + 2; px < x + w - 4; px += 7) { g.fillRect(px, y - 3, 5, 3); g.fillRect(px + 3, y + hgt, 5, 3); }
    g.fillStyle = fill;
    g.fillRect(x + 1, y, w - 2, hgt); g.fillRect(x, y + 1, w, hgt - 2);
    for (var qx = x + 2; qx < x + w - 4; qx += 7) { g.fillRect(qx + 1, y - 2, 3, 2); g.fillRect(qx + 4, y + hgt, 3, 2); }
  }
  // Speech keeps its spot; clouds are placed around speech, heads and each other, never overlapping a
  // cloud. In a packed pit a cloud may sit over an idle agent's head, never over a busy one's.
  var worldRef = null;
  function layoutThoughts(list, speakers) {
    var placed = speakers.map(bubbleRect), out = [];
    // A stable order (speakers, then who started thinking first) so clouds do not trade places.
    list.forEach(function (a) { a.inBox = !!(worldRef && worldRef.arenaMode && (a.role === "red" || a.role === "blue")); });
    var minds = list.filter(function (a) { return !a.bubble && (a.thinking > 0 || (a.thought && !a.inBox)); })
      .sort(function (p, q) { return (q.thought ? 1 : 0) - (p.thought ? 1 : 0) || (p.thought ? p.hy - q.hy : 0) || (p.since || 0) - (q.since || 0) || (p.id < q.id ? -1 : 1); }).slice(0, 6);
    var headOf = function (a) { return { x: Math.round(a.x) - 1, y: Math.round(a.y) - 1, w: 10, h: 12 }; };
    var heads = list.map(headOf), busyHeads = minds.map(headOf);
    minds.forEach(function (a) {
      // Sticky: keep last frame's spot while it is still free, so a cloud never jitters.
      var r = keepSpot(a, placed.concat(busyHeads.filter(function (hd) { return hd.x !== Math.round(a.x) - 1 || hd.y !== Math.round(a.y) - 1; }))) ||
              placeThought(a, placed.concat(heads)) || placeThought(a, placed.concat(busyHeads)) ||
              (a.thought ? placeThought(a, placed.concat([headOf(a)])) : null);   // a real line beats a quip's head room
      if (r) { placed.push(r); out.push({ a: a, r: r }); a.spot = { dx: r.cx - Math.round(a.x), dy: r.cy - Math.round(a.y), key: (r.lines || []).join("|") }; }
      else a.spot = null;
    });
    list.forEach(function (a) { if (!a.thought && !(a.thinking > 0)) a.spot = null; });
    return out;
  }
  function keepSpot(a, obstacles) {
    var sp = a.spot, lines = thoughtLines(a);
    if (!sp || sp.key !== (lines || []).join("|")) return null;
    var w = lines ? Math.max.apply(null, lines.map(textW)) + 8 : 17, hgt = lines ? lines.length * 7 + 3 : 7;
    var x = Math.round(a.x) + sp.dx, y = Math.round(a.y) + sp.dy;
    if (x < 3 || x + w > W - 3 || y < TOP + 4 || y + hgt + 4 > BOTTOM) return null;
    var r = { x: x - 2, y: y - 3, w: w + 4, h: hgt + 6, cx: x, cy: y, cw: w, ch: hgt, lines: lines };
    if (overlaps(r, obstacles)) return null;
    // never sit on its own head
    if (overlaps(r, [{ x: Math.round(a.x) - 1, y: Math.round(a.y) - 1, w: 10, h: 12 }])) return null;
    return r;
  }
  function bubbleRect(a) {
    var b = a.bubble, lines = [b.word];
    if (b.reason) wrap(b.reason, 22).slice(0, 3).forEach(function (l) { lines.push(l); });
    var w = Math.max.apply(null, lines.map(textW)) + 6, hgt = lines.length * 7 + 4;
    var x = Math.max(2, Math.min(W - w - 2, Math.round(a.x + 4 - w / 2))), y = Math.max(TOP + 1, Math.round(a.y) - hgt - 4);
    return { x: x - 2, y: y - 2, w: w + 4, h: hgt + 6 };
  }
  function thoughtLines(a) {
    if (a.inBox) return null;   // the arena puts words in the dialogue box; the head only shows "..."
    var t = a.thought || (a.thinking > 0 && a.quip) || null;
    return t ? wrap(t, a.thought ? 34 : 26).slice(0, 2) : null;
  }
  function overlaps(r, list) {
    return list.some(function (q) { return r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h; });
  }
  // Try above the head, then higher, then to either side; give up rather than cover another cloud.
  function placeThought(a, placed) {
    var lines = thoughtLines(a);
    var w = lines ? Math.max.apply(null, lines.map(textW)) + 8 : 17, hgt = lines ? lines.length * 7 + 3 : 7;
    var ax = Math.round(a.x), ay = Math.round(a.y);
    // above the head first; the last few drop below the desk, for the top row and crowded pits
    var below = 30 + hgt;
    var offsets = [[0, 0], [0, -10], [-(w >> 1) - 6, 0], [(w >> 1) + 6, 0], [0, -20], [-(w >> 1) - 6, -12], [(w >> 1) + 6, -12], [0, -30],
                   [0, below], [-(w >> 1) - 6, below], [(w >> 1) + 6, below], [0, below + 10]];
    var spots = offsets.map(function (o) { return [ax + 4 - (w >> 1) + o[0], ay - hgt - 10 + o[1]]; });
    // beside the head, right then left, for tight rows
    var beside = [];
    [0, 6, -6, 11, -11].forEach(function (dy) { var y0 = ay - (hgt >> 1) + 2 + dy; beside.push([ax + 13, y0], [ax - w - 6, y0]); });
    spots.splice.apply(spots, [2, 0].concat(beside));
    for (var i = 0; i < spots.length; i++) {
      var x = Math.max(3, Math.min(W - w - 3, spots[i][0])), y = spots[i][1];
      if (y < TOP + 4 || y + hgt + 4 > BOTTOM) continue;
      var r = { x: x - 2, y: y - 3, w: w + 4, h: hgt + 6, cx: x, cy: y, cw: w, ch: hgt, lines: lines };
      if (!overlaps(r, placed)) return r;
    }
    return null;
  }
  var TEAM_CLOUD = { red: { fill: "#ffd9dd", edge: "#7a1020", ink: "#8f1d2c", quip: "#c0505e" },
                    blue: { fill: "#d6e6ff", edge: "#0f2f6b", ink: "#123a7a", quip: "#4f78c0" } };
  function drawThought(g, world, a, r) {
    var tc = TEAM_CLOUD[a.role];
    var fill = tc ? tc.fill : "#e9e4ff", edge = tc ? tc.edge : C.ink, ink = tc ? tc.ink : "#3b3270";
    var lines = r.lines, x = r.cx, y = r.cy, w = r.cw, hgt = r.ch;
    var ax = Math.round(a.x), ay = Math.round(a.y);
    cloud(g, x, y, w, hgt, fill, edge);
    // trail: dots from the cloud down to the head, wherever the cloud ended up
    var under = y > ay, side = !under && y + hgt > ay - 2;
    var tx0 = Math.max(x + 2, Math.min(x + w - 4, ax + 4)), ty0 = under ? y - 4 : y + hgt + 3, tx1 = ax + 4, ty1 = under ? ay + 14 : ay - 2;
    if (side) { tx0 = x > ax ? x - 3 : x + w + 2; ty0 = y + (hgt >> 1); tx1 = x > ax ? ax + 9 : ax - 2; ty1 = ay + 2; }
    [[0.35, 3], [0.75, 2]].forEach(function (d) {
      var px = Math.round(tx0 + (tx1 - tx0) * d[0]), py = Math.round(ty0 + (ty1 - ty0) * d[0]);
      g.fillStyle = edge; g.fillRect(px - 1, py - 1, d[1] + 1, d[1]);
      g.fillStyle = fill; g.fillRect(px, py, Math.max(1, d[1] - 1), Math.max(1, d[1] - 2));
    });
    var quip = !a.thought;
    if (lines) lines.forEach(function (l, i) { text(g, l, x + 4, y + 2 + i * 7, quip ? (tc ? tc.quip : "#7a6fb3") : ink, null, true); });
    else for (var d = 0; d < 3; d++) {
      g.fillStyle = (((world.clock * 4) | 0) % 3) === d ? ink : "#b9b0e6";
      g.fillRect(x + 4 + d * 4, y + 3, 2, 2);
    }
  }

  // analyst-007 -> A7, skeptic-03 -> SK3, red-trader -> RED: short enough to sit under a desk.
  function nameTag(id) {
    var m = String(id).match(/^([a-z]+)[-_]?0*(\d*)/i);
    if (!m) return String(id).slice(0, 4).toUpperCase();
    var word = m[1].toLowerCase(), num = m[2] || "";
    var short = { analyst: "A", skeptic: "SK", risk: "RK", reporter: "REP", cio: "CIO", cos: "COS", red: "RED", blue: "BLUE" }[word] || word.slice(0, 3);
    return (short + num).toUpperCase();
  }

  function wrap(s, n) {
    var words = s.split(/\s+/), out = [], cur = "";
    words.forEach(function (w) { if ((cur + " " + w).trim().length > n) { if (cur) out.push(cur); cur = w.slice(0, n); } else cur = (cur + " " + w).trim(); });
    if (cur) out.push(cur);
    return out;
  }

  // ---------------------------------------------------------------- arena: versus HUD and dialogue
  var TEAM_INK = { red: "#ff5a68", blue: "#5aa0ff" }, TEAM_DEEP = { red: "#5a1420", blue: "#12285a" };
  function teamAgent(world, team) {
    return world.order.map(function (id) { return world.agents[id]; }).filter(function (a) { return a.role === team; })[0] || null;
  }
  function drawVsHud(g, world) {
    var sb = world.arena || {}, teams = sb.teams || {};
    g.fillStyle = C.ink; g.fillRect(0, 0, W, TOP);
    g.fillStyle = "#1c1830"; g.fillRect(0, TOP - 2, W, 2);
    var mid = W >> 1, barW = mid - 26, bar = 6, by = 12;
    ["red", "blue"].forEach(function (team) {
      var t = teams[team] || {}, a = teamAgent(world, team), left = team === "red";
      var name = team.toUpperCase() + " " + (t.gate ? (t.gate === "arcade" ? "ARCADE" : "NO ARCADE") : modelWord(t.model || (a && a.model) || ""));
      var score = Math.max(0, Math.min(100, Number(t.score) || 0)), fill = Math.round(barW * score / 100);
      var x0 = left ? 4 : mid + 22;
      g.fillStyle = "#2a2440"; g.fillRect(x0, by, barW, bar);
      g.fillStyle = TEAM_DEEP[team]; g.fillRect(x0, by + bar - 2, barW, 2);
      g.fillStyle = TEAM_INK[team];
      // bars meet in the middle: RED fills toward VS from the left, BLUE from the right
      if (left) g.fillRect(x0 + barW - fill, by, fill, bar - 2); else g.fillRect(x0, by, fill, bar - 2);
      var sc = String(Math.round(score * 10) / 10);
      if (left) { text(g, name, 4, 3, TEAM_INK[team]); text(g, sc, x0 + barW - textW(sc), 3, C.cream); }
      else { text(g, name, W - 4 - textW(name), 3, TEAM_INK[team]); text(g, sc, x0, 3, C.cream); }
    });
    var lead = (teams.red && teams.blue) ? (teams.red.score > teams.blue.score ? "red" : teams.blue.score > teams.red.score ? "blue" : null) : null;
    text(g, "VS", mid - (textW("VS") >> 1), 3, lead ? TEAM_INK[lead] : C.gold);
    var left = sb.ends_at ? Math.max(0, Math.round(sb.ends_at - Date.now() / 1000)) : null;
    var bell = sb.opens_at ? Math.round(sb.opens_at - Date.now() / 1000) : 0;
    if (bell > 0 && !sb.final) { var bl = "BELL " + ((bell / 60) | 0) + ":" + ("0" + (bell % 60)).slice(-2); text(g, bl, mid - (textW(bl) >> 1), by, C.gold); return; }
    var clock = sb.final ? (sb.winner ? sb.winner.toUpperCase() + " WINS" : "DRAW") : left == null ? "--:--" : ((left / 60) | 0) + ":" + ("0" + (left % 60)).slice(-2);
    text(g, clock, mid - (textW(clock) >> 1), by, sb.final ? C.gold : C.cream);
  }
  function drawDialogue(g, world, team) {
    var sb = (world.arena || {}).teams || {}, t = sb[team] || {};
    var x = BOX[team][0], y = BOX[team][1], w = BOX.w, h = BOX.h, ink = TEAM_INK[team];
    g.fillStyle = ink; g.fillRect(x, y, w, h);
    g.fillStyle = "#0f0c1a"; g.fillRect(x + 1, y + 1, w - 2, h - 2);
    g.fillStyle = TEAM_DEEP[team]; g.fillRect(x + 1, y + 1, w - 2, 9);
    var pnl = t.pnl_pct != null ? (t.pnl_pct >= 0 ? "+" : "") + Number(t.pnl_pct).toFixed(2) + "%" : "";
    if (t.burn != null && t.net != null) pnl = "NET " + (t.net >= 0 ? "+$" : "-$") + Math.abs(Number(t.net)).toFixed(2);
    var head = team.toUpperCase() + (t.gate ? (t.gate === "arcade" ? " ARCADE" : " NO ARCADE") : " DESK") + (pnl ? "  " + pnl : "") + (t.trades != null ? "  " + t.trades + " TR" : "");
    text(g, head, x + 4, y + 3, ink);
    if (t.gate) {
      var tally = t.gate === "arcade" ? "STOPPED " + (t.stopped || 0) : "BREACHES " + (t.breaches || 0);
      text(g, tally, x + w - 4 - textW(tally), y + 3, t.gate === "arcade" ? C.gold : (t.breaches ? "#ff5a68" : C.dim));
    }
    var members = world.order.map(function (id) { return world.agents[id]; }).filter(function (a) { return a.role === team; });
    var firm = members.some(function (a) { return !isLead(a); });
    var log = (world.talk || {})[team] || [], cols = Math.floor((w - 8) / 4), ly = y + 14, floorY = y + h - 10;
    // firm: a fixed column of seat tags, the words indented after it (never two strings on one spot:
    // the terminal draws text as characters, and overlapping strings get pushed apart)
    var indent = firm ? 5 : 0, tx = x + 4 + indent * 4, tcols = cols - indent;
    var dimTag = team === "red" ? "#a8404e" : "#4068b0";
    if (t.thesis) {   // the firm's bet stays pinned above the talk
      var tl = "THESIS " + t.thesis;
      text(g, tl.length > cols ? tl.slice(0, cols - 3) + "..." : tl, x + 4, ly, C.gold, null, true);
      ly += 9;
    }
    if (!log.length) { text(g, "waiting for the first move", x + 4, ly, "#6f6790", null, true); ly += 9; }
    else {
      // the newest line types out in full; the eye goes to what changed
      var top = log[log.length - 1], lines = wrap(top.text, tcols).slice(0, 3);
      var shown = Math.floor((world.clock - top.at) * 45), n = 0;
      if (firm) text(g, seatTag(top.a), x + 4, ly, ink);
      lines.forEach(function (l, i) {
        var part = l.slice(0, Math.max(0, shown - n)); n += l.length + 1;
        if (part) text(g, part, tx, ly + i * 8, C.cream, null, true);
      });
      ly += lines.length * 8;
      // the lines before it, one each, dimmed, newest first
      for (var k = log.length - 2; k >= 0 && ly <= floorY - 8; k--) {
        var o = log[k], body = o.text.length > tcols ? o.text.slice(0, tcols - 3) + "..." : o.text;
        if (firm) text(g, seatTag(o.a), x + 4, ly, dimTag);
        text(g, body, tx, ly, "#6f6790", null, true);
        ly += 8;
      }
    }
    var busy = members.filter(function (a) { return a.thinking > 0; });
    if (busy.length) {
      var d = ((world.clock * 4) | 0) % 4;
      var who = firm ? busy.map(seatTag).join(" ") + " " : "";
      text(g, (who + "thinking" + ".".repeat(d)).slice(0, cols), x + 4, floorY, ink, null, true);
    }
  }

  function drawTicker(g, world, ui) {
    if (world.arenaMode && world.arena) return drawVsHud(g, world);
    g.fillStyle = C.ledDk; g.fillRect(0, 0, W, TOP);
    g.fillStyle = C.ink; g.fillRect(0, TOP - 2, W, 2);
    var firm = world.firm || "ARCADE FLOOR";
    text(g, firm, 4, 3, C.led);
    var mode = world.mode === "replay" ? "REPLAY " + (world.replayWo || "") : "LIVE";
    text(g, mode, 4, 11, world.mode === "replay" ? C.screen : (((world.clock * 2) | 0) % 2 ? C.red : "#7a2232"));
    var b = world.book;
    var right = b ? "BOOK $" + money(b.book_usd) + "   CASH $" + money(b.cash_usd) + "   FILLS " + b.fills + "   " + (b.label || "PAPER") : (companyKits ? "" : "NO BOOK");
    text(g, right, W - textW(right) - 4, 3, C.gold);
    // The terminal floor already lists the latest receipts under the room; a ticker there only crowds the header.
    if (!(ui && ui.term)) {
      g.save(); g.beginPath(); g.rect(120, 10, W - 124, 9); g.clip();
      text(g, world.ticker || "WAITING FOR THE FIRST RECEIPT", Math.round(world.tickerX), 11, C.led);
      g.restore();
    }
  }
  function money(n) { n = Math.round(Number(n) || 0); return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ","); }

  function drawBottom(g, world, ui) {
    g.fillStyle = C.ink; g.fillRect(0, BOTTOM, W, H - BOTTOM);
    g.fillStyle = C.trim; g.fillRect(0, BOTTOM, W, 1);
    world.log.slice(-2).forEach(function (l, i) { text(g, l.text, 4, BOTTOM + 4 + i * 7, l.color); });
    ui.buttons = [];
    var bx = 4, by = H - 9;
    function btn(label, on, fn) {
      var w = textW(label) + 6;
      g.fillStyle = on ? C.amber : C.wallHi; g.fillRect(bx, by - 1, w, 8);
      text(g, label, bx + 3, by, on ? C.ink : C.cream);
      ui.buttons.push({ x: bx, y: by - 1, w: w, h: 8, fn: fn });
      bx += w + 4;
    }
    if (ui.term) {
      var wo0 = ui.workOrders[ui.woIndex];
      var hint = "[L] LIVE   [R] REPLAY " + (wo0 ? String(wo0.work_order).slice(0, 16) + " (" + wo0.events + ")" : "-") +
                 "   [ ] PICK   [S] " + ui.speed + "X   [G] " + (ui.cells === "half" ? "CHUNKY" : "FINE") + "   [Q] QUIT";
      text(g, hint, 4, by, world.mode === "replay" ? C.screen : C.amber);
      return;
    }
    btn("LIVE", world.mode !== "replay", ui.goLive);
    btn("< ", false, function () { ui.pick(-1); });
    var wo = ui.workOrders[ui.woIndex];
    btn(wo ? "REPLAY " + String(wo.work_order).slice(0, 16) + " (" + wo.events + ")" : "NO WORK ORDERS", world.mode === "replay", ui.replay);
    btn(" >", false, function () { ui.pick(1); });
    btn(ui.speed + "X", false, ui.cycleSpeed);
    btn(audio.on ? "SOUND ON" : "SOUND OFF", audio.on, function () { audio.on = !audio.on; beep("ok"); });
    var legend = "GREEN PASS  RED DENIED  AMBER WAITS ON YOUR PHONE";
    if (bx + textW(legend) + 8 < W) text(g, legend, W - textW(legend) - 4, by, C.dim);
  }

  function drawCard(g, a) {
    var e = a.last, lines = [a.id, ROLE[a.role].tag];
    if (e) {
      lines.push(shortTool(e.tool) + " " + String(e.decision || "").toUpperCase());
      if (e.work_order) lines.push(e.work_order);
      if (e.reason) wrap(String(e.reason).toUpperCase(), 30).slice(0, 2).forEach(function (l) { lines.push(l); });
    } else lines.push("NO CALLS YET");
    var w = Math.max.apply(null, lines.map(textW)) + 8, hgt = lines.length * 7 + 5;
    var x = Math.min(W - w - 2, Math.round(a.x) + 12), y = Math.max(TOP + 2, Math.min(BOTTOM - hgt - 2, Math.round(a.y) - 4));
    g.fillStyle = C.ink; g.fillRect(x - 1, y - 1, w + 2, hgt + 2);
    g.fillStyle = C.wall; g.fillRect(x, y, w, hgt);
    g.fillStyle = ROLE[a.role].body; g.fillRect(x, y, 2, hgt);
    lines.forEach(function (l, i) { text(g, l, x + 5, y + 3 + i * 7, i === 0 ? C.cream : C.dim); });
  }

  // ---------------------------------------------------------------- events in
  function logLine(world, e) {
    var who = agentIdFor(e).toUpperCase(), d = String(e.decision || "").toUpperCase(), tool = shortTool(e.tool);
    var color = d === "DENIED" ? C.red : d === "APPROVED" ? C.green : d === "HANDED_BACK" ? C.amber : C.cream;
    var extra = e.input && e.input.symbol ? " " + e.input.symbol + (e.input.notional_usd ? " $" + e.input.notional_usd : "") : "";
    var t = (e.ts || "").slice(11, 16) + " " + who + (e.via ? " FOR " + String(e.role || "").toUpperCase() : "") + "  " + d.replace("_", " ") + "  " + tool + extra;
    if (d === "DENIED" && e.reason) t += "  " + String(e.reason).toUpperCase();
    world.log.push({ text: t.slice(0, 94), color: color });
    if (world.log.length > 50) world.log.shift();
    world.ticker = t.slice(0, 160);
    world.tickerX = W;
  }

  function ingest(world, events, animate) {
    events.forEach(function (e) {
      world.seq = Math.max(world.seq, e.seq || 0);
      ensureAgent(world, e).last = e;
      logLine(world, e);
      if (animate) { if (world.arenaMode) planArenaTrip(world, e); else planTrip(world, e); }
    });
  }

  // Quips: what a thinking agent might be mumbling, picked from its role, its model and the moment.
  // Shown only while the model runs and nothing real has been said; a real line always replaces it.
  var QUIPS = {
    any: ["hmm.", "is this alpha or noise", "one more look", "trust the process", "reading the room", "numbers, please behave"],
    analyst: ["chart looks like a cat", "DOGE is a vibe, not a thesis", "spreadsheet says yes", "drawing a trend line. again."],
    cio: ["conviction: medium rare", "sizing it like a grown up", "the thesis writes itself. it does not."],
    skeptic: ["citation needed", "what could go wrong. everything.", "I have notes", "devil's advocate, reporting in"],
    risk: ["have we tried not doing that", "40% is a cap, not a goal", "checking the exits"],
    reporter: ["lede: line went up", "needs a better headline", "who, what, why, how much"],
    cos: ["who approved this. oh, me.", "agenda item 7 of 3", "keeping the founder out of it"],
    red: ["buy high, sell higher", "fees are a state of mind", "beat blue. that is the plan.", "red candles are just warm"],
    blue: ["cool heads, warm bags", "beat red. calmly.", "blue chip energy", "patience is a position"],
    claude: ["let me reconsider. again.", "being careful here", "on the other hand..."],
    gpt: ["certainly! a trade:", "great question, market", "as a large trader model..."],
    gemini: ["searching my feelings", "multimodal hunch"],
    grok: ["based trade incoming", "the chart is the meme"],
    qwen: ["thinking in two languages", "small model, big swing"],
    deepseek: ["reasoning... deeply", "chain of thought: chain of trades"],
  };
  function modelWord(model) {
    var m = String(model || "").split("/").pop().replace(/^claude-/, "").replace(/-\d.*$/, "");
    return m.toUpperCase().slice(0, 8);
  }
  function family(model) {
    var m = String(model || "").toLowerCase();
    return ["claude", "gpt", "gemini", "grok", "qwen", "deepseek"].filter(function (f) { return m.indexOf(f) >= 0 || (f === "gpt" && m.indexOf("openai") >= 0); })[0];
  }
  function quipFor(a, model) {
    var pool = QUIPS.any.concat(QUIPS[a.role] || []);
    var fam = family(model || a.model);
    if (fam) pool = pool.concat(QUIPS[fam], QUIPS[fam]);
    return pool[(hash(a.id + ":" + (a.quips = (a.quips || 0) + 1)) >>> 4) % pool.length];
  }

  // Activity: thinking, the line an agent says before acting, and local (toolbox) tools.
  function ingestActivity(world, acts, animate) {
    acts.forEach(function (ev) {
      world.act = Math.max(world.act, ev.n || 0);
      if (!animate) return;
      var e = { role: ev.role, profile: ev.profile, tool: ev.tool };
      var a = ensureAgent(world, e);
      if (ev.model) a.model = ev.model;
      var team = a.role === "red" || a.role === "blue";
      if (ev.kind === "think") {
        if (!(a.thinking > 0)) a.since = world.clock;
        a.thinking = 90;
        // traders: no jokes over their real lines; their last line stays up while they think
        if (team) a.quip = null;
        else if (!a.quip || Math.random() < 0.25) a.quip = Math.random() < 0.7 ? quipFor(a, ev.model) : null;
      }
      else if (ev.kind === "think_end") { a.thinking = 0; a.quip = null; }
      else if (ev.kind === "say" && ev.text) {
        if (a.thought && a.thought !== String(ev.text)) a.prevThought = a.thought;
        a.thought = String(ev.text); a.tht = team ? 600 : 7; a.thinking = 0; a.since = world.clock; a.saidAt = world.clock;
        if (team) {
          var log = (world.talk = world.talk || {})[a.role] = (world.talk[a.role] || []);
          log.push({ a: a, text: String(ev.text), at: world.clock });
          if (log.length > 6) log.shift();
        }
      }
      else if (ev.kind === "tool" && ev.tool) planToolbox(world, e);
    });
  }

  // ---------------------------------------------------------------- the React tab
  function FloorPage() {
    var ref = React.useRef(null);
    var stateRef = React.useRef(null);
    var tick = React.useState(0), setTick = tick[1];

    React.useEffect(function () {
      var canvas = ref.current, g = canvas.getContext("2d");
      var world = makeWorld();
      var ui = { hover: null, buttons: [], workOrders: [], woIndex: 0, speed: 1 };
      stateRef.current = { world: world, ui: ui };
      var alive = true, raf = 0, last = performance.now(), poll = 0, replayTimers = [];

      function fetchState(q) { return SDK.fetchJSON(API + "/state" + q); }
      function clearReplay() { replayTimers.forEach(clearTimeout); replayTimers = []; }
      function reset(mode) {
        var fresh = makeWorld();
        Object.keys(fresh).forEach(function (k) { world[k] = fresh[k]; });
        world.mode = mode;
      }
      ui.goLive = function () {
        clearReplay(); reset("live");
        fetchState("?after=0").then(function (s) {
          world.firm = s.firm; world.book = s.book;
          ingest(world, s.events || [], false);
          ingestActivity(world, s.activity || [], false);
          (s.waiting || []).forEach(function (w) { holdAtDoor(world, w); });
        }).catch(function () {});
      };
      ui.replay = function () {
        var wo = ui.workOrders[ui.woIndex];
        if (!wo) return;
        clearReplay(); reset("replay");
        world.replayWo = wo.work_order;
        fetchState("?after=0&work_order=" + encodeURIComponent(wo.work_order)).then(function (s) {
          world.firm = s.firm; world.book = s.book;
          var evs = s.events || [], t = 0, prev = null;
          evs.forEach(function (e) { ensureAgent(world, e); });
          evs.forEach(function (e) {
            var ts = Date.parse(e.ts) || 0, gap = prev == null ? 0.4 : Math.min(2.4, Math.max(0.25, (ts - prev) / 1000 / 20));
            prev = ts; t += gap / ui.speed;
            var founder = e.decision === "approved" || (e.decision === "denied" && e.approver) || e.decision === "handed_back";
            replayTimers.push(setTimeout(function () { if (alive && world.mode === "replay") ingest(world, [e], true); }, t * 1000));
            // The founder's door is the point of the floor: it plays in real time whatever the speed.
            if (founder) t += 3.5;
          });
        }).catch(function () {});
      };
      ui.pick = function (d) { if (ui.workOrders.length) ui.woIndex = (ui.woIndex + d + ui.workOrders.length) % ui.workOrders.length; };
      ui.cycleSpeed = function () { ui.speed = { 1: 2, 2: 4, 4: 8, 8: 1 }[ui.speed]; };

      SDK.fetchJSON(API + "/work_orders").then(function (r) { ui.workOrders = r.work_orders || []; }).catch(function () {});
      ui.goLive();

      function doPoll() {
        if (!alive) return;
        if (world.mode === "live") {
          fetchState("?after=" + world.seq + "&act=" + world.act).then(function (s) {
            if (world.mode !== "live") return;
            world.book = s.book; world.firm = s.firm; world.arena = s.arena || null;
            (s.waiting || []).forEach(function (w) { holdAtDoor(world, w); });
            ingest(world, s.events || [], true);
            ingestActivity(world, s.activity || [], true);
          }).catch(function () {});
        }
        poll = setTimeout(doPoll, 1500);
      }
      poll = setTimeout(doPoll, 1500);

      function frame(now) {
        if (!alive) return;
        world.speed = ui.speed; sayScale = world.mode === "replay" ? ui.speed * 1.5 : 1;
        var dt = Math.min(0.05, (now - last) / 1000) * (world.mode === "replay" ? ui.speed : 1);
        last = now;
        step(world, dt);
        draw(g, world, ui);
        raf = requestAnimationFrame(frame);
      }
      raf = requestAnimationFrame(frame);

      function toWorld(ev) {
        var r = canvas.getBoundingClientRect();
        return { x: (ev.clientX - r.left) * (W / r.width), y: (ev.clientY - r.top) * (H / r.height) };
      }
      function onMove(ev) {
        var p = toWorld(ev), best = null, bd = 64;
        world.order.forEach(function (id) { var a = world.agents[id], d = Math.pow(a.x + 4 - p.x, 2) + Math.pow(a.y + 5 - p.y, 2); if (d < bd) { bd = d; best = id; } });
        ui.hover = best;
        canvas.style.cursor = ui.buttons.some(function (b) { return p.x >= b.x && p.x <= b.x + b.w && p.y >= b.y && p.y <= b.y + b.h; }) ? "pointer" : "default";
      }
      function onClick(ev) {
        var p = toWorld(ev);
        ui.buttons.forEach(function (b) { if (p.x >= b.x && p.x <= b.x + b.w && p.y >= b.y && p.y <= b.y + b.h && b.fn) b.fn(); });
      }
      canvas.addEventListener("mousemove", onMove);
      canvas.addEventListener("click", onClick);
      canvas.addEventListener("mouseleave", function () { ui.hover = null; });

      function fit() {
        var box = canvas.parentElement.getBoundingClientRect();
        var scale = Math.max(1, Math.floor(Math.min(box.width / W, (window.innerHeight - box.top - 24) / H)));
        canvas.style.width = W * scale + "px"; canvas.style.height = H * scale + "px";
        setTick(function (n) { return n + 1; });
      }
      fit();
      window.addEventListener("resize", fit);
      return function () {
        alive = false; cancelAnimationFrame(raf); clearTimeout(poll); clearReplay();
        window.removeEventListener("resize", fit);
      };
    }, []);

    return h("div", { className: "arcade-floor" },
      h("canvas", { ref: ref, width: W, height: H, className: "arcade-floor-canvas", "aria-label": "Arcade floor: live view of governed agent tool calls" }));
  }

  if (HOSTED) window.__HERMES_PLUGINS__.register("arcade-for-hermes", FloorPage);

  // test hook: lets a headless check drive the simulation without a browser tab
  window.__ARCADE_FLOOR__ = { makeWorld: makeWorld, ingest: ingest, ingestActivity: ingestActivity, layoutThoughts: layoutThoughts, step: step, holdAtDoor: holdAtDoor, draw: draw, ensureAgent: ensureAgent, setKits: setKits,
                              GLYPHS: GLYPHS, W: W, H: H, C: C, setSayScale: function (s) { sayScale = s; } };
})();
