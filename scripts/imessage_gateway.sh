#!/usr/bin/env bash
# Start the spike's Hermes gateway with the BlueBubbles (iMessage) platform, plus the poll bridge.
#
# The BlueBubbles password and the allowed sender are read from their files at runtime and exported
# only into this process tree; nothing is written to any .env and nothing is printed. The webhook
# listener binds 127.0.0.1 only. No tunnels, no public URLs.
#
#   scripts/imessage_gateway.sh          # gateway + bridge in the foreground; Ctrl+C stops both
#
# Quit any TUI first (its auto-started gateway holds the lock and idle-exits ~20s after /quit); the
# TUI reattaches to this gateway when reopened.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HERMES_SRC="${HERMES_SRC:-$HOME/hermes-v0.23.0}"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes-arcade-spike}"
PY="$HERMES_SRC/.venv/bin/python"

pw_file="$HOME/.config/bluebubbles/password"
p2_env="$HOME/arcade-on-phone/.env"
[[ -s "$pw_file" ]] || { echo "missing $pw_file" >&2; exit 1; }
allowed="$(grep -E '^ALLOWED_SENDER_IDS=' "$p2_env" | head -1 | cut -d= -f2- | tr -d "\"' ")"
[[ -n "$allowed" ]] || { echo "ALLOWED_SENDER_IDS missing from $p2_env" >&2; exit 1; }

export BLUEBUBBLES_SERVER_URL="http://127.0.0.1:1234"
BLUEBUBBLES_PASSWORD="$(tr -d '\r\n' < "$pw_file")"
export BLUEBUBBLES_PASSWORD
export BLUEBUBBLES_ALLOWED_USERS="$allowed"
export BLUEBUBBLES_HOME_CHANNEL="${allowed%%,*}"
export BLUEBUBBLES_SEND_READ_RECEIPTS=false
export BLUEBUBBLES_WEBHOOK_HOST=127.0.0.1
export BLUEBUBBLES_WEBHOOK_PORT=8645

"$PY" "$HERE/bluebubbles_bridge.py" &
bridge_pid=$!
trap 'kill "$bridge_pid" 2>/dev/null || true' EXIT INT TERM

cd "$HERMES_SRC"
"$PY" -m hermes_cli.main --profile default gateway run
