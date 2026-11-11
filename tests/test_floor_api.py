"""The Floor's read-only API: what the 8-bit tab may see of the receipts, and nothing more."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("floor_api", ROOT / "dashboard" / "plugin_api.py")
api = importlib.util.module_from_spec(spec)
sys.modules["floor_api"] = api
spec.loader.exec_module(api)

RECEIPT = {
    "v": 1, "id": "abc123", "ts": "2026-11-08T07:41:04Z", "action_key": "arcade:3b7f", "role": "reporter",
    "profile": "default", "via": "cos", "principal": "thierry@brisedemer.io", "tool": "Github.UpdateIssue",
    "toolkit": "github", "verb": "ship", "decision": "approved", "outcome": "ok", "work_order": "BC-2026-003",
    "reason": "reporter may ship on github", "url": "https://github.com/x/y/issues/3", "task_id": "t", "session_id": "s",
    "input": {"owner": "thierry-brise", "repo": "bowser-capital-desk", "issue_number": 3, "state": "closed",
              "body": "a long private body " * 20},
    "approver": {"choice": "once", "decided_by": "human", "surface": "gateway",
                 "session_key": "agent:main:bluebubbles:dm:any;-;+15550001111"},
}


def test_an_event_carries_what_the_floor_draws_and_no_identity_or_link(tmp_path):
    path = tmp_path / "receipts.jsonl"
    path.write_text(json.dumps(RECEIPT) + "\n")
    (e,) = api.read_events(path)
    assert e["seq"] == 1 and e["key"] == "arcade:3b7f" and e["via"] == "cos" and e["decision"] == "approved"
    assert e["input"] == {"issue_number": "3", "state": "closed"}
    assert e["approver"] == {"choice": "once", "decided_by": "human", "surface": "gateway"}
    flat = json.dumps(e)
    for leaked in ("brisedemer", "+1555", "github.com", "session_key", "private body", "task_id"):
        assert leaked not in flat


def test_events_after_a_seq_and_by_work_order(tmp_path):
    path = tmp_path / "receipts.jsonl"
    rows = [dict(RECEIPT, id=str(i), work_order="A" if i % 2 else "B") for i in range(1, 6)]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    assert [e["id"] for e in api.read_events(path, after=3)] == ["4", "5"]
    assert [e["id"] for e in api.read_events(path, work_order="B")] == ["2", "4"]
    assert [w["work_order"] for w in api.work_orders(path)] and {w["events"] for w in api.work_orders(path)} == {3, 2}


def test_waiting_drops_stale_entries_and_trims_inputs(tmp_path):
    path = tmp_path / "waiting.json"
    now = time.time()
    path.write_text(json.dumps({
        "k1": {"role": "cos", "tool": "koopa_execute", "since": now, "input": {"proposal_id": "PR-1", "hash": "h"}},
        "k2": {"role": "cos", "tool": "koopa_execute", "since": now - 3600},
    }))
    (w,) = api.read_waiting(path)
    assert w["key"] == "k1" and w["input"] == {"proposal_id": "PR-1"}


def test_the_book_values_positions_at_fixture_prices(tmp_path):
    (tmp_path / "account.json").write_text(json.dumps({
        "label": "PAPER MODE", "cash_usd": 6000, "positions": {"BTC/USD": 0.01, "ETH/USD": 0},
        "prices": {"BTC/USD": {"price": 75000}, "ETH/USD": {"price": 2000}}}))
    (tmp_path / "ledger.jsonl").write_text(json.dumps({"kind": "fill", "ts": "t", "fill": {"symbol": "BTC/USD", "qty": 0.01}}) + "\n")
    b = api.read_book(tmp_path)
    assert b["book_usd"] == 6750.0 and b["positions"] == {"BTC/USD": 0.01} and b["fills"] == 1
    assert api.read_book(tmp_path / "missing") is None


def test_activity_is_trimmed_and_read_after_n(tmp_path):
    path = tmp_path / "activity.jsonl"
    rows = [{"n": 10, "kind": "think", "role": "cio", "profile": "cio", "secret": "x"},
            {"n": 11, "kind": "say", "role": "cio", "profile": "cio", "text": "word " * 60},
            {"n": 12, "kind": "tool", "role": "cos", "profile": "default", "tool": "delegate_task"}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    acts = api.read_activity(path, after=10)
    assert [a["n"] for a in acts] == [11, 12] and len(acts[0]["text"]) <= 96
    assert "secret" not in json.dumps(api.read_activity(path))
