"""Money limits, exits and the kill switch: what traders asked for (alpaca-mcp-server #60, #62, #130,
#134). Offline: no network, no keys, no Hermes runtime."""

from __future__ import annotations

import json
import time

import pytest

from arcade_for_hermes import hooks as hooks_mod
from arcade_for_hermes.guard import HaltSwitch, spent_today
from arcade_for_hermes.hooks import Governor
from arcade_for_hermes.identity import RoleContext
from arcade_for_hermes.policy import Policy, PolicyError
from arcade_for_hermes.receipts import ReceiptStore
from arcade_for_hermes.runtime import Runtime

DESK = {
    "version": 1, "default": "deny", "principal_prefix": "desk",
    "toolkits": {"alpaca": ["ArcadeAlpaca"]},
    "profile_roles": {"default": "trader"},
    "rules": [
        {"tool": "ArcadeAlpaca.GetAccount", "verb": "look"},
        {"tool": "ArcadeAlpaca.ClosePosition", "verb": "ship", "exit": True},
        {"tool": "ArcadeAlpaca.CancelOrder", "verb": "ship", "exit": True},
        {"tool": "ArcadeAlpaca.SubmitOrder", "verb": "ship", "amount": "notional"},
        {"tool": "ArcadeAlpaca.CreateWatchlist", "verb": "draft"},
    ],
    "roles": {
        "trader": {"grants": [{"toolkit": "alpaca", "verbs": ["look", "draft", "ship"]}],
                   "limits": {"per_call": 500, "per_day": 1000}},
        "founder": {"grants": [{"toolkit": "alpaca", "verbs": ["look", "draft", "ship"]}]},
    },
}


@pytest.fixture
def desk() -> Policy:
    return Policy.from_dict(DESK)


def order(n):
    return {"symbol": "BTC/USD", "side": "buy", "notional": n}


def test_an_order_under_the_limit_still_goes_to_the_card(desk):
    d = desk.decide("trader", "ArcadeAlpaca.SubmitOrder", order(400))
    assert d.allowed and d.requires_approval and d.amount == 400


def test_an_order_over_the_per_call_limit_never_reaches_the_card(desk):
    d = desk.decide("trader", "ArcadeAlpaca.SubmitOrder", order(12000))
    assert not d.allowed and "per-call limit of 500.00" in d.reason


def test_the_daily_limit_counts_what_already_ran(desk):
    assert desk.decide("trader", "ArcadeAlpaca.SubmitOrder", order(400), spent_today=500).allowed
    d = desk.decide("trader", "ArcadeAlpaca.SubmitOrder", order(400), spent_today=700)
    assert not d.allowed and "daily limit of 1,000.00" in d.reason


def test_an_unreadable_amount_fails_closed(desk):
    for bad in (None, "lots", True, -5, float("nan")):
        d = desk.decide("trader", "ArcadeAlpaca.SubmitOrder", {"symbol": "BTC/USD", "notional": bad})
        assert not d.allowed and "no readable amount" in d.reason
    assert desk.decide("trader", "ArcadeAlpaca.SubmitOrder", {"symbol": "BTC/USD", "notional": "$1,200.50"}).amount == 1200.5


def test_a_role_without_limits_is_not_capped_but_still_needs_the_card(desk):
    d = desk.decide("founder", "ArcadeAlpaca.SubmitOrder", order(12000))
    assert d.allowed and d.requires_approval


def test_halt_stops_drafts_and_ships_but_never_reads_or_exits(desk):
    halted = "market went weird"
    buy = desk.decide("trader", "ArcadeAlpaca.SubmitOrder", order(10), halted=halted)
    assert not buy.allowed and "halted by the founder (market went weird)" in buy.reason
    assert not desk.decide("trader", "ArcadeAlpaca.CreateWatchlist", {}, halted=halted).allowed
    assert desk.decide("trader", "ArcadeAlpaca.GetAccount", {}, halted=halted).allowed
    close = desk.decide("trader", "ArcadeAlpaca.ClosePosition", {"symbol": "BTC/USD"}, halted=halted)
    assert close.allowed and close.requires_approval   # exits run, and still ask
    cancel = desk.decide("trader", "ArcadeAlpaca.CancelOrder", {"order_id": "x"}, halted=halted)
    assert cancel.allowed


def test_limits_reject_bad_config():
    with pytest.raises(PolicyError):
        Policy.from_dict({**DESK, "roles": {"trader": {"grants": [], "limits": {"per_week": 5}}}})
    with pytest.raises(PolicyError):
        Policy.from_dict({**DESK, "roles": {"trader": {"grants": [], "limits": {"per_call": "lots"}}}})
    with pytest.raises(PolicyError):
        Policy.from_dict({**DESK, "rules": [{"tool": "ArcadeAlpaca.SubmitOrder", "verb": "ship", "amount": 5}]})


def test_halt_switch_round_trip_and_an_unreadable_file_counts_as_halted(tmp_path):
    switch = HaltSwitch(tmp_path / "halt.json")
    assert switch.reason() is None
    switch.halt("flash crash")
    assert switch.reason() == "flash crash"
    assert switch.resume() and switch.reason() is None and not switch.resume()
    (tmp_path / "halt.json").write_text("{not json")
    assert switch.reason() == "halt file unreadable"


def test_spent_today_counts_only_this_roles_calls_that_ran_today(tmp_path):
    store = ReceiptStore(tmp_path / "r.jsonl")
    store.append(role="trader", decision="approved", outcome="ok", amount=300)
    store.append(role="trader", decision="allowed", outcome="ok", amount=50)
    store.append(role="trader", decision="denied", outcome="not_run", amount=9000)
    store.append(role="trader", decision="approved", outcome="error", amount=700)
    store.append(role="founder", decision="approved", outcome="ok", amount=5000)
    assert spent_today(store, "trader") == 350
    assert spent_today(store, "trader", now=time.time() + 2 * 86400) == 0


@pytest.fixture
def gate(tmp_path, monkeypatch):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(DESK))
    runtime = Runtime(policy_path=str(path), receipts_path=str(tmp_path / "receipts.jsonl"), cron_check=lambda: False)
    policy = runtime.policies.get()
    monkeypatch.setattr(hooks_mod, "resolve_role",
                        lambda _p: RoleContext("trader", "trader", policy.principal("trader"), "/tmp/h"))
    return runtime, Governor(runtime)


def _run(gov, args, result='{"ok": true}'):
    directive = gov.pre_tool_call(tool_name="arcade_execute", args=args)
    blocked = isinstance(directive, dict) and directive.get("action") == "block"
    gov.post_tool_call(tool_name="arcade_execute", args=args, result=result,
                       status="blocked" if blocked else None, error_message=directive.get("message") if blocked else None)
    return directive


def test_the_gate_counts_receipts_toward_the_daily_limit(gate):
    runtime, gov = gate
    first = {"tool": "ArcadeAlpaca.SubmitOrder", "input": order(450)}
    assert _run(gov, first)["action"] == "approve"          # card raised; Hermes runs it after the founder's yes
    assert runtime.receipts.read()[0]["amount"] == 450
    second = {"tool": "ArcadeAlpaca.SubmitOrder", "input": order(450), "work_order": "W2"}
    assert _run(gov, second)["action"] == "approve"         # 900 of 1,000
    third = {"tool": "ArcadeAlpaca.SubmitOrder", "input": order(450), "work_order": "W3"}
    directive = _run(gov, third)
    assert directive["action"] == "block" and "daily limit" in directive["message"]
    assert runtime.receipts.read()[0]["decision"] == "denied"


def test_the_kill_switch_blocks_at_the_gate_and_lets_exits_through(gate):
    runtime, gov = gate
    runtime.halt.halt("going to dinner")
    directive = _run(gov, {"tool": "ArcadeAlpaca.SubmitOrder", "input": order(10)})
    assert directive["action"] == "block" and "going to dinner" in directive["message"]
    assert _run(gov, {"tool": "ArcadeAlpaca.ClosePosition", "input": {"symbol": "BTC/USD"}})["action"] == "approve"
    runtime.halt.resume()
    assert _run(gov, {"tool": "ArcadeAlpaca.SubmitOrder", "input": order(10), "work_order": "W9"})["action"] == "approve"
