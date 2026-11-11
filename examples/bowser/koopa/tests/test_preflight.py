"""No approval card for an order that cannot happen (a card for an expired proposal was seen live).

Koopa's own pre_tool_call vetoes koopa_execute when the proposal is unknown, tampered, rejected,
expired or already executed; Hermes ranks that block above the Arcade governor's approve.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

BOWSER = Path(__file__).resolve().parents[2]


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("KOOPA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("KOOPA_BROKER", raising=False)
    monkeypatch.syspath_prepend(str(BOWSER))
    for name in [m for m in sys.modules if m == "koopa" or m.startswith("koopa.")]:
        monkeypatch.delitem(sys.modules, name)
    mod = importlib.import_module("koopa")
    mod._desk().reset()
    return mod


def _veto(plugin, proposal_id, hash_):
    return plugin.pre_tool_call(tool_name="koopa_execute", args={"proposal_id": proposal_id, "hash": hash_})


def test_a_fresh_passing_proposal_goes_to_the_human(plugin):
    out = plugin._desk().propose("BTC/USD", 500, "BC-T")
    assert _veto(plugin, out["proposal_id"], out["hash"]) is None


def test_an_expired_proposal_is_blocked_before_any_card(plugin, monkeypatch):
    out = plugin._desk().propose("BTC/USD", 500, "BC-T")
    koopa_mod = sys.modules["koopa.koopa"]
    later = koopa_mod._now() + koopa_mod.PROPOSAL_TTL + timedelta(minutes=1)
    monkeypatch.setattr(koopa_mod, "_now", lambda: later)
    veto = _veto(plugin, out["proposal_id"], out["hash"])
    assert veto["action"] == "block" and "expired" in json.loads(veto["message"])["error"]


@pytest.mark.parametrize("case", ["unknown", "tampered", "rejected", "executed"])
def test_orders_that_cannot_happen_never_ask(plugin, case):
    desk = plugin._desk()
    out = desk.propose("BTC/USD", 12000 if case == "rejected" else 500, "BC-T")
    pid, h = out["proposal_id"], out["hash"]
    if case == "unknown":
        pid = "PR-999"
    elif case == "tampered":
        h = "0" * 16
    elif case == "executed":
        desk.execute(pid, h)
    veto = _veto(plugin, pid, h)
    assert veto and veto["action"] == "block" and json.loads(veto["message"])["approval"] == "not requested"


def test_other_tools_are_untouched(plugin):
    assert plugin.pre_tool_call(tool_name="koopa_propose", args={}) is None


def test_the_ttl_is_four_hours_by_default_and_overridable(monkeypatch):
    koopa_mod = sys.modules.get("koopa.koopa") or importlib.import_module("koopa.koopa")
    monkeypatch.delenv("KOOPA_PROPOSAL_TTL_MINUTES", raising=False)
    assert koopa_mod._ttl() == timedelta(hours=4)
    monkeypatch.setenv("KOOPA_PROPOSAL_TTL_MINUTES", "30")
    assert koopa_mod._ttl() == timedelta(minutes=30)
