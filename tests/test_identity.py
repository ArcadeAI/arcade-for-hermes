"""Role detection from the Hermes home. Uses the real hermes_constants when Hermes is importable."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcade_for_hermes import identity
from arcade_for_hermes.policy import Policy

BOWSER = Path(__file__).resolve().parents[1] / "examples" / "bowser" / "policy.yaml"
hermes_constants = pytest.importorskip("hermes_constants")


def test_launch_home_is_default_and_override_is_the_child_profile(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    (home / "profiles" / "cio").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    policy = Policy.load(BOWSER)
    ctx = identity.resolve_role(policy)
    assert ctx.profile == "default" and ctx.role == "cos" and ctx.principal == "bowser/cos"
    token = hermes_constants.set_hermes_home_override(str(home / "profiles" / "cio"))
    try:
        child = identity.resolve_role(policy)
        assert child.profile == "cio" and child.role == "cio" and child.principal == "bowser/cio"
        unknown_token = hermes_constants.set_hermes_home_override(str(home / "profiles" / "intern"))
        try:
            intern = identity.resolve_role(policy)
            assert not intern.ok and "not mapped" in intern.error
        finally:
            hermes_constants.reset_hermes_home_override(unknown_token)
    finally:
        hermes_constants.reset_hermes_home_override(token)
