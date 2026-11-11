#!/usr/bin/env bash
# Local spike for Arcade for Hermes: the parts that need a person at a keyboard or a phone.
# Run on your own machine with Hermes v0.23.0 installed. Nothing here touches the cloud session.
#
#   bash scripts/local_spike.sh prepare     # test home, role profiles, policy, plugin, model config
#   bash scripts/local_spike.sh connect     # print the Arcade consent links (one per role per app)
#   bash scripts/local_spike.sh offline     # spike checks that need no human: deny, fail-closed, role
#   bash scripts/local_spike.sh tui         # spike check c: the approval card in `hermes --tui`
#
# Set ARCADE_API_KEY and OPENROUTER_API_KEY in your shell before `prepare`; they are copied into the
# test home's .env files (never printed).
set -eu

PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export HERMES_HOME="${ARCADE_SPIKE_HOME:-$HOME/.hermes-arcade-spike}"
MODEL="${ARCADE_SPIKE_MODEL:-anthropic/claude-sonnet-5.5}"   # gpt-4.1-mini could not call deferred plugin tools
ROLES="cio skeptic reporter"

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 1; }; }

prepare() {
  need hermes
  : "${ARCADE_API_KEY:?set ARCADE_API_KEY in your shell first}"
  : "${OPENROUTER_API_KEY:?set OPENROUTER_API_KEY in your shell first (or edit MODEL/provider below)}"
  mkdir -p "$HERMES_HOME/plugins" "$HERMES_HOME/arcade"
  echo "Test home: $HERMES_HOME"
  for p in $ROLES; do
    hermes profile create "$p" --no-alias --description "Bowser Capital $p" >/dev/null 2>&1 || true
  done
  for d in "$HERMES_HOME" "$HERMES_HOME"/profiles/*; do
    touch "$d/.env"
    grep -q '^ARCADE_API_KEY=' "$d/.env" || printf 'ARCADE_API_KEY=%s\n' "$ARCADE_API_KEY" >> "$d/.env"
    grep -q '^OPENROUTER_API_KEY=' "$d/.env" || printf 'OPENROUTER_API_KEY=%s\n' "$OPENROUTER_API_KEY" >> "$d/.env"
    mkdir -p "$d/plugins"
    ln -sfn "$PLUGIN_DIR" "$d/plugins/arcade-for-hermes"
    HERMES_HOME="$d" hermes config set model.provider openrouter >/dev/null
    HERMES_HOME="$d" hermes config set model.default "$MODEL" >/dev/null
    yes 2>/dev/null | HERMES_HOME="$d" hermes plugins enable arcade-for-hermes | tail -1
  done
  cp "$PLUGIN_DIR/examples/bowser/policy.yaml" "$HERMES_HOME/arcade/policy.yaml"
  hermes plugins install advanced-delegation --enable --yes-deps | tail -2
  python3 - "$HERMES_HOME/config.yaml" <<'PY'
import sys, re
path = sys.argv[1]
text = open(path).read()
if "profile_routes" not in text:
    text += """
delegation:
  backend: profile_routes
  backends:
    profile_routes:
      profiles:
        - {name: cio, description: "Chief Investment Officer: researches and drafts the thesis memo."}
        - {name: skeptic, description: "Challenges the thesis; files dissents as comments."}
        - {name: reporter, description: "Writes the daily brief and asks to close the work order."}
"""
    open(path, "w").write(text)
PY
  hermes plugins validate "$PLUGIN_DIR" --install-deps | tail -3
  hermes plugins doctor "$PLUGIN_DIR" --ci | tail -2
  echo "prepared. Next: bash scripts/local_spike.sh connect"
}

connect() {
  need hermes
  hermes arcade connect
}

offline() {
  need hermes
  hermes arcade status
  echo
  echo "Policy denial (skeptic may not edit docs) and fail-closed ship, through Hermes's own dispatch:"
  python3 - <<'PY'
import json, os
import model_tools
from hermes_cli.plugins import discover_plugins
discover_plugins()
from tools.delegate_tool_routes import delegated_profile_scope
from hermes_cli.profiles import get_profile_dir
def call(label, name, args):
    r = model_tools.handle_function_call(name, args, task_id="spike")
    print(f"[{label}] {r[:300]}")
with delegated_profile_scope(get_profile_dir("cio")):
    call("cio whoami", "arcade_whoami", {})
with delegated_profile_scope(get_profile_dir("skeptic")):
    call("skeptic docs edit (expect DENIED)", "arcade_execute", {"tool": "GoogleDocs.InsertTextAtEndOfDocument", "input": {"document_id": "x", "text_content": "softer"}, "work_order": "BC-2026-001"})
PY
  hermes arcade audit BC-2026-001
}

tui() {
  need hermes
  cat <<'TXT'
Spike check c: the approval card from a routed child.

1. This opens `hermes --tui`. Paste the prompt below. The main session delegates to the reporter
   profile, which tries to close issue #1 (a ship action). Inside the subagent the plugin answers
   HANDOFF (a background child cannot reach the card in Hermes v0.23.0); the main session then
   re-issues the call with on_behalf_of: reporter and you see "SHIP: reporter (...) via cos wants
   Github.UpdateIssue ...". Answer Deny: nothing is written, the audit shows denied, approver deny.
2. Repeat and answer Once: the issue closes and the receipt shows approved/once, role reporter via cos.
3. For the phone: run `hermes gateway` with Telegram configured and send the same prompt there.
   If a stale gateway from an earlier run holds old plugin code, it exits after 10 idle minutes.

Prompt:
  Delegate this to the reporter profile: use arcade_execute with tool Github.UpdateIssue and input
  {"owner": "<your-login>", "repo": "<a test repo>", "issue_number": 1, "state": "closed"} and
  work_order BC-2026-001. Report the exact tool result back to me. When the result says HANDOFF,
  make that exact arcade_execute call yourself.

Without the hand-back, every surface auto-denies a background child's approval with no card
(Hermes default for subagents). The card always comes from the main session.
TXT
  read -r -p "Press Enter to start hermes --tui..." _
  hermes --tui
}

case "${1:-}" in
  prepare) prepare ;;
  connect) connect ;;
  offline) offline ;;
  tui) tui ;;
  *) sed -n 2,12p "$0"; exit 1 ;;
esac
