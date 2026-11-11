"""Koopa's three tests, and only three: oversize rejected; duplicate execute is one fill; altered hash executes nothing."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("koopa_mod", ROOT / "koopa.py")
koopa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(koopa)


@pytest.fixture
def desk(tmp_path):
    d = koopa.Desk(tmp_path / "state", ROOT / "fixtures")
    d.reset()
    return d


def test_oversize_proposal_is_rejected_with_reasons(desk):
    out = desk.propose("BTC/USD", 12000, "BC-2026-001")
    assert out["decision"] == "REJECT" and out["proposal_id"] == "PR-001" and out["label"] == "PAPER MODE"
    assert any("exceeds cash" in r for r in out["reasons"]) and any("40%" in r for r in out["reasons"])
    executed = desk.execute(out["proposal_id"], out["hash"])
    assert "error" in executed and desk.report()["positions"] == {}


def test_duplicate_execute_returns_the_same_order_and_one_fill(desk):
    out = desk.propose("BTC/USD", 4000, "BC-2026-001")
    assert out["decision"] == "PASS"
    first = desk.execute(out["proposal_id"], out["hash"], "BC-2026-001")
    second = desk.execute(out["proposal_id"], out["hash"], "BC-2026-001")
    assert first["order_id"] == "ORD-001" and first["fill"]["label"] == "MOCK"
    assert second["order_id"] == "ORD-001" and second.get("duplicate") is True
    report = desk.report()
    price = desk.report()["prices"]["BTC/USD"]["price"]
    assert len(report["fills"]) == 1 and report["positions"] == {"BTC/USD": round(4000 / price, 4)}
    assert abs(report["cash_usd"] - 6000.0) < 5 and report["reconciliation"]["reconciled"] is True


def test_altered_hash_is_rejected_and_nothing_executes(desk):
    out = desk.propose("BTC/USD", 4000)
    bad = desk.execute(out["proposal_id"], out["hash"][::-1])
    assert "hash does not match" in bad["error"]
    report = desk.report()
    assert report["positions"] == {} and report["cash_usd"] == 10000.0 and report["fills"] == []
