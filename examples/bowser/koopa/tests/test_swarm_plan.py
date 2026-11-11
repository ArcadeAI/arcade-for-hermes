"""The swarm plan: the requested size, every profile maps to a real role, analysts cover the allow-list."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("swarm", ROOT / "swarm.py")
swarm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(swarm)


def test_a_hundred_profiles_split_into_four_roles_and_cover_every_symbol():
    plan = swarm.plan(100)
    assert len(plan) == 100 and len({p for p, _, _ in plan}) == 100
    roles = {r for _, r, _ in plan}
    assert roles == {"analyst", "skeptic", "risk", "reporter"}
    allow = json.loads((ROOT / "koopa" / "fixtures" / "account.json").read_text())["allowlist"]
    assert {c for _, r, c in plan if r == "analyst"} == set(allow)
    assert all(p.startswith(r + "-") for p, r, _ in plan)
