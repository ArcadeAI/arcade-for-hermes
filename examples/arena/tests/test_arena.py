"""The arena desk holds every order to the founder's mandate and scores half activity, half money."""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena import desk  # noqa: E402


@pytest.fixture
def root(tmp_path):
    desk.new_match(tmp_path, 10_000, "go chaos mode", 5, {"red": "m1", "blue": "m2"}, seed=7)
    return tmp_path


def test_plain_words_pick_a_style():
    assert desk.style_from_words("steady saving please") == "steady"
    assert desk.style_from_words("YOLO it") == "chaos"
    assert desk.style_from_words("be a bit aggressive") == "risky"
    assert desk.style_from_words("whatever you think") == "balanced"


def test_a_buy_inside_the_mandate_fills_and_pays_the_fee(root):
    r = desk.trade(root, "red", "btc/usd", "buy", 2000, "momentum")
    assert r["filled"] and r["fee_usd"] == 2.0 and r["cash_usd"] == 7998.0
    s = desk.standings(root)["red"]
    assert s["trades"] == 1 and s["pnl"] == -2.0 and s["activity"] > 0


def test_the_mandate_caps_refuse_with_reasons_and_trade_nothing(root):
    assert "order cap" in desk.trade(root, "red", "BTC/USD", "buy", 6000, "all in")["reasons"][0]
    assert "long only" in desk.trade(root, "red", "ETH/USD", "sell", 100, "short it")["reasons"][0]
    assert "not traded here" in desk.trade(root, "red", "PEPE/USD", "buy", 100, "")["reasons"][0]
    assert desk.trade(root, "red", "SOL/USD", "buy", 1000, "")["filled"]
    assert "cooldown" in desk.trade(root, "red", "SOL/USD", "buy", 1000, "again")["reasons"][0]
    book = json.loads((root / "red" / "book.json").read_text())
    assert book["trades"] == 1 and book["refused"] == 4


def test_teams_have_separate_books_and_the_match_ends(root):
    desk.trade(root, "red", "BTC/USD", "buy", 1000, "")
    assert desk.standings(root)["blue"]["cash"] == 10_000
    m = json.loads((root / "match.json").read_text())
    m["ends_at"] = time.time() - 1
    (root / "match.json").write_text(json.dumps(m))
    assert "the match is over" in desk.trade(root, "blue", "BTC/USD", "buy", 100, "")["reasons"]


def test_the_market_moves_and_the_score_follows(root):
    desk.trade(root, "red", "DOGE/USD", "buy", 5000, "")
    before = desk.standings(root)["red"]["value"]
    rng = random.Random(1)
    for _ in range(30):
        desk.tick_market(root, rng, 0.005)
    after = desk.standings(root)["red"]
    assert after["value"] != before and 0 <= after["score"] <= 100


def test_a_sell_round_trip_closes_the_position(root, monkeypatch):
    desk.trade(root, "blue", "ETH/USD", "buy", 1000, "")
    book = json.loads((root / "blue" / "book.json").read_text())
    book["last_trade_at"] = 0
    (root / "blue" / "book.json").write_text(json.dumps(book))
    r = desk.trade(root, "blue", "ETH/USD", "sell", 1000, "take it off")
    assert r["filled"] and "ETH/USD" not in json.loads((root / "blue" / "book.json").read_text())["positions"]


def test_a_chaos_gain_does_not_pin_the_money_half():
    # the last chaos match ended 100 to 100 at +17.7% and +14.5%: the wider span keeps them apart
    match = {"budget": 10_000, "caps": desk.PRESETS["chaos"]}
    prices = {"BTC/USD": 1.0}
    big = desk.score(match, {"cash": 11_768, "positions": {}, "trades": 30}, prices)
    small = desk.score(match, {"cash": 11_446, "positions": {}, "trades": 48}, prices)
    assert big["money"] < 50 and small["money"] < big["money"]
    steady = desk.score({"budget": 10_000, "caps": desk.PRESETS["steady"]}, {"cash": 10_500, "positions": {}, "trades": 4}, prices)
    assert steady["money"] == 50


def test_desk_talk_reaches_the_team_and_never_the_rival(root):
    assert desk.note(root, "red", "red-analyst-1", "  SOL up, buy $2k ", "sol", "BUY")["ok"]
    assert not desk.note(root, "red", "red-skeptic", "   ")["ok"]
    talk = desk.market_view(root, "red")["desk_talk"]
    assert talk[-1]["who"] == "red-analyst-1" and talk[-1]["text"] == "SOL up, buy $2k"
    assert talk[-1]["symbol"] == "SOL/USD" and talk[-1]["side"] == "buy"
    assert desk.market_view(root, "blue")["desk_talk"] == []


def test_a_fill_records_which_seat_traded(root):
    desk.trade(root, "red", "BTC/USD", "buy", 500, "the AN1 call", who="red-cio")
    rows = [json.loads(l) for l in (root / "trades.jsonl").read_text().splitlines()]
    assert rows[-1]["who"] == "red-cio" and rows[-1]["ok"]


def test_margin_adds_cash_and_debt_and_the_exchange_caps_it(root):
    before = desk.standings(root)["red"]["value"]
    out = desk.borrow(root, "red", 5000, "lever up", who="red-cio-raw")
    assert out["borrowed"] and out["debt"] == 5000
    after = desk.standings(root)["red"]
    assert after["cash"] == 15000 and after["debt"] == 5000 and abs(after["value"] - before) < 0.01
    assert not desk.borrow(root, "red", 16_000, "more")["borrowed"]   # 2x budget is the exchange's line


def test_the_witness_records_what_arcade_would_have_stopped_and_blocks_nothing(root, tmp_path, monkeypatch):
    import shutil
    import hermes_constants
    import arena as plugin

    home = tmp_path / "home"
    (home / "arcade").mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[2] / "bowser" / "policy.yaml", home / "arcade" / "policy.yaml")
    monkeypatch.setattr(hermes_constants, "get_process_hermes_home", lambda: home)
    monkeypatch.setenv("ARENA_DIR", str(root))
    monkeypatch.setattr(plugin, "_profile", lambda: "blue-analyst-1-raw")
    out = json.loads(plugin.arena_trade({"symbol": "BTC/USD", "side": "buy", "notional_usd": 500, "why": "no gate"}))
    assert out.get("filled") is not False and "error" not in out          # nothing stopped it
    plugin.arena_borrow({"amount_usd": 1000, "why": "lever"})
    rows = [json.loads(l) for l in (root / "witness.jsonl").read_text().splitlines()]
    assert [r["tool"] for r in rows] == ["arena_trade", "arena_borrow"]
    assert rows[0]["would"] == "denied" and "only the desk's CIO" in rows[0]["would_reason"]
    assert rows[1]["would"] == "denied" and "founder's budget" in rows[1]["would_reason"]
    # a governed seat leaves no witness rows: Arcade's own receipts cover it
    monkeypatch.setattr(plugin, "_profile", lambda: "blue-cio")
    plugin.arena_market({})
    assert len((root / "witness.jsonl").read_text().splitlines()) == 2


QUOTES = {s: {"bid": 100.0 + i, "ask": 100.2 + i} for i, s in enumerate(desk.ALPACA_UNIVERSE)}


@pytest.fixture
def live(tmp_path):
    desk.new_match(tmp_path, 10_000, "balanced", 30, {"red": "m", "blue": "m"}, seed=1, crew="quant",
                   market="alpaca", quotes=QUOTES, research_minutes=0)
    return tmp_path


def test_live_fills_pay_the_spread_and_alpacas_fee(live):
    out = desk.trade(live, "red", "BTC", "buy", 1000, "lead-lag", who="red-exec")
    assert "error" not in out
    row = [json.loads(l) for l in (live / "trades.jsonl").read_text().splitlines()][-1]
    btc = QUOTES["BTC/USD"]
    assert row["price"] == btc["ask"] and row["symbol"] == "BTC/USD"
    book = json.loads((live / "red" / "book.json").read_text())
    assert abs(book["fees"] - 1000 * desk.LIVE_FEE_BPS / 10_000) < 1e-9
    desk.trade(live, "red", "BTC/USD", "sell", 500, "trim", who="red-exec")
    assert [json.loads(l) for l in (live / "trades.jsonl").read_text().splitlines()][-1]["price"] == btc["bid"]


def test_the_bell_keeps_the_research_phase_out_of_the_market(tmp_path):
    desk.new_match(tmp_path, 10_000, "balanced", 30, {"red": "m", "blue": "m"}, market="alpaca", quotes=QUOTES, research_minutes=3)
    out = desk.trade(tmp_path, "red", "ETH/USD", "buy", 500, "early")
    assert "the bell is in" in out["error"]
    view = desk.market_view(tmp_path, "red")
    assert view["phase"] == "research" and view["seconds_to_bell"] > 170


def test_a_big_universe_shows_a_screener_and_history_on_request(live):
    for k in range(40):
        desk.tick_live(live, {s: {"bid": q["bid"] * (1 + 0.001 * k * (i % 3)), "ask": q["ask"] * (1 + 0.001 * k * (i % 3))}
                              for i, (s, q) in enumerate(QUOTES.items())})
    view = desk.market_view(live, "red")
    assert len(view["universe"]) == len(desk.ALPACA_UNIVERSE) and len(view["quotes"]) <= 10 and "BTC/USD" in view["quotes"]
    assert all("spread_bps" in q for q in view["quotes"].values())
    h = desk.history(live, ["sol", "BTC/USD", "NOPE"], 60)
    assert len(h["series"]["SOL/USD"]) == 30 and h["missing"] == ["NOPE/USD"]


def test_the_score_is_net_of_the_model_bill(live):
    with (live / "burn.jsonl").open("a") as fh:
        fh.write(json.dumps({"team": "red", "profile": "red-pm", "usd": 12.5, "tokens": 1000}) + "\n")
    red, blue = desk.standings(live)["red"], desk.standings(live)["blue"]
    assert red["burn"] == 12.5 and red["net"] == round(red["pnl"] - 12.5, 2) and red["money"] < blue["money"]


def test_a_thesis_needs_a_real_sentence(live):
    assert not desk.set_thesis(live, "red", "red-pm", "buy")["ok"]
    assert desk.set_thesis(live, "red", "red-pm", "Alts are Bitcoin on a delay: buy laggards after a BTC break.", "no lag after costs")["ok"]
    assert desk.market_view(live, "red")["thesis"]["kill_if"] == "no lag after costs"
    assert desk.market_view(live, "blue")["thesis"] is None


def _referee():
    import importlib.util
    spec = importlib.util.spec_from_file_location("arena_referee", Path(__file__).resolve().parents[1] / "arena.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_only_think_when_it_pays_sleeps_in_a_quiet_market_and_wakes_on_a_move(live):
    ref = _referee()
    match = json.loads((live / "match.json").read_text())
    for _ in range(35):   # flat
        desk.tick_live(live, QUOTES)
    awake, move, bar = ref.market_pays(match, live, "red")
    assert not awake and move == 0 and bar > 0
    for k in range(35):   # every coin climbs about 1% in a minute
        desk.tick_live(live, {s: {"bid": q["bid"] * (1 + 0.0003 * (k + 1)), "ask": q["ask"] * (1 + 0.0003 * (k + 1))}
                              for s, q in QUOTES.items()})
    awake, move, bar = ref.market_pays(match, live, "red")
    assert awake and move > bar
