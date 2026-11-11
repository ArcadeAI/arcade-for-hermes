#!/bin/sh
# Hermes `command` secret source for the BlueBubbles platform (config.yaml: secrets.command).
# Hermes runs this and reads KEY=VALUE lines from stdout into the profile's secret scope, so the
# password is read from its file at runtime and never written to any .env. A multiplexed gateway
# (one with profile routes) ignores os.environ for profile secrets, which is why exports alone
# are not enough. Hermes discards this script's stderr and never logs its stdout.
set -eu
pw_file="$HOME/.config/bluebubbles/password"
p2_env="$HOME/arcade-on-phone/.env"
pw="$(tr -d '\r\n' < "$pw_file")"
allowed="$(grep -E '^ALLOWED_SENDER_IDS=' "$p2_env" | head -1 | cut -d= -f2- | tr -d "\"' ")"
[ -n "$pw" ] && [ -n "$allowed" ] || exit 1
printf 'BLUEBUBBLES_SERVER_URL=http://127.0.0.1:1234\n'
printf 'BLUEBUBBLES_PASSWORD=%s\n' "$pw"
printf 'BLUEBUBBLES_ALLOWED_USERS=%s\n' "$allowed"
printf 'BLUEBUBBLES_HOME_CHANNEL=%s\n' "${allowed%%,*}"
printf 'BLUEBUBBLES_SEND_READ_RECEIPTS=false\n'
printf 'BLUEBUBBLES_WEBHOOK_HOST=127.0.0.1\n'
printf 'BLUEBUBBLES_WEBHOOK_PORT=8645\n'
