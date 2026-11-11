"""The Alpaca paper broker: paper-only, one order per proposal, and nothing booked when it refuses."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"koopa_{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


koopa, broker = _load("koopa"), _load("broker")
PAPER = {"is_paper": True, "endpoint": broker.PAPER_ENDPOINT, "trading_blocked": False, "account_blocked": False}


class FakeArcade:
    def __init__(self, account):
        self.account, self.calls, self.orders = account, [], {}
        self.tools = self

    def execute(self, *, tool_name, input, user_id):
        self.calls.append((tool_name, user_id))
        if tool_name.endswith("GetAccount"):
            value = self.account
        elif tool_name.endswith("GetOrder"):
            o = next(v for v in self.orders.values() if v["id"] == input["order_id"])
            o.update(status="filled", filled_qty="0.0517", filled_avg_price="75776.90")
            value = o
        else:
            key = input["client_order_id"]
            self.orders.setdefault(key, {"id": f"alp-{len(self.orders) + 1}", "client_order_id": key,
                                         "status": "accepted", "symbol": input["symbol"], "notional": input["notional"]})
            value = self.orders[key]
        return SimpleNamespace(success=True, status="success", output=SimpleNamespace(error=None, value=value))


def _desk(tmp_path, account):
    fake = FakeArcade(account)
    desk = koopa.Desk(tmp_path / "state", ROOT / "fixtures", broker=broker.AlpacaPaperBroker(lambda: fake, "bowser/cos", sleep=lambda s: None))
    desk.reset()
    return desk, fake


def test_an_approved_execute_places_one_paper_order_keyed_by_the_proposal(tmp_path):
    desk, fake = _desk(tmp_path, PAPER)
    p = desk.propose("BTC/USD", 4000, "BC-2026-001")
    first = desk.execute(p["proposal_id"], p["hash"])
    again = desk.execute(p["proposal_id"], p["hash"])
    order = first["fill"]["broker_order"]
    assert first["fill"]["label"] == "ALPACA PAPER" and order["status"] == "filled" and order["notional"] == "4000.00"
    assert order["client_order_id"] == f"koopa-{p['proposal_id']}-{p['hash']}"
    assert again.get("duplicate") is True and len(fake.orders) == 1
    assert [c[0] for c in fake.calls] == ["ArcadeAlpaca.GetAccount", "ArcadeAlpaca.SubmitOrder", "ArcadeAlpaca.GetOrder"]


def test_the_book_takes_the_broker_fill_and_never_spends_more_than_the_notional(tmp_path):
    desk, _ = _desk(tmp_path, PAPER)
    p = desk.propose("BTC/USD", 4000, "BC-2026-001")
    fill = desk.execute(p["proposal_id"], p["hash"])["fill"]
    assert (fill["qty"], fill["price"], fill["book_price_label"]) == (0.0517, 75776.9, "BROKER FILL")
    assert fill["cost_usd"] <= 4000
    report = desk.report()
    assert report["positions"] == {"BTC/USD": 0.0517} and report["reconciliation"]["reconciled"]


@pytest.mark.parametrize("account", [
    {**PAPER, "is_paper": False, "endpoint": "https://api.alpaca.markets"},
    {**PAPER, "endpoint": "https://api.alpaca.markets"},
    {**PAPER, "trading_blocked": True},
    {},
])
def test_no_order_and_nothing_booked_unless_the_account_is_paper_and_open(tmp_path, account):
    desk, fake = _desk(tmp_path, account)
    p = desk.propose("BTC/USD", 4000, "BC-2026-001")
    out = desk.execute(p["proposal_id"], p["hash"])
    assert "nothing booked" in out["error"] and fake.orders == {}
    assert desk.report()["positions"] == {} and desk.report()["fills"] == []


@pytest.mark.parametrize("symbol, tif", [("VTI", "day"), ("BTC/USD", "gtc")])
def test_crypto_orders_use_gtc_and_stocks_use_day(symbol, tif):
    seen = {}

    class Recorder(FakeArcade):
        def execute(self, *, tool_name, input, user_id):
            if tool_name.endswith("SubmitOrder"):
                seen.update(input)
            return super().execute(tool_name=tool_name, input=input, user_id=user_id)

    fake = Recorder(PAPER)
    broker.AlpacaPaperBroker(lambda: fake, "u", sleep=lambda s: None).submit(symbol, 4000, "k1")
    assert seen["time_in_force"] == tif and seen["symbol"] == symbol


def test_a_rejected_proposal_never_reaches_the_broker(tmp_path):
    desk, fake = _desk(tmp_path, PAPER)
    p = desk.propose("BTC/USD", 12000, "BC-2026-001")
    assert "error" in desk.execute(p["proposal_id"], p["hash"]) and fake.calls == []


@pytest.mark.parametrize("value, expected", [("", None), ("mock", None), ("alpaca", "ALPACA PAPER")])
def test_broker_is_off_unless_asked_for(monkeypatch, value, expected):
    monkeypatch.setenv("KOOPA_BROKER", value)
    got = broker.from_env()
    assert (got.name if got else None) == expected


def test_an_unknown_broker_fails_closed(monkeypatch):
    monkeypatch.setenv("KOOPA_BROKER", "live")
    with pytest.raises(broker.BrokerRefused):
        broker.from_env()
