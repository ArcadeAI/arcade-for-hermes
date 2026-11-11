"""Grow Bowser Capital into a swarm of Hermes profiles that share a handful of roles.

    HERMES_HOME=~/.hermes-arcade-spike python examples/bowser/swarm.py 100 [--model anthropic/claude-haiku-5.5]

Creates analyst-NNN (split across Koopa's allow-list), skeptic-NN, risk-NN and reporter-NN profiles,
each on the given model, with both plugins linked, its role's SOUL.md plus its coverage, and the
main profile's ARCADE_API_KEY and OPENROUTER_API_KEY copied in (never printed). Then lists every
swarm profile under `delegation.backends.profile_routes` and sets `max_concurrent_children`.

The policy needs no change at any size: `"analyst-*": analyst` and friends map every profile to
its role, so a hundred agents still hold exactly the grants of four roles.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_DIR = HERE.parents[1]
KEYS = ("ARCADE_API_KEY", "OPENROUTER_API_KEY")


def plan(n: int) -> list[tuple[str, str, str]]:
    """(profile, role, coverage) for a swarm of n: ~84% analysts, ~12% skeptics, 3% risk, 1 reporter."""
    allow = json.loads((HERE / "koopa" / "fixtures" / "account.json").read_text())["allowlist"]
    reporters = 1
    risk = max(1, round(n * 0.03))
    skeptics = max(1, round(n * 0.12))
    analysts = max(1, n - reporters - risk - skeptics)
    out = [(f"analyst-{i:03d}", "analyst", allow[(i - 1) % len(allow)]) for i in range(1, analysts + 1)]
    out += [(f"skeptic-{i:02d}", "skeptic", "") for i in range(1, skeptics + 1)]
    out += [(f"risk-{i:02d}", "risk", "") for i in range(1, risk + 1)]
    out += [(f"reporter-{i:02d}", "reporter", "") for i in range(1, reporters + 1)]
    return out


def _env_lines(home: Path) -> str:
    lines = (home / ".env").read_text().splitlines() if (home / ".env").exists() else []
    return "".join(f"{line}\n" for line in lines if line.split("=", 1)[0] in KEYS)


def _write_config(path: Path, model: str) -> None:
    from ruamel.yaml import YAML

    yaml = YAML()
    data = yaml.load(path.read_text()) if path.exists() else {}
    data = data or {}
    data.setdefault("model", {})
    data["model"]["provider"] = "openrouter"
    data["model"]["default"] = model
    plugins = data.setdefault("plugins", {})
    enabled = list(plugins.get("enabled") or [])
    for name in ("arcade-for-hermes", "koopa"):
        if name not in enabled:
            enabled.append(name)
    plugins["enabled"] = enabled
    plugins.setdefault("disabled", [])
    with path.open("w") as fh:
        yaml.dump(data, fh)


def make_profile(home: Path, hermes: str, name: str, role: str, coverage: str, model: str, env: str) -> str:
    ph = home / "profiles" / name
    if not ph.exists():
        subprocess.run([hermes, "profile", "create", name, "--no-alias", "--description", f"Bowser Capital {role}"],
                       env={**os.environ, "HERMES_HOME": str(home)}, check=True, capture_output=True)
    (ph / "plugins").mkdir(parents=True, exist_ok=True)
    for link, target in (("arcade-for-hermes", PLUGIN_DIR), ("koopa", HERE / "koopa")):
        dest = ph / "plugins" / link
        if dest.is_symlink() or dest.exists():
            dest.unlink() if dest.is_symlink() else shutil.rmtree(dest)
        dest.symlink_to(target)
    soul = (HERE / "souls" / f"{role}.md").read_text()
    if coverage:
        soul += f"\nYour coverage: {coverage}. Propose only {coverage}; size it from your own read of the book.\n"
    (ph / "SOUL.md").write_text(soul)
    existing = (ph / ".env").read_text() if (ph / ".env").exists() else ""
    keep = "".join(f"{line}\n" for line in existing.splitlines() if line.split("=", 1)[0] not in KEYS)
    (ph / ".env").write_text(keep + env)
    _write_config(ph / "config.yaml", model)
    return name


def write_routes(home: Path, profiles: list[tuple[str, str, str]], concurrency: int) -> None:
    from ruamel.yaml import YAML

    yaml = YAML()
    path = home / "config.yaml"
    data = yaml.load(path.read_text()) or {}
    delegation = data.setdefault("delegation", {})
    delegation["backend"] = "profile_routes"
    delegation["max_concurrent_children"] = concurrency
    routes = delegation.setdefault("backends", {}).setdefault("profile_routes", {})
    base = [p for p in (routes.get("profiles") or []) if not str(p.get("name", "")).startswith(("analyst-", "skeptic-", "risk-", "reporter-"))]
    words = {"analyst": "analyst", "skeptic": "skeptic", "risk": "risk officer", "reporter": "reporter"}
    swarm = [{"name": n, "description": f"{words[r]}{' ' + c if c else ''}"} for n, r, c in profiles]
    routes["profiles"] = base + swarm
    with path.open("w") as fh:
        yaml.dump(data, fh)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("n", type=int, nargs="?", default=100)
    ap.add_argument("--model", default="anthropic/claude-haiku-5.5")
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--hermes", default=shutil.which("hermes") or "hermes")
    args = ap.parse_args()
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()
    env = _env_lines(home)
    if not all(k in env for k in KEYS):
        raise SystemExit(f"{home}/.env must hold {', '.join(KEYS)} first")
    profiles = plan(args.n)
    with ThreadPoolExecutor(max_workers=8) as pool:
        done = list(pool.map(lambda p: make_profile(home, args.hermes, p[0], p[1], p[2], args.model, env), profiles))
    write_routes(home, profiles, args.concurrency)
    counts: dict[str, int] = {}
    for _, role, _ in profiles:
        counts[role] = counts.get(role, 0) + 1
    print(f"swarm: {len(done)} profiles on {args.model} in {home}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    print(f"delegation: profile_routes lists them; max_concurrent_children={args.concurrency}")
    # Plugins are enabled by writing each profile's config, which a running gateway does not watch:
    # without a restart, new profiles' subagents start with no arcade or koopa tools at all.
    print("restart the gateway (quit hermes --tui and wait for it to exit) so new profiles load their plugins")


if __name__ == "__main__":
    main()
