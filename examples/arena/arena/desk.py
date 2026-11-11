"""The arena desk: two paper books on one simulated market, a mandate per match, and the score.

SIMULATED MARKET, PAPER BOOKS. No broker, no real prices, no real money. Everything lives in one
directory (``ARENA_DIR``) the referee owns:

  match.json             the mandate (budget, style, caps), start and end, team models
  market.json            prices, rewritten by the referee every tick
  <team>/book.json       cash, positions, fees, trade count
  trades.jsonl           every fill and every refusal, both teams, with the trader's one-line why
  equity.jsonl           each team's book value per tick (the board's sparklines)

The mandate is the founder's one yes: a budget and a style. The style sets the caps every trade is
checked against here, deterministically, whatever the model asks for.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Optional

LABEL = "SIMULATED MARKET, PAPER"
LIVE_LABEL = "LIVE ALPACA QUOTES, PAPER FILLS"
# Every crypto pair Alpaca listed as tradable on 2026-11-08 (checked through Arcade's ArcadeAlpaca.GetAsset),
# stablecoins left out. Quotes come from Alpaca's public crypto feed: real bid and ask, no key.
ALPACA_UNIVERSE = tuple(f"{c}/USD" for c in (
    "AAVE ADA ARB AVAX BAT BCH BTC CRV DOGE DOT ETH GRT HYPE LINK LTC ONDO PEPE POL RENDER SHIB SKY SOL SUSHI "
    "TRUMP UNI XRP XTZ YFI").split())
LIVE_FEE_BPS = 25   # Alpaca's crypto taker fee at the lowest volume tier, as remembered: not checked against today's schedule
SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD")
START_PRICES = {"BTC/USD": 76000.0, "ETH/USD": 2900.0, "SOL/USD": 180.0, "DOGE/USD": 0.21}
FEE_BPS = 10  # every fill pays 0.10%: churn costs money

# style -> caps. order/position are fractions of the budget; vol is per-tick sigma of the market;
# target is the trade count at which the activity half of the score is full.
PRESETS: dict[str, dict[str, Any]] = {
    "steady": {"max_order": 0.10, "max_position": 0.30, "cooldown_s": 20, "vol": 0.0012, "target": 4, "money_span": 0.05,
               "blurb": "steady saving: small orders, never more than 30% in one coin"},
    "balanced": {"max_order": 0.20, "max_position": 0.50, "cooldown_s": 10, "vol": 0.0020, "target": 9, "money_span": 0.10,
                 "blurb": "balanced: medium orders, up to half the budget in one coin"},
    "risky": {"max_order": 0.35, "max_position": 0.80, "cooldown_s": 6, "vol": 0.0032, "target": 16, "money_span": 0.15,
              "blurb": "risky: big orders, concentrate up to 80%"},
    "chaos": {"max_order": 0.50, "max_position": 1.00, "cooldown_s": 3, "vol": 0.0050, "target": 25, "money_span": 0.25,
              "blurb": "chaos: anything inside the budget goes, and the market is wild"},
}
_WORDS = [
    ("chaos", ("chaos", "yolo", "degen", "wild", "insane", "send it", "max")),
    ("steady", ("steady", "safe", "saving", "save", "conservative", "careful", "low risk", "boring")),
    ("risky", ("risky", "risk", "aggressive", "bold", "growth", "big")),
    ("balanced", ("balanced", "medium", "normal", "moderate", "mix")),
]


def style_from_words(text: str) -> str:
    """The preset a plain-words mandate asks for. Unclear words get balanced."""
    t = (text or "").lower()
    for style, words in _WORDS:
        if any(re.search(r"\b" + re.escape(w) + r"\b", t) for w in words):
            return style
    return "balanced"


def arena_dir() -> Path:
    """<launch HERMES_HOME>/plugin-data/arena: the gateway and the referee agree on it."""
    if os.environ.get("ARENA_DIR"):
        return Path(os.environ["ARENA_DIR"])
    try:
        from hermes_constants import get_process_hermes_home

        home = Path(get_process_hermes_home())
    except Exception:
        home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return home / "plugin-data" / "arena"


def _atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(path)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


@contextlib.contextmanager
def locked(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------- the match
def symbols_of(match: Optional[dict]) -> tuple:
    return tuple((match or {}).get("symbols") or SYMBOLS)


def new_match(root: Path, budget: float, words: str, minutes: float, teams: dict[str, str], seed: Optional[int] = None,
              crew: str = "solo", market: str = "sim", quotes: Optional[dict] = None, research_minutes: float = 0.0) -> dict:
    """market "sim": the random walk. market "alpaca": live bid/ask in ``quotes`` ({symbol: {"bid", "ask"}}),
    buys fill at the ask and sells at the bid, Alpaca's fee. ``research_minutes`` before the bell: the
    desk is open for reading and talking, closed for trading."""
    style = style_from_words(words)
    caps = {k: v for k, v in PRESETS[style].items()}
    live = market == "alpaca"
    if live:   # real crypto moves less in an hour than the toy market does in a minute
        caps["money_span"] = 0.03
    now = time.time()
    opens = now + research_minutes * 60
    symbols = tuple(s for s in ALPACA_UNIVERSE if s in (quotes or {})) if live else SYMBOLS
    match = {"label": LIVE_LABEL if live else LABEL, "budget": float(budget), "words": words, "style": style, "caps": caps,
             "starts_at": now, "opens_at": opens, "ends_at": opens + minutes * 60, "teams": teams,
             "seed": seed if seed is not None else int(now), "fee_bps": LIVE_FEE_BPS if live else FEE_BPS, "crew": crew,
             "market": market, "symbols": list(symbols)}
    for f in list(root.glob("*.jsonl")) + [root / "result.json", root / "scoreboard.json"] + list(root.glob("*/thesis.json")):
        if f.exists():
            f.unlink()
    _atomic(root / "match.json", match)
    for team in teams:
        _atomic(root / team / "book.json", {"cash": float(budget), "positions": {}, "fees": 0.0, "trades": 0,
                                            "refused": 0, "last_trade_at": 0.0})
    if live:
        mids = {s: round((quotes[s]["bid"] + quotes[s]["ask"]) / 2, 10) for s in symbols}
        _atomic(root / "market.json", {"t": now, "tick": 0, "tick_s": 2, "prices": mids, "history": {s: [p] for s, p in mids.items()},
                                       "bid": {s: quotes[s]["bid"] for s in symbols}, "ask": {s: quotes[s]["ask"] for s in symbols}})
    else:
        _atomic(root / "market.json", {"t": now, "tick": 0, "tick_s": 1, "prices": dict(START_PRICES),
                                       "history": {s: [p] for s, p in START_PRICES.items()}})
    return match


def tick_live(root: Path, quotes: dict) -> dict:
    """One poll of the live feed: mid, bid and ask per coin; a coin missing from this poll keeps its last quote."""
    with locked(root):
        m = _read(root / "market.json", None)
        if m is None:
            raise RuntimeError("no market; start a match first")
        for s, q in quotes.items():
            if s not in m["prices"] or not (q.get("bid") and q.get("ask")):
                continue
            m["bid"][s], m["ask"][s] = q["bid"], q["ask"]
            m["prices"][s] = round((q["bid"] + q["ask"]) / 2, 10)
            h = m["history"].setdefault(s, [])
            h.append(m["prices"][s])
            del h[:-1800]   # an hour at one poll every two seconds
        m["t"] = time.time()
        m["tick"] += 1
        _atomic(root / "market.json", m)
        return m


def tick_market(root: Path, rng: random.Random, vol: float) -> dict:
    """One second of a regime-switching random walk with a little momentum."""
    with locked(root):
        m = _read(root / "market.json", None)
        if m is None:
            raise RuntimeError("no market; start a match first")
        drift = m.setdefault("drift", {s: 0.0 for s in SYMBOLS})
        for s in SYMBOLS:
            if rng.random() < 0.04:                       # regime change: a new trend
                drift[s] = rng.gauss(0, vol * 0.6)
            beta = {"BTC/USD": 1.0, "ETH/USD": 1.2, "SOL/USD": 1.6, "DOGE/USD": 2.2}[s]
            shock = rng.gauss(0, vol * beta) + drift[s]
            if rng.random() < 0.01:                       # a rare jump
                shock += rng.choice((-1, 1)) * vol * beta * 6
            p = m["prices"][s] * math.exp(shock)
            m["prices"][s] = round(p, 6 if p < 1 else 2)
            h = m["history"].setdefault(s, [])
            h.append(m["prices"][s])
            del h[:-120]
        m["t"] = time.time()
        m["tick"] += 1
        _atomic(root / "market.json", m)
        return m


MAX_BORROW = 2.0   # the exchange's margin limit, in budgets; the founder's mandate is a separate, lower line


def book_value(book: dict, prices: dict) -> float:
    """Equity: cash plus positions, minus what was borrowed."""
    return (float(book["cash"]) + sum(float(q) * float(prices.get(s, 0)) for s, q in book.get("positions", {}).items())
            - float(book.get("debt", 0.0)))


def burn_by_team(root: Path) -> dict:
    """Model spend per team from burn.jsonl (the arena plugin meters every model call)."""
    out: dict[str, dict] = {}
    try:
        lines = (root / "burn.jsonl").read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        t = out.setdefault(str(r.get("team")), {"usd": 0.0, "tokens": 0, "calls": 0, "seats": {}})
        t["usd"] += float(r.get("usd") or 0)
        t["tokens"] += int(r.get("tokens") or 0)
        t["calls"] += 1
        seat = str(r.get("profile") or "")
        t["seats"][seat] = round(t["seats"].get(seat, 0.0) + float(r.get("usd") or 0), 4)
    return out


def score(match: dict, book: dict, prices: dict, burn_usd: float = 0.0) -> dict:
    """Half activity, half money. Activity: trades that filled, with diminishing returns, full at the
    style's target. Money: P&L against the budget; the style's span (+-5% steady up to +-25% chaos)
    covers the whole half, so a wild market cannot pin both desks at 100. 0 to 100."""
    budget = float(match["budget"])
    value = book_value(book, prices)
    pnl = value - budget
    pnl_pct = pnl / budget if budget else 0.0
    # the firm's real thesis: does it make more than it costs to think? the money half scores NET of the model bill
    net = pnl - burn_usd
    net_pct = net / budget if budget else 0.0
    target = float(match["caps"]["target"])
    activity = min(1.0, math.sqrt(book.get("trades", 0) / target)) if target else 0.0
    span = float(match["caps"].get("money_span", 0.05)) or 0.05
    money = min(1.0, max(0.0, 0.5 + net_pct / (2 * span)))
    return {"value": round(value, 2), "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct * 100, 3),
            "burn": round(burn_usd, 4), "net": round(net, 2), "net_pct": round(net_pct * 100, 3),
            "trades": book.get("trades", 0), "fees": round(book.get("fees", 0.0), 2),
            "activity": round(activity * 50, 1), "money": round(money * 50, 1), "score": round(activity * 50 + money * 50, 1)}


def standings(root: Path) -> dict:
    match = _read(root / "match.json", None)
    market = _read(root / "market.json", {"prices": {}})
    if not match:
        return {}
    out = {}
    burns = burn_by_team(root)
    for team in match["teams"]:
        book = _read(root / team / "book.json", {"cash": match["budget"], "positions": {}})
        out[team] = {**score(match, book, market["prices"], burns.get(team, {}).get("usd", 0.0)), "positions": book.get("positions", {}), "cash": round(book["cash"], 2),
                     "debt": round(float(book.get("debt", 0.0)), 2)}
    return out


# ---------------------------------------------------------------------------- trader tools
def market_view(root: Path, team: str) -> dict:
    match = _read(root / "match.json", None)
    market = _read(root / "market.json", None)
    if not match or not market:
        return {"label": LABEL, "error": "no match running"}
    now = time.time()
    left = max(0, int(match["ends_at"] - now))
    step = float(market.get("tick_s") or 1)
    quotes = {}
    for s, p in market["prices"].items():
        h = market["history"].get(s, [p])
        ago = lambda secs: h[-int(max(1, secs / step))] if len(h) >= secs / step else h[0]  # noqa: E731
        q = {"price": p, "chg_10s_pct": round((p / ago(10) - 1) * 100, 3), "chg_60s_pct": round((p / ago(60) - 1) * 100, 3),
             "chg_5m_pct": round((p / ago(300) - 1) * 100, 3)}
        if market.get("bid"):
            q["spread_bps"] = round((market["ask"][s] - market["bid"][s]) / p * 10_000, 1) if p else None
        quotes[s] = q
    table = standings(root)
    caps = match["caps"]
    book = table.get(team, {})
    if len(quotes) > 8:
        # a screener, not a dump: the biggest movers, plus whatever this desk holds
        movers = sorted(quotes, key=lambda s: -abs(quotes[s]["chg_60s_pct"]))[:8]
        held = [s for s in (book.get("positions") or {}) if s in quotes]
        shown = {s: quotes[s] for s in dict.fromkeys(movers + held + ["BTC/USD"]) if s in quotes}
    else:
        shown = quotes
    phase = "research" if now < match.get("opens_at", 0) else ("over" if now > match["ends_at"] else "trading")
    extra = {"phase": phase, "seconds_to_bell": max(0, int(match.get("opens_at", 0) - now)), "universe": list(quotes),
             "thesis": _read(root / team / "thesis.json", None)} if match.get("market") == "alpaca" or match.get("opens_at") else {}
    quotes = shown
    return {"label": match.get("label", LABEL), "seconds_left": left, **extra, "mandate": {"budget": match["budget"], "style": match["style"], "words": match["words"],
            "max_order_usd": round(caps["max_order"] * match["budget"], 2), "max_position_usd": round(caps["max_position"] * match["budget"], 2),
            "cooldown_seconds": caps["cooldown_s"], "fee_bps": match["fee_bps"]},
            "quotes": quotes, "you": {"team": team, **table.get(team, {})}, "desk_talk": talk(root, team),
            "rivals": {t: {k: v for k, v in s.items() if k in ("score", "value", "pnl_pct", "trades")} for t, s in table.items() if t != team},
            "score_rule": "score = activity (trades, diminishing, full at %d) 50 + money (P&L vs budget, +-%d%% spans it) 50" % (caps["target"], round(caps.get("money_span", 0.05) * 100))}


def history(root: Path, symbols: Any, seconds: Any = 300) -> dict:
    """This session's mid prices for a few coins, oldest first, one point per tick: paste into E2B."""
    market = _read(root / "market.json", None)
    if not market:
        return {"error": "no match running"}
    want = [str(s).upper() if "/" in str(s) else f"{str(s).upper()}/USD" for s in (symbols or [])][:6]
    step = float(market.get("tick_s") or 1)
    try:
        n = max(2, min(int(float(seconds) / step), 1800))
    except (TypeError, ValueError):
        n = 150
    out = {s: market["history"][s][-n:] for s in want if s in market["history"]}
    return {"tick_seconds": step, "series": out, "missing": [s for s in want if s not in out]}


def set_thesis(root: Path, team: str, who: str, text: Any, kill_if: Any = "") -> dict:
    """The firm's one bet, set by whoever the policy lets (a PM). The latest one stands."""
    body = " ".join(str(text or "").split())[:400]
    if len(body) < 20:
        return {"ok": False, "error": "refused: a thesis is a sentence or two: the edge, why it exists, how we trade it"}
    row = {"ts": time.time(), "who": str(who or team)[:40], "thesis": body, "kill_if": " ".join(str(kill_if or "").split())[:200]}
    _atomic(root / team / "thesis.json", row)
    return {"ok": True, "thesis": row}


def borrow(root: Path, team: str, amount_usd: Any, why: Any = "", who: Any = None) -> dict:
    """Margin: cash now, debt that counts against equity. The exchange allows up to MAX_BORROW budgets.
    Whether the founder's mandate allows it at all is not the desk's call: that is the gate's."""
    with locked(root):
        match = _read(root / "match.json", None)
        bpath = root / team / "book.json"
        book = _read(bpath, None)
        if not match or book is None:
            return {"label": LABEL, "error": "no match running; nothing borrowed"}
        try:
            amount = float(amount_usd)
        except (TypeError, ValueError):
            amount = float("nan")
        limit = MAX_BORROW * float(match["budget"]) - float(book.get("debt", 0.0))
        reasons = []
        if time.time() > match["ends_at"]:
            reasons.append("the match is over")
        if not (amount > 0):
            reasons.append("amount_usd must be a positive number")
        elif amount > limit + 1e-9:
            reasons.append(f"${amount:,.0f} is over the exchange's margin limit (${max(0.0, limit):,.0f} left)")
        row = {"ts": time.time(), "team": team, "kind": "borrow", "notional": round(amount, 2) if amount == amount else None,
               "why": why, "who": str(who or team)[:40]}
        if reasons:
            _log(root, {**row, "ok": False, "reasons": reasons})
            return {"label": LABEL, "borrowed": False, "error": "refused: " + "; ".join(reasons), "reasons": reasons}
        book["cash"] = round(float(book["cash"]) + amount, 6)
        book["debt"] = round(float(book.get("debt", 0.0)) + amount, 6)
        _atomic(bpath, book)
        _log(root, {**row, "ok": True})
        return {"label": LABEL, "borrowed": True, "amount_usd": round(amount, 2), "cash": round(book["cash"], 2),
                "debt": round(book["debt"], 2)}


def note(root: Path, team: str, who: str, text: Any, symbol: Any = None, side: Any = None) -> dict:
    """One line on the team's desk talk: an analyst's call, the skeptic's objection, the CIO's decision.
    Talk moves no money; the CIO reads it in arena_market."""
    body = " ".join(str(text or "").split())[:200]
    if not body:
        return {"ok": False, "error": "refused: say something (text is empty)"}
    row: dict[str, Any] = {"ts": time.time(), "team": team, "who": str(who or team)[:40], "text": body}
    sym = str(symbol or "").upper()
    if sym and "/" not in sym:
        sym += "/USD"
    if sym in symbols_of(_read(root / "match.json", None)):
        row["symbol"] = sym
    if str(side or "").lower() in ("buy", "sell"):
        row["side"] = str(side).lower()
    with locked(root):
        with (root / f"{team}-talk.jsonl").open("a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return {"ok": True, "posted": row}


def talk(root: Path, team: str, n: int = 8) -> list[dict]:
    try:
        lines = (root / f"{team}-talk.jsonl").read_text().splitlines()[-n:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        out.append({k: r[k] for k in ("who", "text", "symbol", "side") if k in r} | {"secs_ago": int(time.time() - r["ts"])})
    return out


def _log(root: Path, row: dict) -> None:
    with (root / "trades.jsonl").open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def trade(root: Path, team: str, symbol: Any, side: Any, notional_usd: Any, why: Any = "", who: Any = None) -> dict:
    """Buy or sell at the current simulated price, inside the mandate. Deterministic checks only."""
    symbol = str(symbol or "").upper().strip()
    side = str(side or "").lower().strip()
    why = " ".join(str(why or "").split())[:120]
    with locked(root):
        match = _read(root / "match.json", None)
        market = _read(root / "market.json", None)
        bpath = root / team / "book.json"
        book = _read(bpath, None)
        now = time.time()
        reasons: list[str] = []
        if not match or not market or book is None:
            return {"label": LABEL, "error": "no match running; nothing traded"}
        caps, budget = match["caps"], float(match["budget"])
        try:
            notional = float(notional_usd)
        except (TypeError, ValueError):
            notional = float("nan")
        if now > match["ends_at"]:
            reasons.append("the match is over")
        if now < match.get("opens_at", 0):
            reasons.append(f"the bell is in {match['opens_at'] - now:.0f}s: research first, then trade")
        if isinstance(symbol, str) and symbol and "/" not in symbol:
            symbol = symbol.upper() + "/USD"
        if symbol not in symbols_of(match):
            reasons.append(f"{symbol or '(none)'} is not traded here; the universe is {list(symbols_of(match))}")
        if side not in ("buy", "sell"):
            reasons.append("side must be buy or sell")
        if not (notional > 0):
            reasons.append("notional_usd must be a positive number")
        max_order = caps["max_order"] * budget
        if notional > max_order + 1e-9:
            reasons.append(f"${notional:,.0f} is over the {match['style']} order cap ${max_order:,.0f}")
        wait = caps["cooldown_s"] - (now - float(book.get("last_trade_at", 0)))
        if wait > 0:
            reasons.append(f"cooldown: wait {wait:.0f}s more ({match['style']} mandate)")
        # live: buys pay the ask, sells get the bid; the spread is a real cost
        side_px = (market.get("ask") if side == "buy" else market.get("bid")) or {}
        price = float(side_px.get(symbol) or market["prices"].get(symbol, 0) or 0)
        qty = notional / price if price > 0 and notional == notional else 0.0
        fee = notional * match["fee_bps"] / 10_000 if notional == notional else 0.0
        held = float(book["positions"].get(symbol, 0))
        if side == "buy" and not reasons:
            if notional + fee > book["cash"] + 1e-9:
                reasons.append(f"${notional:,.0f} plus fee is over cash ${book['cash']:,.0f}")
            pos_after = (held + qty) * price
            if pos_after > caps["max_position"] * budget + 1e-6:
                reasons.append(f"{symbol} would be ${pos_after:,.0f}, over the {match['style']} position cap ${caps['max_position'] * budget:,.0f}")
        if side == "sell" and not reasons and qty > held + 1e-12:
            reasons.append(f"you hold {held:.6f} {symbol} (${held * price:,.2f}); long only, no shorting")
        row = {"ts": now, "team": team, "symbol": symbol, "side": side, "notional": round(notional, 2) if notional == notional else None,
               "price": price, "why": why, "who": str(who or team)[:40]}
        if reasons:
            book["refused"] = book.get("refused", 0) + 1
            _atomic(bpath, book)
            _log(root, {**row, "ok": False, "reasons": reasons})
            return {"label": LABEL, "filled": False, "error": "refused: " + "; ".join(reasons), "reasons": reasons}
        if side == "buy":
            book["cash"] = round(book["cash"] - notional - fee, 6)
            book["positions"][symbol] = held + qty
        else:
            book["cash"] = round(book["cash"] + notional - fee, 6)
            left = held - qty
            if left * price < 0.01:
                book["positions"].pop(symbol, None)
            else:
                book["positions"][symbol] = left
        book["fees"] = book.get("fees", 0.0) + fee
        book["trades"] = book.get("trades", 0) + 1
        book["last_trade_at"] = now
        _atomic(bpath, book)
        _log(root, {**row, "ok": True, "qty": qty, "fee": round(fee, 4)})
        s = score(match, book, market["prices"])
        return {"label": LABEL, "filled": True, "side": side, "symbol": symbol, "qty": round(qty, 8), "price": price,
                "fee_usd": round(fee, 2), "cash_usd": round(book["cash"], 2), "your_score": s["score"], "your_pnl_pct": s["pnl_pct"]}
