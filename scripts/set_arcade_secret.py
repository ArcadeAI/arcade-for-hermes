#!/usr/bin/env python3
"""Store a toolkit secret in Arcade (POST /v1/admin/secrets/{key}) without the value touching chat,
a file, or shell history: you type it into a hidden prompt.

    ! python3 ~/arcade-for-hermes/scripts/set_arcade_secret.py DAYTONA_API_KEY

The Arcade project is the one whose ARCADE_API_KEY sits in HERMES_HOME/.env (default
~/.hermes-arcade-spike). Prints the HTTP status and nothing else from the request or the response.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


def arcade_key() -> str:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes-arcade-spike").expanduser()
    for line in (home / ".env").read_text().splitlines():
        if line.startswith("ARCADE_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"no ARCADE_API_KEY in {home / '.env'}")


def main() -> None:
    if len(sys.argv) != 2 or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", sys.argv[1]):
        raise SystemExit("usage: set_arcade_secret.py SECRET_NAME   (e.g. DAYTONA_API_KEY)")
    name = sys.argv[1]
    value = getpass.getpass(f"{name} (hidden): ").strip()
    if not value:
        raise SystemExit("nothing entered; nothing sent")
    req = urllib.request.Request(
        f"https://api.arcade.dev/v1/admin/secrets/{name}", method="POST",
        data=json.dumps({"value": value, "description": "set from arcade-for-hermes"}).encode(),
        # a named client: Cloudflare in front of the API refuses Python's default User-Agent (error 1010)
        headers={"Authorization": f"Bearer {arcade_key()}", "Content-Type": "application/json",
                 "User-Agent": "arcade-for-hermes/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"{name}: stored (HTTP {resp.status})")
    except urllib.error.HTTPError as exc:
        print(f"{name}: not stored (HTTP {exc.code})")
        sys.exit(1)


if __name__ == "__main__":
    main()
