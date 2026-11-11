"""shared_principal: every role uses one Arcade identity, roles still govern, and the plugin says so."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import arcade_for_hermes.commands as commands_mod
from arcade_for_hermes.commands import Commands
from arcade_for_hermes.policy import Policy
from arcade_for_hermes.runtime import Runtime

BOWSER = Path(__file__).resolve().parents[1] / "examples" / "bowser" / "policy.yaml"
ME = "founder@example.com"


@pytest.fixture
def shared_policy_path(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(BOWSER.read_text() + f"\nshared_principal: {ME}\n")
    return path


def test_every_role_resolves_to_the_shared_principal(shared_policy_path):
    policy = Policy.load(shared_policy_path)
    assert {policy.principal(r) for r in policy.roles} == {ME}


def test_shared_principal_does_not_widen_any_role(shared_policy_path):
    shared, plain = Policy.load(shared_policy_path), Policy.load(BOWSER)
    assert shared.status_rows()[0]["grants"] == plain.status_rows()[0]["grants"]
    edit = {"document_id": "x", "text_content": "softer"}
    assert not shared.decide("skeptic", "GoogleDocs.InsertTextAtEndOfDocument", edit).allowed


def test_without_the_setting_principals_stay_per_role():
    assert Policy.load(BOWSER).principal("cio") == "bowser/cio"


def _commands(path, tmp_path, monkeypatch):
    calls = []

    def authorize(*, tool_name, user_id):
        calls.append((tool_name, user_id))
        return SimpleNamespace(status="pending", url=f"https://consent/{tool_name}")

    monkeypatch.setattr(commands_mod, "get_client", lambda: SimpleNamespace(tools=SimpleNamespace(authorize=authorize)))
    runtime = Runtime(policy_path=str(path), receipts_path=str(tmp_path / "r.jsonl"))
    return Commands(runtime), calls


def test_connect_asks_once_per_app_when_shared(shared_policy_path, tmp_path, monkeypatch):
    cmds, calls = _commands(shared_policy_path, tmp_path, monkeypatch)
    out = cmds.connect()
    assert sorted(calls) == [("Github.WhoAmI", ME), ("GoogleDocs.WhoAmI", ME)]
    assert "2 link(s)" in out


def test_status_warns_that_arcade_sees_one_user(shared_policy_path, tmp_path, monkeypatch):
    cmds, _ = _commands(shared_policy_path, tmp_path, monkeypatch)
    assert "shared_principal" in cmds.status()
