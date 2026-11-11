// node examples/hijack-site/check_parity.js : the JS port must give policy.py's answer on every case.
const fs = require("fs");
const path = require("path");
const { Policy, parity } = require("./policy.js");
const here = __dirname;
const { suites } = JSON.parse(fs.readFileSync(path.join(here, "vectors.json"), "utf8"));
let total = 0, failed = 0;
for (const s of suites) {
  const r = parity(new Policy(s.policy), s.cases);
  total += r.total; failed += r.failed.length;
  for (const f of r.failed.slice(0, 10)) console.log("MISMATCH", s.scenario, f.c.role, f.c.tool, JSON.stringify(f.c.input), JSON.stringify(f.c.state), f.key, "got", JSON.stringify(f.got), "want", JSON.stringify(f.want));
  console.log(`${s.scenario}: ${r.total - r.failed.length}/${r.total}`);
}
console.log(`${total - failed}/${total} match policy.py`);
process.exit(failed ? 1 : 0);
