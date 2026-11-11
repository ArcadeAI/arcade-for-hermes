#!/usr/bin/env bash
# Open the 8-bit Floor in a Rex tab (falls back to this terminal outside Rex).
#   scripts/floor_rex.sh                       # LIVE
#   scripts/floor_rex.sh --replay BC-2026-003 --speed 4
# Make the pane big (zoom it, or shrink the font) for full detail: 384x108 cells is pixel-perfect.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes-arcade-spike}"
if command -v rex >/dev/null 2>&1 && [[ -n "${REX_SESSION:-}" ]]; then
  exec rex window new -s "$REX_SESSION" Floor -c "$ROOT" -- env HERMES_HOME="$HERMES_HOME" node dashboard/floor_term.js "$@"
fi
exec node "$ROOT/dashboard/floor_term.js" "$@"
