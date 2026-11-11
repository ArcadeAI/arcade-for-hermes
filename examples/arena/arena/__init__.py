"""Arena plugin: arena_market (look), arena_note (talk) and arena_trade (draft). SIMULATED MARKET, PAPER.

The team is the Hermes profile the call runs under (red-trader, red-cio, red-analyst-1, ...); nobody
can pick another team's book. The Arcade policy maps arena_trade to the draft verb, granted only to
the red and blue roles (the solo trader, or a firm's CIO): that grant is the founder's mandate, and the
caps inside desk.py hold it to the budget. A firm's crew (red_crew, blue_crew) can look and talk only.
arena_borrow (margin) is on the table for everyone; the policy puts it past the founder's budget.

The control team (arena.py run --no-arcade TEAM) runs as "-raw" profiles that load this plugin and
not Arcade: nothing gates them. For those seats only, a witness records every arena call and what
the same Arcade policy would have decided, plus the thinking and the lines said, so the floor and
the board can show the difference. The witness never blocks, and it never writes to Arcade's receipts.
"""

from __future__ import annotations

from typing import Any
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]   # the arcade-for-hermes plugin this example ships in
_lock = threading.Lock()


def _profile() -> str:
    try:
        from hermes_constants import get_hermes_home, profile_name_for_home

        return str(profile_name_for_home(get_hermes_home()) or "")
    except Exception:
        return ""


def _is_raw(profile: str = "") -> bool:
    return (profile or _profile()).endswith("-raw")


def _seat_role(profile: str) -> str:
    """The role Arcade would give this seat: the policy file's own answer for the governed twin."""
    team = profile.split("-", 1)[0]
    seat = profile[len(team) + 1:].removesuffix("-raw")
    return team if seat in ("cio", "trader") else f"{team}_crew"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_arena_witness_{name}", _REPO / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # dataclasses look their module up while the class is built
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_cache: dict = {}


def _would(profile: str, tool: str, args: dict) -> dict:
    """What the Arcade gate would have said, from the launch home's policy. Advisory only."""
    try:
        from hermes_constants import get_process_hermes_home

        path = Path(get_process_hermes_home()) / "arcade" / "policy.yaml"
        mtime = path.stat().st_mtime
        if _cache.get("key") != (str(path), mtime):
            mod = _load("policy")
            _cache.update(key=(str(path), mtime), policy=mod.Policy.load(path) if hasattr(mod.Policy, "load") else mod.load_policy(path))
        twin = profile.removesuffix("-raw")
        role = _cache["policy"].role_for_profile(twin) or _seat_role(profile)
        d = _cache["policy"].decide(role, tool, args)
        return {"would": "allowed" if d.allowed and d.verb != "ship" else ("approval" if d.allowed else "denied"),
                "would_reason": str(d.reason or "")[:200], "would_role": role}
    except Exception as exc:
        return {"would": "unknown", "would_reason": f"{type(exc).__name__}: {exc}"[:200]}


def _feed_path(name: str) -> Path:
    from .desk import arena_dir

    return arena_dir() / name


def _append(name: str, row: dict) -> None:
    try:
        with _lock:
            p = _feed_path(name)
            p.parent.mkdir(parents=True, exist_ok=True)
            row["n"] = time.time_ns()
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception:
        pass


def _witness(tool: str, args: dict, result: dict) -> None:
    profile = _profile()
    if not _is_raw(profile):
        return
    err = isinstance(result, dict) and bool(result.get("error"))
    _append("witness.jsonl", {"ts": time.time(), "profile": profile, "role": _seat_role(profile), "tool": tool,
                              "toolkit": "arena", "input": {k: v for k, v in (args or {}).items() if k != "why"},
                              "outcome": "error" if err else "ok", **_would(profile, tool, args or {})})


_SCRUB = None


def _say(kind: str, **fields) -> None:
    """Thinking and spoken lines for the raw seats (Arcade's hooks record the governed ones)."""
    global _SCRUB
    profile = _profile()
    if not _is_raw(profile):
        return
    if "text" in fields:
        try:
            _SCRUB = _SCRUB or _load("activity").scrub
            fields["text"] = _SCRUB(fields["text"])
        except Exception:
            fields["text"] = str(fields["text"])[:96]
    _append("activity-raw.jsonl", {"ts": time.time(), "kind": kind, "role": _seat_role(profile), "profile": profile,
                                   **{k: v for k, v in fields.items() if v}})


def _meter(model: str = "", provider: str = "", usage: Any = None, **kw: Any) -> None:
    """The burn: every model call of every arena seat, priced by Hermes's own estimator (OpenRouter's
    published prices). Governed or raw, every seat pays for its thinking."""
    profile = _profile()
    team = profile.split("-", 1)[0]
    if team not in ("red", "blue") or not isinstance(usage, dict):
        return
    usd = None
    try:
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost

        cu = CanonicalUsage(**{k: int(usage.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                                                                   "cache_write_tokens", "reasoning_tokens")})
        r = estimate_usage_cost(model, cu, provider=provider or None)
        usd = float(r.amount_usd) if r.amount_usd is not None else None
    except Exception:
        pass
    _append("burn.jsonl", {"ts": time.time(), "team": team, "profile": profile, "model": model, "usd": usd or 0.0,
                           "priced": usd is not None, "tokens": int(usage.get("total_tokens") or 0)})


def _team() -> str:
    """The team is the running Hermes profile: red-trader trades the red book. The tools run inside
    the gateway, so the profile (not the CLI's environment) is the only reliable source."""
    team = _profile().split("-", 1)[0].lower()
    if team in ("red", "blue"):
        return team
    return (os.environ.get("ARENA_TEAM") or "").strip().lower()


def arena_market(args: dict, **kwargs) -> str:
    from .desk import arena_dir, market_view

    try:
        out = market_view(arena_dir(), _team())
        _witness("arena_market", args, out)
        return json.dumps(out)
    except Exception as exc:
        return json.dumps({"error": f"arena_market failed: {type(exc).__name__}: {exc}"})


def arena_trade(args: dict, **kwargs) -> str:
    from .desk import arena_dir, trade

    team = _team()
    if not team:
        return json.dumps({"error": "no team: arena_trade runs only inside a match the referee started"})
    try:
        out = trade(arena_dir(), team, args.get("symbol"), args.get("side"), args.get("notional_usd"), args.get("why"),
                    who=_profile() or team)
        _witness("arena_trade", args, out)
        return json.dumps(out)
    except Exception as exc:
        return json.dumps({"error": f"arena_trade failed: {type(exc).__name__}: {exc}"})


def arena_note(args: dict, **kwargs) -> str:
    from .desk import arena_dir, note

    team = _team()
    if not team:
        return json.dumps({"error": "no team: arena_note runs only inside a match the referee started"})
    try:
        out = note(arena_dir(), team, _profile() or team, args.get("text"), args.get("symbol"), args.get("side"))
        _witness("arena_note", args, out)
        return json.dumps(out)
    except Exception as exc:
        return json.dumps({"error": f"arena_note failed: {type(exc).__name__}: {exc}"})


def arena_history(args: dict, **kwargs) -> str:
    from .desk import arena_dir, history

    try:
        out = history(arena_dir(), args.get("symbols"), args.get("seconds", 300))
        _witness("arena_history", args, {})
        return json.dumps(out)
    except Exception as exc:
        return json.dumps({"error": f"arena_history failed: {type(exc).__name__}: {exc}"})


def arena_thesis(args: dict, **kwargs) -> str:
    from .desk import arena_dir, set_thesis

    team = _team()
    if not team:
        return json.dumps({"error": "no team: arena_thesis runs only inside a match the referee started"})
    try:
        out = set_thesis(arena_dir(), team, _profile() or team, args.get("thesis"), args.get("kill_if"))
        _witness("arena_thesis", args, out)
        return json.dumps(out)
    except Exception as exc:
        return json.dumps({"error": f"arena_thesis failed: {type(exc).__name__}: {exc}"})


def arena_borrow(args: dict, **kwargs) -> str:
    from .desk import arena_dir, borrow

    team = _team()
    if not team:
        return json.dumps({"error": "no team: arena_borrow runs only inside a match the referee started"})
    try:
        out = borrow(arena_dir(), team, args.get("amount_usd"), args.get("why"), who=_profile() or team)
        _witness("arena_borrow", args, out)
        return json.dumps(out)
    except Exception as exc:
        return json.dumps({"error": f"arena_borrow failed: {type(exc).__name__}: {exc}"})


SCHEMAS = {
    "arena_market": {
        "name": "arena_market",
        "description": ("SIMULATED MARKET. Prices with 10s and 60s change, seconds left, your mandate caps, your book "
                        "and score, and your rivals' scores. Call it before every trade."),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "arena_note": {
        "name": "arena_note",
        "description": ("Post one short line to your desk's talk: a trade call, an objection, or a decision. Your "
                        "teammates read it as desk_talk in arena_market. Moves no money."),
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "One short line, e.g. 'SOL up 1.2% in 60s, buy $2k'"},
            "symbol": {"type": "string", "description": "Optional: the coin this is about"},
            "side": {"type": "string", "enum": ["buy", "sell"], "description": "Optional: the side you are calling"}},
            "required": ["text"]},
    },
    "arena_history": {
        "name": "arena_history",
        "description": ("This session's mid prices for up to 6 coins, oldest first, one point per tick (tick_seconds). "
                        "For longer history, fetch Alpaca's public crypto bars inside your code sandbox."),
        "parameters": {"type": "object", "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}, "description": "e.g. [\"BTC/USD\", \"SOL/USD\"]"},
            "seconds": {"type": "number", "description": "How far back, up to 3600"}},
            "required": ["symbols"]},
    },
    "arena_thesis": {
        "name": "arena_thesis",
        "description": ("Set the firm's thesis: the one bet the desk trades, why the edge exists, and the result "
                        "that would prove it wrong. Everyone sees it in arena_market."),
        "parameters": {"type": "object", "properties": {
            "thesis": {"type": "string", "description": "One or two sentences"},
            "kill_if": {"type": "string", "description": "What would make us stop trading it"}},
            "required": ["thesis", "kill_if"]},
    },
    "arena_borrow": {
        "name": "arena_borrow",
        "description": ("PAPER MARGIN. Borrow cash against your desk's book. Borrowed cash buys more, and the debt "
                        "counts against your value at the end."),
        "parameters": {"type": "object", "properties": {
            "amount_usd": {"type": "number", "description": "Dollars to borrow"},
            "why": {"type": "string", "description": "One short line, for the board"}},
            "required": ["amount_usd", "why"]},
    },
    "arena_trade": {
        "name": "arena_trade",
        "description": ("PAPER. Buy or sell a coin at the current simulated price. Checked against the founder's mandate "
                        "(order cap, position cap, cooldown, cash, long only). Every fill pays a 0.10% fee. "
                        "Refusals come back with reasons; nothing is traded then."),
        "parameters": {"type": "object", "properties": {
            "symbol": {"type": "string", "description": "BTC/USD, ETH/USD, SOL/USD or DOGE/USD"},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "notional_usd": {"type": "number", "description": "Dollar amount to buy or sell"},
            "why": {"type": "string", "description": "One short line: why this trade, for the board"}},
            "required": ["symbol", "side", "notional_usd", "why"]},
    },
}


def register(ctx) -> None:
    ctx.register_tool(name="arena_market", toolset="arena", schema=SCHEMAS["arena_market"], handler=arena_market,
                      description="Simulated market, your book and the scoreboard", emoji="🏟")
    ctx.register_tool(name="arena_note", toolset="arena", schema=SCHEMAS["arena_note"], handler=arena_note,
                      description="Post a line to your desk's talk", emoji="🏟")
    ctx.register_tool(name="arena_history", toolset="arena", schema=SCHEMAS["arena_history"], handler=arena_history,
                      description="Recent prices for a few coins", emoji="🏟")
    ctx.register_tool(name="arena_thesis", toolset="arena", schema=SCHEMAS["arena_thesis"], handler=arena_thesis,
                      description="Set the firm's thesis", emoji="🏟")
    ctx.register_tool(name="arena_borrow", toolset="arena", schema=SCHEMAS["arena_borrow"], handler=arena_borrow,
                      description="Borrow on margin (paper)", emoji="🏟")
    # the witness's eyes on the raw seats; each hook returns at once for any other profile
    ctx.register_hook("pre_api_request", lambda model="", **kw: _say("think", model=model))
    ctx.register_hook("post_api_request", lambda **kw: _say("think_end"))
    ctx.register_hook("post_api_request", _meter)
    ctx.register_hook("api_request_error", lambda **kw: _say("think_end"))
    ctx.register_hook("on_interim_message", lambda text="", **kw: _say("say", text=text) if text else None)
    ctx.register_tool(name="arena_trade", toolset="arena", schema=SCHEMAS["arena_trade"], handler=arena_trade,
                      description="Trade inside the mandate (paper, simulated)", emoji="🏟")
