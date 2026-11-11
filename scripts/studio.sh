#!/usr/bin/env bash
# The demo studio: one Hermes home per company, one Rex window per home.
#
#   scripts/studio.sh setup coo                    # a home at ~/arcade-studio/coo, signed in to Arcade's gateway
#   scripts/studio.sh setup software-startup founder
#   scripts/studio.sh setup shirt-shop yolo
#   scripts/studio.sh setup trading-desk roles --gateway-url https://api.arcade.dev/mcp/<your gateway slug>
#   scripts/studio.sh open                         # Rex session "arcade-studio": a window per home
#   scripts/studio.sh status
#
# Each window: Hermes (the lead) on the left, the Floor top right, the company's board bottom right.
# Bottom right is the gate: the board's tasks, then every Arcade call as the policy decides it.
#
# Secrets: setup copies only the model key line from SOURCE_HOME's .env into the new home's .env
# (never printed). Sign-in to the gateway happens in your browser, once per home; every role profile
# is linked to that one sign-in when the company is founded.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERMES="${HERMES:-$HOME/hermes-v0.23.0/.venv/bin/hermes}"
PY="$(dirname "$HERMES")/python"
HERMES_SRC="$(cd "$(dirname "$HERMES")/../.." && pwd)"
STUDIO="${ARCADE_STUDIO:-$HOME/arcade-studio}"
SOURCE_HOME="${SOURCE_HOME:-$HOME/.hermes-arcade-spike}"     # where the model settings and key come from
OFFICIAL_PLUGIN="${ARCADE_PLUGIN_DIR:-$HOME/arcade-plugin/plugin}"   # a local copy of ArcadeAI/arcade-plugin
ORDER=(coo software-startup shirt-shop trading-desk)
# Founding shells out to `hermes`; make it this one, not an older install earlier on PATH.
export PATH="$(dirname "$HERMES"):$PATH"

die() { echo "studio: $*" >&2; exit 1; }
label() { case "$1" in coo) echo "1 COO";; software-startup) echo "2 Startup";; shirt-shop) echo "3 Shirts";;
                       trading-desk) echo "4 Desk";; *) echo "$1";; esac; }

setup() {
  local template="$1" setting="" url="https://api.arcade.dev/mcp/arcade" name="arcade"
  shift
  if [[ $# -gt 0 && "$1" != --* ]]; then setting="$1"; shift; fi
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --gateway-url) url="$2"; name="arcade-own"; shift 2;;
      *) die "unknown option $1";;
    esac
  done
  [[ -f "$ROOT/templates/$template.yaml" ]] || die "no template $template (see templates/)"
  [[ -d "$OFFICIAL_PLUGIN" ]] || die "no Arcade plugin at $OFFICIAL_PLUGIN (git clone https://github.com/ArcadeAI/arcade-plugin.git ~/arcade-plugin)"
  if [[ "$template" == trading-desk && "$name" == arcade ]]; then
    die "the trading desk runs on your own gateway: pass --gateway-url (the official gateway has no ArcadeAlpaca)"
  fi
  local home="$STUDIO/$template"
  export HERMES_HOME="$home"
  mkdir -p "$home/plugins"
  echo "== $template -> $home"

  # Model: the same provider and model as the source home; only the matching key line is copied.
  local provider model
  provider="$(HERMES_HOME="$SOURCE_HOME" "$HERMES" config get model.provider 2>/dev/null | tail -1 || true)"
  model="$(HERMES_HOME="$SOURCE_HOME" "$HERMES" config get model.default 2>/dev/null | tail -1 || true)"
  [[ -n "$provider" ]] && "$HERMES" config set model.provider "$provider" >/dev/null
  [[ -n "$model" ]] && "$HERMES" config set model.default "$model" >/dev/null
  if [[ -f "$SOURCE_HOME/.env" ]] && ! grep -q '^OPENROUTER_API_KEY=' "$home/.env" 2>/dev/null; then
    grep '^OPENROUTER_API_KEY=' "$SOURCE_HOME/.env" >> "$home/.env" || true
    chmod 600 "$home/.env"
  fi

  # Arcade's official plugin (skills + gateway declaration) and ours (the company layer).
  mkdir -p "$home/plugins/arcade" && rsync -a --delete "$OFFICIAL_PLUGIN/" "$home/plugins/arcade/"
  ln -sfn "$ROOT" "$home/plugins/arcade-for-hermes"
  "$HERMES" plugins enable arcade >/dev/null
  "$HERMES" plugins enable arcade-for-hermes >/dev/null

  # A plugin install builds the home's dependency environment without Hermes's optional mcp extra.
  # Skip the sync when the newest environment already has it: the sync re-resolves the whole lock
  # and fails on any flaky download, even with nothing to add.
  local newest
  newest="$(ls -td "$home"/installs/*/environments/*/ 2>/dev/null | head -1)"
  if [[ -n "$newest" ]] && compgen -G "${newest}venv/lib/python*/site-packages/mcp" >/dev/null; then
    echo "The mcp extra is already in this home's environment."
  else
    (cd "$HERMES_SRC" && "$PY" -c 'import pm; pm.sync_venv(["mcp"], explicit=True)' >/dev/null) \
      || die "could not add the mcp extra to $home (a flaky download? run setup again)"
  fi

  # The gateway, signed in once. A same-named entry replaces the plugin's (which cannot declare OAuth).
  if [[ ! -f "$home/mcp-tokens/$name.json" ]]; then
    echo "Signing in to $url as '$name' (your browser opens; answer the prompts here)."
    # If the sign-in times out and you save the entry anyway, Hermes writes it disabled, and founding
    # would skip it. Keep it enabled; finish the sign-in with `hermes mcp login $name`.
    "$HERMES" mcp add "$name" --url "$url" --auth oauth --connect-timeout 300 || true
    "$HERMES" config set "mcp_servers.$name.enabled" true >/dev/null 2>&1 || true
    [[ -f "$home/mcp-tokens/$name.json" ]] || die "not signed in to '$name' yet: run HERMES_HOME=$home $HERMES mcp login $name, then setup again"
  else
    echo "Already signed in to '$name'."
  fi

  # The company: policy, a profile per role (each linked to the sign-in above), the board.
  "$HERMES" arcade found "$template" ${setting:+"$setting"}
  echo "== $template ready. Open the studio: scripts/studio.sh open"
}

open_studio() {
  command -v rex >/dev/null || die "rex is not installed"
  local sid="" first=1
  for template in "${ORDER[@]}"; do
    local home="$STUDIO/$template"
    [[ -d "$home" ]] || continue
    local slug
    slug="$(sed -n 's/^slug: *//p' "$home/arcade/company.yaml" 2>/dev/null | head -1)"
    # A home's gateway outlives the TUI and keeps the plugin code it started with: restart it.
    HERMES_HOME="$home" "$HERMES" gateway stop >/dev/null 2>&1 || true
    local env=(env "HERMES_HOME=$home")
    local lead=("${env[@]}" "$HERMES")
    local floor=("${env[@]}" node "$ROOT/dashboard/floor_term.js" --fresh)
    # The gate, live: the board's tasks, then one line per Arcade call as the policy decides it.
    local board=(env "HERMES_HOME=$home" "HERMES_BIN=$HERMES" "$PY" -u "$ROOT/scripts/gate_log.py" --board "$slug")
    local out block
    if [[ $first -eq 1 ]]; then
      out="$(rex new arcade-studio --window "$(label "$template")" -c "$home" --json -- "${lead[@]}")"
      sid="$(echo "$out" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')"
      block="$(echo "$out" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["initial_windows"][0]["block_ids"][0])')"
      first=0
    else
      out="$(rex window new -s "$sid" "$(label "$template")" -c "$home" --focus=false --json -- "${lead[@]}")"
      block="$(echo "$out" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["block_ids"][0])')"
    fi
    local fl
    fl="$(rex split -s "$sid" -b "$block" --split=right --ratio 42 --focus=false -- "${floor[@]}")"
    [[ -n "$slug" ]] && rex split -s "$sid" -b "$fl" --split=below --ratio 45 --focus=false --keep-open -- "${board[@]}" >/dev/null
  done
  [[ -n "$sid" ]] || die "no studio homes yet: run scripts/studio.sh setup <template> first"
  rex session rename "$sid" arcade-studio >/dev/null 2>&1 || true
  echo "Rex session $sid (arcade-studio): one window per company."
}

status() {
  for template in "${ORDER[@]}"; do
    local home="$STUDIO/$template"
    if [[ -d "$home" ]]; then
      local signed="not signed in"; ls "$home"/mcp-tokens/*.json >/dev/null 2>&1 && signed="signed in"
      echo "$template: $home ($signed)"
      HERMES_HOME="$home" "$HERMES" arcade status 2>/dev/null | sed -n '2p' | sed 's/^/  /'
    else
      echo "$template: not set up"
    fi
  done
}

case "${1:-}" in
  setup) shift; [[ $# -ge 1 ]] || die "setup <template> [setting] [--gateway-url URL]"; setup "$@";;
  open) open_studio;;
  status) status;;
  *) sed -n '2,15p' "$0"; exit 1;;
esac
