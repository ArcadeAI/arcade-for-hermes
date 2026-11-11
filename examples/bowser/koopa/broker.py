"""Optional Alpaca paper broker for Koopa, through an Arcade-hosted ArcadeAlpaca toolkit.

Off unless ``KOOPA_BROKER=alpaca``. It only runs inside ``koopa_execute``, which is a ship action,
so every order has already passed Koopa's risk checks and a human Allow on the approval card.
Before any order it asks ``ArcadeAlpaca.GetAccount`` which endpoint it is on and refuses unless
the answer is the paper endpoint. The order tools themselves are not granted to any role.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Optional

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
TOOLKIT = "ArcadeAlpaca"


class BrokerRefused(RuntimeError):
    """The broker did not place the order. The message is safe to show."""


def _secret(name: str) -> Optional[str]:
    try:
        from agent.secret_scope import get_secret
    except ImportError:
        return os.environ.get(name) or None
    return get_secret(name) or None


def _arcade():
    key = _secret("ARCADE_API_KEY")
    if not key:
        raise BrokerRefused("ARCADE_API_KEY is not set; no order placed")
    from arcadepy import Arcade

    base_url = _secret("ARCADE_BASE_URL")
    return Arcade(api_key=key, base_url=base_url) if base_url else Arcade(api_key=key)


def _call(client, tool: str, args: dict[str, Any], user_id: str) -> Any:
    resp = client.tools.execute(tool_name=f"{TOOLKIT}.{tool}", input=args, user_id=user_id)
    output = getattr(resp, "output", None)
    error = getattr(output, "error", None) if output is not None else None
    if getattr(resp, "success", None) is False or error:
        message = getattr(error, "message", None) or str(error or getattr(resp, "status", "failed"))
        raise BrokerRefused(f"{TOOLKIT}.{tool} failed: {message}")
    return getattr(output, "value", None)


class AlpacaPaperBroker:
    name = "ALPACA PAPER"

    def __init__(self, client_factory: Callable[[], Any] = _arcade, user_id: Optional[str] = None,
                 fill_polls: int = 5, sleep: Callable[[float], None] = time.sleep) -> None:
        self._client_factory = client_factory
        self.user_id = user_id or os.environ.get("KOOPA_ARCADE_USER_ID") or "bowser/cos"
        self.fill_polls = fill_polls
        self._sleep = sleep

    def submit(self, symbol: str, notional_usd: float, client_order_id: str) -> dict[str, Any]:
        client = self._client_factory()
        account = _call(client, "GetAccount", {}, self.user_id) or {}
        if account.get("is_paper") is not True or str(account.get("endpoint", "")).rstrip("/") != PAPER_ENDPOINT:
            raise BrokerRefused(f"the Alpaca account is not on the paper endpoint ({account.get('endpoint')!r}); no order placed")
        if account.get("trading_blocked") or account.get("account_blocked"):
            raise BrokerRefused("the Alpaca paper account is blocked from trading; no order placed")
        # Crypto pairs (BTC/USD) trade around the clock and Alpaca accepts only gtc or ioc for them.
        tif = "gtc" if "/" in symbol else "day"
        order = _call(client, "SubmitOrder", {
            "symbol": symbol, "side": "buy", "notional": f"{float(notional_usd):.2f}",
            "order_type": "market", "time_in_force": tif, "client_order_id": client_order_id,
        }, self.user_id) or {}
        # Crypto market orders usually fill within a second or two; wait briefly so the book can
        # carry the broker's own fill. Anything slower is booked at the estimate and says so.
        for _ in range(self.fill_polls):
            if order.get("status") == "filled" or not order.get("id"):
                break
            self._sleep(1.0)
            try:
                order = _call(client, "GetOrder", {"order_id": order["id"]}, self.user_id) or order
            except BrokerRefused:
                break
        return {"broker": self.name, "endpoint": PAPER_ENDPOINT, "order_id": order.get("id"),
                "filled_qty": order.get("filled_qty"), "filled_avg_price": order.get("filled_avg_price"),
                "client_order_id": order.get("client_order_id", client_order_id), "status": order.get("status"),
                "symbol": order.get("symbol", symbol), "notional": order.get("notional")}


def from_env() -> Optional[AlpacaPaperBroker]:
    choice = (os.environ.get("KOOPA_BROKER") or "").strip().lower()
    if not choice or choice == "mock":
        return None
    if choice != "alpaca":
        raise BrokerRefused(f"KOOPA_BROKER must be 'alpaca' or unset, got {choice!r}")
    return AlpacaPaperBroker()
