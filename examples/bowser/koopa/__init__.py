"""Koopa plugin registration: three tools and one pre_tool_call veto. PAPER MODE only."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
FIXTURES = _HERE / "fixtures"


def _state_dir() -> Path:
    override = os.environ.get("KOOPA_STATE_DIR")
    if override:
        return Path(override)
    try:
        from hermes_constants import get_process_hermes_home

        return Path(get_process_hermes_home()) / "plugin-data" / "koopa"
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes") / "plugin-data" / "koopa"


def _desk(broker=None):
    from .koopa import Desk

    return Desk(_state_dir(), FIXTURES, broker=broker)


def _execute_desk():
    from .broker import from_env

    return _desk(from_env())


def koopa_propose(args: dict, **kwargs) -> str:
    try:
        return json.dumps(_desk().propose(args.get("symbol"), args.get("notional_usd"), args.get("work_order")))
    except Exception as exc:
        return json.dumps({"label": "PAPER MODE", "error": f"koopa_propose failed: {type(exc).__name__}: {exc}"})


def koopa_execute(args: dict, **kwargs) -> str:
    try:
        return json.dumps(_execute_desk().execute(args.get("proposal_id"), args.get("hash"), args.get("work_order")))
    except Exception as exc:
        return json.dumps({"label": "PAPER MODE", "error": f"koopa_execute failed: {type(exc).__name__}: {exc}"})


def pre_tool_call(tool_name: str = "", args: Optional[dict] = None, **kwargs) -> Optional[dict]:
    """Veto koopa_execute when the proposal can never execute, so no approval card is raised for
    it. Hermes ranks block above approve whatever the plugin order, so this wins over the Arcade
    governor's ship-tier approve. Errors here never block: execute re-checks everything itself."""
    if tool_name != "koopa_execute":
        return None
    args = args if isinstance(args, dict) else {}
    try:
        reason = _desk().preflight(args.get("proposal_id"), args.get("hash"))
    except Exception:
        return None
    if reason:
        return {"action": "block", "message": json.dumps({"label": "PAPER MODE", "error": reason, "approval": "not requested"})}
    return None


def koopa_report(args: dict, **kwargs) -> str:
    try:
        return json.dumps(_desk().report())
    except Exception as exc:
        return json.dumps({"label": "PAPER MODE", "error": f"koopa_report failed: {type(exc).__name__}: {exc}"})


SCHEMAS = {
    "koopa_propose": {
        "name": "koopa_propose",
        "description": ("PAPER MODE. Propose a long-only paper trade and run Bowser Capital's deterministic risk checks "
                        "(allow-list, notional <= cash, notional <= 40% of the book, fresh fixture price). Returns a "
                        "proposal_id, a hash, PASS or REJECT with reasons. Nothing is executed."),
        "parameters": {"type": "object", "properties": {
            "symbol": {"type": "string", "description": "Crypto pair on the allow-list, e.g. BTC/USD (24/7 assets only)"},
            "notional_usd": {"type": "number", "description": "Dollar amount to buy"},
            "work_order": {"type": "string", "description": "Work-order ID, e.g. BC-2026-001"}},
            "required": ["symbol", "notional_usd"]},
    },
    "koopa_execute": {
        "name": "koopa_execute",
        "description": ("PAPER MODE. Execute a PASS proposal: a MOCK fill at the fixture price, or, when the desk is set "
                        "to KOOPA_BROKER=alpaca, a market order on an Alpaca paper account. This is a ship action: "
                        "it waits for the founder's approval in Hermes's gate. Needs the proposal_id and its hash exactly "
                        "as koopa_propose returned them. Executing the same proposal twice returns the same order."),
        "parameters": {"type": "object", "properties": {
            "proposal_id": {"type": "string"}, "hash": {"type": "string"},
            "work_order": {"type": "string", "description": "Work-order ID, e.g. BC-2026-001"}},
            "required": ["proposal_id", "hash"]},
    },
    "koopa_report": {
        "name": "koopa_report",
        "description": "PAPER MODE. Positions, cash, MOCK fills, and a ledger-to-book reconciliation. Every number traces to a ledger line.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def register(ctx) -> None:
    ctx.register_tool(name="koopa_propose", toolset="koopa", schema=SCHEMAS["koopa_propose"], handler=koopa_propose,
                      description="Propose a paper trade (deterministic risk checks)", emoji="🐢")
    ctx.register_tool(name="koopa_execute", toolset="koopa", schema=SCHEMAS["koopa_execute"], handler=koopa_execute,
                      description="Execute a passed proposal with a MOCK fill (ship action)", emoji="🐢")
    ctx.register_tool(name="koopa_report", toolset="koopa", schema=SCHEMAS["koopa_report"], handler=koopa_report,
                      description="Positions, cash and reconciliation", emoji="🐢")
    ctx.register_hook("pre_tool_call", pre_tool_call)
