"""Snapshot a verb for every tool in the Arcade catalog into data/arcade_verbs.json.

    HERMES_HOME=~/.hermes-arcade-spike ~/hermes-v0.23.0/.venv/bin/python scripts/build_verbs.py

Reads ARCADE_API_KEY (and ARCADE_BASE_URL) from $HERMES_HOME/.env into this process only; never
prints it. Writes {"built": date, "count": n, "toolkits": {...}, "verbs": {"Gmail.SendEmail": "ship", ...}}.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("afh_verbs", ROOT / "verbs.py")
verbs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verbs)


def _load_env() -> None:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()
    env = home / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("ARCADE_API_KEY", "ARCADE_BASE_URL") and not os.environ.get(key.strip()):
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def main() -> None:
    _load_env()
    if not os.environ.get("ARCADE_API_KEY"):
        sys.exit("ARCADE_API_KEY is not set (put it in $HERMES_HOME/.env)")
    from arcadepy import Arcade

    kwargs = {"api_key": os.environ["ARCADE_API_KEY"]}
    if os.environ.get("ARCADE_BASE_URL"):
        kwargs["base_url"] = os.environ["ARCADE_BASE_URL"]
    client = Arcade(**kwargs)
    out: dict[str, str] = {}
    toolkits: dict[str, int] = {}
    offset = 0
    while True:
        page = client.tools.list(limit=250, offset=offset)
        if not page.items:
            break
        for tool in page.items:
            d = tool.model_dump()
            name = d["qualified_name"]
            behavior = ((d.get("metadata") or {}).get("behavior")) or None
            out[name] = verbs.classify(name, behavior)
            tk = (d.get("toolkit") or {}).get("name") or name.split(".")[0]
            toolkits[tk] = toolkits.get(tk, 0) + 1
        offset += len(page.items)
        if offset >= (page.total_count or 0):
            break
    data = {"built": date.today().isoformat(), "count": len(out), "toolkits": dict(sorted(toolkits.items())),
            "verbs": dict(sorted(out.items()))}
    path = ROOT / "data" / "arcade_verbs.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    counts = {v: list(out.values()).count(v) for v in ("look", "draft", "ship")}
    print(f"{len(out)} tools in {len(toolkits)} toolkits -> {path.relative_to(ROOT)}: {counts}")


if __name__ == "__main__":
    main()
