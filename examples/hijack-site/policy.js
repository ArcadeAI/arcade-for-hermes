/* A line-for-line port of policy.py's decision path (Policy.__init__ validation is trimmed to what the
   site's policy uses). check_parity.js and the page itself run it over vectors.json, which policy.py
   wrote, and every answer must match. Pure: no network, no page state. */
(function (root) {
  "use strict";
  var VERBS = ["look", "draft", "ship"];

  function globRe(pat) {               // fnmatch.translate, enough of it: * ? [seq] [!seq]
    var out = "", i = 0;
    while (i < pat.length) {
      var c = pat[i++];
      if (c === "*") out += "[\\s\\S]*";
      else if (c === "?") out += "[\\s\\S]";
      else if (c === "[") {
        var j = i;
        if (pat[j] === "!") j++;
        if (pat[j] === "]") j++;
        while (j < pat.length && pat[j] !== "]") j++;
        if (j >= pat.length) out += "\\[";
        else {
          var stuff = pat.slice(i, j).replace(/\\/g, "\\\\");
          i = j + 1;
          if (stuff[0] === "!") stuff = "^" + stuff.slice(1);
          else if (stuff[0] === "^") stuff = "\\" + stuff;
          out += "[" + stuff + "]";
        }
      } else out += c.replace(/[.*+?^${}()|[\]\\\/]/g, "\\$&");
    }
    return new RegExp("^(?:" + out + ")$");
  }
  function glob(name, pat) { return globRe(pat).test(name); }

  function isMap(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }

  function getPath(data, dotted) {
    var cur = data, parts = dotted.split(".");
    for (var i = 0; i < parts.length; i++) {
      if (isMap(cur) && Object.prototype.hasOwnProperty.call(cur, parts[i])) cur = cur[parts[i]];
      else return null;
    }
    return cur === undefined ? null : cur;
  }

  function pyStr(v) {                  // str() of a scalar the way Python prints it
    if (v === true) return "True";
    if (v === false) return "False";
    return String(v);
  }

  function matchValue(expected, actual) {
    if (expected === "*") return actual !== null && actual !== undefined;
    if (expected === "!") return actual === null || actual === undefined;
    if (Array.isArray(expected)) return expected.some(function (e) { return matchValue(e, actual); });
    if (typeof expected === "boolean")
      return actual === expected || (typeof actual === "string" && actual.toLowerCase() === pyStr(expected).toLowerCase());
    if (typeof expected === "number") return actual === expected;
    if (typeof expected === "string") {
      if (actual === null || actual === undefined || typeof actual === "object") return false;
      return glob(pyStr(actual).toLowerCase(), expected.toLowerCase());
    }
    return expected === actual;
  }

  function amountOf(value) {           // _amount: a finite number >= 0, else null
    if (typeof value === "boolean" || value === null || value === undefined) return null;
    var n;
    if (typeof value === "string") {
      var s = value.replace(/,/g, "").replace(/\$/g, "").trim();
      if (!/^[+-]?(\d+(_\d+)*(\.(\d+(_\d+)*)?)?|\.\d+(_\d+)*)([eE][+-]?\d+)?$/.test(s)) {
        var low = s.toLowerCase().replace(/^[+-]/, "");
        if (low === "inf" || low === "infinity" || low === "nan") return null;
        return null;
      }
      n = Number(s.replace(/_/g, ""));
    } else if (typeof value === "number") n = value;
    else return null;
    return isFinite(n) && n >= 0 ? n : null;
  }

  function money(n) {                  // f"{n:,.2f}"
    return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function pyRepr(s) { return s.indexOf("'") >= 0 && s.indexOf('"') < 0 ? '"' + s + '"' : "'" + s.replace(/'/g, "\\'") + "'"; }
  function pyJson(v) {                 // json.dumps(v, sort_keys=True)
    if (Array.isArray(v)) return "[" + v.map(pyJson).join(", ") + "]";
    if (isMap(v)) return "{" + Object.keys(v).sort().map(function (k) { return JSON.stringify(k) + ": " + pyJson(v[k]); }).join(", ") + "}";
    if (v === true) return "true";
    if (v === false) return "false";
    if (v === null || v === undefined) return "null";
    return JSON.stringify(v);
  }

  function Policy(data) {
    var aliases = {}, self = this;
    Object.keys(data.toolkits || {}).forEach(function (canon) {
      var c = canon.toLowerCase();
      aliases[c] = c;
      (data.toolkits[canon] || []).forEach(function (a) { aliases[String(a).toLowerCase()] = c; });
    });
    this.aliases = aliases;
    this.rules = (data.rules || []).map(function (raw, i) {
      var verb = String(raw.verb).toLowerCase();
      if (VERBS.indexOf(verb) < 0) throw new Error("rules[" + i + "] verb " + verb);
      return { name: raw.name ? String(raw.name) : "rules[" + i + "]:" + raw.tool, tool: String(raw.tool), verb: verb,
               toolkit: raw.toolkit ? String(raw.toolkit).toLowerCase() : null, input: raw.input || {},
               amount: raw.amount ? String(raw.amount).trim() : null, exit: !!raw.exit };
    });
    this.roles = {};
    Object.keys(data.roles || {}).forEach(function (name) {
      var raw = data.roles[name] || {};
      self.roles[name] = {
        grants: (raw.grants || []).map(function (g) {
          return { toolkit: String(g.toolkit).toLowerCase(), verbs: (g.verbs || []).map(function (v) { return String(v).toLowerCase(); }), owns: g.owns || null };
        }),
        deny_reasons: raw.deny_reasons || {},
        limits: raw.limits || {}
      };
    });
  }

  Policy.prototype.toolkitOf = function (tool) {
    for (var i = 0; i < this.rules.length; i++) {
      var r = this.rules[i];
      if (r.toolkit && glob(tool.toLowerCase(), r.tool.toLowerCase())) return r.toolkit;
    }
    if (tool.indexOf(".") >= 0) {
      var a = this.aliases[tool.split(".")[0].toLowerCase()];
      return a === undefined ? null : a;
    }
    return null;
  };

  Policy.prototype.classify = function (tool, input) {
    for (var i = 0; i < this.rules.length; i++) {
      var r = this.rules[i];
      if (!glob(tool.toLowerCase(), r.tool.toLowerCase())) continue;
      var ok = Object.keys(r.input).every(function (k) { return matchValue(r.input[k], getPath(input, k)); });
      if (ok) return r;
    }
    return null;
  };

  Policy.prototype.decide = function (role, tool, input, state) {
    state = state || {};
    input = isMap(input) ? input : {};
    var halted = state.halted || null, spent = state.spent_today || 0;
    function D(allowed, verb, toolkit, reason, rule, amount, exit) {
      return { allowed: allowed, role: role, tool: tool, verb: verb === undefined ? null : verb,
               toolkit: toolkit === undefined ? null : toolkit, reason: reason, rule: rule || null,
               requires_approval: !!(allowed && verb === "ship"),
               amount: amount === undefined ? null : amount, exit: !!exit };
    }
    if (!Object.prototype.hasOwnProperty.call(this.roles, role))
      return D(false, null, null, "role " + pyRepr(role) + " is not in the policy; default deny");
    var rule = this.classify(tool, input);
    if (!rule) return D(false, null, this.toolkitOf(tool), "no rule classifies " + tool + "; default deny");
    var toolkit = rule.toolkit || this.toolkitOf(tool);
    if (!toolkit) return D(false, rule.verb, null, "toolkit of " + tool + " is not declared in the policy; default deny", rule.name);
    var verb = rule.verb, spec = this.roles[role];
    var matching = spec.grants.filter(function (g) { return g.toolkit === toolkit && g.verbs.indexOf(verb) >= 0; });
    if (!matching.length) {
      var reason = role + " has no " + verb + " grant on " + toolkit;
      var extra = spec.deny_reasons[toolkit + "." + verb] || spec.deny_reasons[toolkit];
      if (extra) reason += ": " + extra;
      return D(false, verb, toolkit, reason, rule.name);
    }
    var unowned = matching.filter(function (g) {
      return g.owns && !Object.keys(g.owns).every(function (k) { return matchValue(g.owns[k], getPath(input, k)); });
    });
    if (unowned.length && unowned.length === matching.length)
      return D(false, verb, toolkit, tool + " targets an artifact " + role + " does not own (owns: " + pyJson(unowned[0].owns || {}) + ")", rule.name);
    var amount = rule.amount ? amountOf(getPath(input, rule.amount)) : null;
    function deny(reason) { return D(false, verb, toolkit, reason, rule.name, amount, rule.exit); }
    if (halted && verb !== "look" && !rule.exit)
      return deny("halted by the founder (" + halted + "); only exits run until /arcade resume");
    var limits = spec.limits || {};
    if (rule.amount && Object.keys(limits).length && !rule.exit) {
      if (amount === null) return deny(tool + " has no readable amount at '" + rule.amount + "', so " + role + "'s limits cannot be checked");
      var cap = limits.per_call;
      if (cap !== undefined && cap !== null && amount > cap) return deny(money(amount) + " is over " + role + "'s per-call limit of " + money(cap));
      cap = limits.per_day;
      if (cap !== undefined && cap !== null && spent + amount > cap)
        return deny(money(amount) + " would take " + role + " to " + money(spent + amount) + " today, over the daily limit of " + money(cap));
    }
    return D(true, verb, toolkit, role + " may " + verb + " on " + toolkit, rule.name, amount, rule.exit);
  };

  var KEYS = ["allowed", "verb", "toolkit", "reason", "rule", "requires_approval", "amount", "exit"];
  function parity(policy, cases) {
    var bad = [];
    cases.forEach(function (c) {
      var got = policy.decide(c.role, c.tool, c.input, c.state);
      for (var i = 0; i < KEYS.length; i++) {
        var k = KEYS[i], a = got[k], b = c.expect[k];
        if (!(a === b || (a === null && b === undefined))) { bad.push({ c: c, key: k, got: a, want: b }); break; }
      }
    });
    return { total: cases.length, failed: bad };
  }

  var api = { Policy: Policy, parity: parity, amountOf: amountOf, money: money };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.BowserPolicy = api;
})(this);
