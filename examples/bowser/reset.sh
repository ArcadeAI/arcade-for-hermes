#!/usr/bin/env bash
# Reset Bowser Capital between takes: Koopa fixtures, receipts, and (optionally) the role profiles.
#   bash examples/bowser/reset.sh            # reset Koopa state and receipts in $HERMES_HOME
#   bash examples/bowser/reset.sh --install  # also link the plugins into every role profile and write SOUL.md
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(cd "$HERE/../.." && pwd)"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
# Every non-default profile named in the policy's profile_roles (the swarm included).
PROFILES="$(python3 - "$HERE/policy.yaml" <<'PY2'
import re, sys
text = open(sys.argv[1]).read()
block = re.search(r"(?ms)^profile_roles:\n(.*?)(?=^\S)", text).group(1)
print(" ".join(m.group(1) for m in re.finditer(r"(?m)^  ([\w-]+):\s*([\w-]+)", block) if m.group(1) != "default"))
PY2
)"
role_of() { python3 - "$HERE/policy.yaml" "$1" <<'PY2'
import re, sys
m = re.search(r"(?m)^  %s:\s*([\w-]+)" % re.escape(sys.argv[2]), open(sys.argv[1]).read())
print(m.group(1) if m else sys.argv[2])
PY2
}

echo "Hermes home: $HERMES_HOME"
mkdir -p "$HERMES_HOME/plugin-data/koopa" "$HERMES_HOME/plugin-data/arcade-for-hermes" "$HERMES_HOME/arcade"
python3 - "$HERE/koopa" "$HERMES_HOME/plugin-data/koopa" <<'PY'
import importlib.util, sys
from pathlib import Path
root, state = Path(sys.argv[1]), Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("koopa_mod", root / "koopa.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.Desk(state, root / "fixtures").reset()
print("Koopa reset: $10,000 cash, no positions, crypto fixture prices refreshed (PAPER MODE)")
PY
: > "$HERMES_HOME/plugin-data/arcade-for-hermes/receipts.jsonl"
echo "Receipts cleared"
cp "$HERE/policy.yaml" "$HERMES_HOME/arcade/policy.yaml"
if [ -n "${ARCADE_SHARED_PRINCIPAL:-}" ]; then
  printf '\nshared_principal: %s\n' "$ARCADE_SHARED_PRINCIPAL" >> "$HERMES_HOME/arcade/policy.yaml"
  echo "shared_principal: every role acts as $ARCADE_SHARED_PRINCIPAL"
fi
echo "Policy installed at $HERMES_HOME/arcade/policy.yaml"

if [ "${1:-}" = "--install" ]; then
  for p in $PROFILES; do
    PH="$HERMES_HOME/profiles/$p"
    role="$(role_of "$p")"
    [ -d "$PH" ] || hermes profile create "$p" --no-alias --description "Bowser Capital $role ($p)" >/dev/null
    mkdir -p "$PH/plugins"
    ln -sfn "$PLUGIN_DIR" "$PH/plugins/arcade-for-hermes"
    ln -sfn "$HERE/koopa" "$PH/plugins/koopa"
    if [ -f "$HERE/souls/$p.md" ]; then cp "$HERE/souls/$p.md" "$PH/SOUL.md"; else cp "$HERE/souls/$role.md" "$PH/SOUL.md"; fi
    # Copy the main profile's keys and model into a new profile (values never printed).
    touch "$PH/.env"
    for k in ARCADE_API_KEY OPENROUTER_API_KEY; do
      grep -q "^$k=" "$PH/.env" || grep "^$k=" "$HERMES_HOME/.env" >> "$PH/.env" 2>/dev/null || true
    done
    for kv in model.provider model.default; do
      v="$(HERMES_HOME="$HERMES_HOME" hermes config get "$kv" 2>/dev/null | tail -1)"
      [ -n "$v" ] && HERMES_HOME="$PH" hermes config set "$kv" "$v" >/dev/null 2>&1 || true
    done
    for plugin in arcade-for-hermes koopa; do
      yes 2>/dev/null | HERMES_HOME="$PH" hermes plugins enable "$plugin" | tail -1
    done
  done
  mkdir -p "$HERMES_HOME/plugins"
  ln -sfn "$HERE/koopa" "$HERMES_HOME/plugins/koopa"
  yes 2>/dev/null | hermes plugins enable koopa | tail -1
  echo "Installed. Put ARCADE_API_KEY in each profile's .env, then run /arcade connect."
fi
