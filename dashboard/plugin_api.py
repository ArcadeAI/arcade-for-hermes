"""The Floor: read-only backend for the 8-bit dashboard tab (mounted at /api/plugins/arcade-for-hermes/).

Everything the floor draws comes from here, and everything here comes from files the plugin already
writes: receipts.jsonl (one line per governed call), waiting.json (ship actions waiting on the founder),
activity.jsonl (who is thinking, their one-line intent, the local tools they use) and, when the Koopa example desk is installed, its paper book. Nothing on this router writes, calls
Arcade, or approves anything. A floor sprite moves only because a receipt says so.

Fields are trimmed for display: no principals, no session keys, no URLs, no task ids, and only a few
input keys the floor labels with (symbol, notional, proposal id, issue number, state).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Query

router = APIRouter()

PLUGIN_ID = "arcade-for-hermes"
_INPUT_KEYS = ("symbol", "notional_usd", "notional", "side", "proposal_id", "issue_number", "state", "title")
_MAX_EVENTS = 600


def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _data_dir() -> Path:
    return _home() / "plugin-data" / PLUGIN_ID


def _short(value: Any, n: int) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text if len(text) <= n else text[: n - 3] + "..."


def _event(row: dict[str, Any], seq: int) -> dict[str, Any]:
    raw = row.get("input") if isinstance(row.get("input"), dict) else {}
    approver = row.get("approver") if isinstance(row.get("approver"), dict) else None
    return {
        "seq": seq,
        "id": row.get("id"),
        "key": row.get("action_key"),
        "ts": row.get("ts"),
        "role": row.get("role"),
        "profile": row.get("profile"),
        "via": row.get("via"),
        "tool": row.get("tool"),
        "toolkit": row.get("toolkit"),
        "verb": row.get("verb"),
        "decision": row.get("decision"),
        "outcome": row.get("outcome"),
        "reason": _short(row.get("reason"), 120),
        "work_order": row.get("work_order"),
        "input": {k: _short(raw[k], 40) for k in _INPUT_KEYS if k in raw},
        "approver": {k: approver.get(k) for k in ("choice", "decided_by", "surface")} if approver else None,
    }


def read_events(path: Path, after: int = 0, work_order: Optional[str] = None) -> list[dict[str, Any]]:
    """Receipts in file order with a 1-based ``seq``; only those after ``after``."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for seq, line in enumerate(fh, start=1):
            if seq <= after:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or (work_order and row.get("work_order") != work_order):
                continue
            out.append(_event(row, seq))
    return out[-_MAX_EVENTS:] if after == 0 else out[:_MAX_EVENTS]


def read_waiting(path: Path) -> list[dict[str, Any]]:
    import time

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    now = time.time()
    rows = []
    for key, v in (data.items() if isinstance(data, dict) else []):
        if not isinstance(v, dict) or now - float(v.get("since", 0)) > 900:
            continue
        raw = v.get("input") if isinstance(v.get("input"), dict) else {}
        rows.append({"key": key, "role": v.get("role"), "profile": v.get("profile"), "via": v.get("via"),
                     "tool": v.get("tool"), "toolkit": v.get("toolkit"), "work_order": v.get("work_order"),
                     "since": v.get("since"), "input": {k: _short(raw[k], 40) for k in _INPUT_KEYS if k in raw}})
    return sorted(rows, key=lambda r: r.get("since") or 0)


def read_book(koopa_dir: Path) -> Optional[dict[str, Any]]:
    """Koopa's paper book (cash, positions at fixture prices, fill count), or None without Koopa."""
    try:
        account = json.loads((koopa_dir / "account.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    prices = {s: float(p.get("price", 0)) for s, p in (account.get("prices") or {}).items() if isinstance(p, dict)}
    positions = {s: float(q) for s, q in (account.get("positions") or {}).items() if float(q or 0) > 0}
    held = sum(q * prices.get(s, 0.0) for s, q in positions.items())
    fills, last = 0, None
    ledger = koopa_dir / "ledger.jsonl"
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("kind") == "fill":
                fills += 1
                f = row.get("fill") or {}
                last = {"symbol": f.get("symbol") or row.get("symbol"), "qty": f.get("qty"), "price": f.get("price"),
                        "label": f.get("book_price_label") or f.get("label"), "ts": row.get("ts")}
    cash = float(account.get("cash_usd", 0))
    return {"label": account.get("label", "PAPER MODE"), "cash_usd": round(cash, 2),
            "book_usd": round(cash + held, 2), "positions": {s: round(q, 6) for s, q in positions.items()},
            "fills": fills, "last_fill": last}


def work_orders(path: Path) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for e in read_events(path):
        wo = e.get("work_order")
        if not wo:
            continue
        w = seen.setdefault(wo, {"work_order": wo, "events": 0, "first": e["ts"], "last": e["ts"], "first_seq": e["seq"]})
        w["events"] += 1
        w["last"] = e["ts"]
    return sorted(seen.values(), key=lambda w: (w["events"], w["last"] or ""), reverse=True)


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def read_activity(path: Path, after: int = 0, limit: int = 300) -> list[dict[str, Any]]:
    """The activity feed (who is thinking, what they said, local tools), newer than ``after``.
    The plugin already scrubs spoken lines; this trims again so the tab never shows more."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or int(row.get("n") or 0) <= after:
            continue
        out.append({"n": int(row["n"]), "ts": row.get("ts"), "kind": _short(row.get("kind"), 16), "role": _short(row.get("role"), 32),
                    "profile": _short(row.get("profile"), 32), "tool": _short(row.get("tool"), 48), "text": _short(row.get("text"), 96),
                    "model": _short(row.get("model"), 48)})
    return [{k: v for k, v in e.items() if v is not None} for e in out[-limit:]]


@router.get("/state")
async def state(after: int = Query(0, ge=0), work_order: Optional[str] = None, act: int = Query(0, ge=0)) -> dict[str, Any]:
    d = _data_dir()
    receipts = d / "receipts.jsonl"
    return {"events": read_events(receipts, after, work_order), "waiting": read_waiting(d / "waiting.json"),
            "activity": [] if work_order else read_activity(d / "activity.jsonl", act),
            "book": read_book(_home() / "plugin-data" / "koopa"),
            "arena": _read_json(_home() / "plugin-data" / "arena" / "scoreboard.json"),
            "firm": os.environ.get("ARCADE_FLOOR_FIRM") or "BOWSER CAPITAL"}


@router.get("/work_orders")
async def list_work_orders() -> dict[str, Any]:
    receipts = _data_dir() / "receipts.jsonl"
    return {"work_orders": work_orders(receipts)}
