"""Koopa: a paper-trading desk on fixture prices. PAPER MODE everywhere, MOCK on every fill.

State lives under one directory (the launch Hermes home's plugin-data/koopa by default) so every
role sees the same book: account.json (cash and positions), proposals.json, ledger.jsonl.
Fixtures ship with the plugin and the reset script restores them between takes.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

PAPER = "PAPER MODE"
POLICY_VERSION = "risk-paper-v1"
def _ttl() -> timedelta:
    # A committee of slow models plus a human on a phone took over an hour in practice, so the
    # default is four; KOOPA_PROPOSAL_TTL_MINUTES overrides it.
    try:
        minutes = float(os.environ.get("KOOPA_PROPOSAL_TTL_MINUTES", "240"))
    except ValueError:
        minutes = 240.0
    return timedelta(minutes=minutes if minutes > 0 else 240.0)


PROPOSAL_TTL = _ttl()
_LOCK = threading.Lock()   # threads in one process; the file lock below covers every process


def _atomic_write(path: Path, text: str) -> None:
    # A reader never sees a half-written file, and a shorter write never leaves the tail of a longer one.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class Desk:
    def __init__(self, state_dir: Path, fixtures_dir: Path, broker: Any = None) -> None:
        self.state_dir = Path(state_dir)
        self.fixtures_dir = Path(fixtures_dir)
        self.broker = broker               # None: MOCK fills. Else an object with submit(symbol, notional, client_order_id).
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _locked(self):
        """One writer at a time across threads AND processes. Hermes loads this plugin once per
        profile, so a swarm of subagents holds many copies of the module and a module lock alone
        lets them race (seen: duplicate proposal IDs and a corrupted proposals.json at 84 agents)."""
        with _LOCK:
            with (self.state_dir / ".koopa.lock").open("a") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    # ------------------------------------------------------------------ files
    @property
    def account_path(self) -> Path:
        return self.state_dir / "account.json"

    @property
    def proposals_path(self) -> Path:
        return self.state_dir / "proposals.json"

    @property
    def ledger_path(self) -> Path:
        return self.state_dir / "ledger.jsonl"

    def reset(self) -> None:
        """Restore the fixtures: the book, no proposals, an empty ledger, fresh price timestamps."""
        account = json.loads((self.fixtures_dir / "account.json").read_text())
        prices = json.loads((self.fixtures_dir / "prices.json").read_text())
        for p in prices.values():
            p["as_of"] = _iso(_now())
        account["prices"] = prices
        _atomic_write(self.account_path, json.dumps(account, indent=2))
        _atomic_write(self.proposals_path, "{}")
        _atomic_write(self.ledger_path, "")

    def _account(self) -> dict[str, Any]:
        if not self.account_path.exists():
            self.reset()
        return json.loads(self.account_path.read_text())

    def _save_account(self, account: dict[str, Any]) -> None:
        _atomic_write(self.account_path, json.dumps(account, indent=2))

    def _proposals(self) -> dict[str, Any]:
        if not self.proposals_path.exists():
            return {}
        return json.loads(self.proposals_path.read_text() or "{}")

    def _save_proposals(self, proposals: dict[str, Any]) -> None:
        _atomic_write(self.proposals_path, json.dumps(proposals, indent=2))

    def _ledger(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        return [json.loads(line) for line in self.ledger_path.read_text().splitlines() if line.strip()]

    def _append_ledger(self, entry: dict[str, Any]) -> None:
        with self.ledger_path.open("a") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def proposal_hash(proposal: dict[str, Any]) -> str:
        core = {k: proposal[k] for k in ("proposal_id", "symbol", "notional_usd", "price", "decision", "policy_version")}
        return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]

    def _book_value(self, account: dict[str, Any]) -> float:
        prices = account.get("prices", {})
        positions = account.get("positions", {})
        return float(account["cash_usd"]) + sum(float(q) * float(prices[s]["price"]) for s, q in positions.items() if s in prices)

    # ------------------------------------------------------------------ tools
    def propose(self, symbol: str, notional_usd: Any, work_order: Optional[str] = None) -> dict[str, Any]:
        with self._locked():
            account = self._account()
            symbol = str(symbol or "").upper().strip()
            try:
                notional = float(notional_usd)
            except (TypeError, ValueError):
                notional = float("nan")
            reasons: list[str] = []
            if not symbol or symbol not in account.get("allowlist", []):
                reasons.append(f"{symbol or '(none)'} is not on the allow-list {account.get('allowlist', [])}")
            if not (notional > 0):
                reasons.append("long-only: notional must be a positive number")
            cash = float(account["cash_usd"])
            if notional > cash:
                reasons.append(f"notional ${notional:,.0f} exceeds cash ${cash:,.0f}")
            cap = float(account.get("max_position_pct", 0.4))
            book = self._book_value(account)
            if notional > cap * book:
                reasons.append(f"notional ${notional:,.0f} exceeds {cap:.0%} of the book (${cap * book:,.0f})")
            price_row = account.get("prices", {}).get(symbol)
            price = None
            if price_row is None:
                reasons.append(f"no fixture price for {symbol}")
            else:
                price = float(price_row["price"])
                age = (_now() - _parse(price_row["as_of"])).total_seconds()
                limit = float(account.get("staleness_limit_seconds", 86400))
                if age > limit:
                    reasons.append(f"fixture price for {symbol} is {age / 3600:.1f}h old; limit {limit / 3600:.0f}h")
            proposals = self._proposals()
            pid = f"PR-{len(proposals) + 1:03d}"
            proposal = {
                "proposal_id": pid, "symbol": symbol, "notional_usd": notional if notional == notional else None,
                "price": price, "price_label": "FIXTURE", "decision": "REJECT" if reasons else "PASS",
                "reasons": reasons, "policy_version": POLICY_VERSION, "work_order": work_order,
                "created_at": _iso(_now()), "expires_at": _iso(_now() + PROPOSAL_TTL), "executed_order_id": None,
            }
            proposal["hash"] = self.proposal_hash(proposal)
            proposals[pid] = proposal
            self._save_proposals(proposals)
            self._append_ledger({"ts": proposal["created_at"], "kind": "proposal", **{k: proposal[k] for k in ("proposal_id", "symbol", "notional_usd", "decision", "hash", "work_order")}})
            return {"label": PAPER, **{k: proposal[k] for k in ("proposal_id", "hash", "decision", "reasons", "policy_version", "symbol", "notional_usd", "price", "price_label", "expires_at", "work_order")}}

    def _refusal(self, proposals: dict, proposal_id: Any, hash_: Any) -> Optional[dict[str, Any]]:
        """Why this proposal can never execute right now (unknown, tampered, rejected, expired), or
        None. Already-executed is not a refusal: execute answers it idempotently."""
        proposal = proposals.get(str(proposal_id or ""))
        if proposal is None:
            return {"label": PAPER, "error": f"unknown proposal {proposal_id!r}; nothing executed"}
        if str(hash_ or "") != proposal["hash"] or self.proposal_hash(proposal) != proposal["hash"]:
            return {"label": PAPER, "error": "hash does not match the proposal; nothing executed", "proposal_id": proposal["proposal_id"]}
        if proposal["decision"] != "PASS":
            return {"label": PAPER, "error": f"proposal {proposal_id} was rejected: {'; '.join(proposal['reasons'])}; nothing executed"}
        if not proposal.get("executed_order_id") and _now() > _parse(proposal["expires_at"]):
            return {"label": PAPER, "error": f"proposal {proposal_id} expired at {proposal['expires_at']}; nothing executed"}
        return None

    def preflight(self, proposal_id: Any, hash_: Any) -> Optional[str]:
        """Read-only: the reason execute would refuse, so the founder is never asked to approve an
        order that cannot happen (a card for an expired proposal was seen live). None = ask."""
        with self._locked():
            proposals = self._proposals()
            refusal = self._refusal(proposals, proposal_id, hash_)
            if refusal:
                return refusal["error"]
            done = proposals[str(proposal_id)].get("executed_order_id")
            return f"proposal {proposal_id} already executed as {done}; no second fill, nothing to approve" if done else None

    def execute(self, proposal_id: str, hash_: str, work_order: Optional[str] = None) -> dict[str, Any]:
        with self._locked():
            proposals = self._proposals()
            refusal = self._refusal(proposals, proposal_id, hash_)
            if refusal:
                return refusal
            proposal = proposals[str(proposal_id)]
            if proposal.get("executed_order_id"):
                order = next((e for e in self._ledger() if e.get("kind") == "fill" and e.get("order_id") == proposal["executed_order_id"]), None)
                return {"label": PAPER, "order_id": proposal["executed_order_id"], "duplicate": True,
                        "fill": order.get("fill") if order else None, "note": "already executed; no second fill"}
            account = self._account()
            price = float(proposal["price"])
            qty = round(float(proposal["notional_usd"]) / price, 4)
            cost = round(qty * price, 2)
            if cost > float(account["cash_usd"]) + 1e-9:
                return {"label": PAPER, "error": "insufficient cash at execution; nothing executed"}
            broker_order = None
            if self.broker is not None:
                # The idempotency key is the proposal itself, so a retry can never place a second order.
                key = f"koopa-{proposal['proposal_id']}-{proposal['hash']}"
                try:
                    broker_order = self.broker.submit(proposal["symbol"], float(proposal["notional_usd"]), key)
                except Exception as exc:
                    return {"label": PAPER, "error": f"broker did not place the order: {exc}; nothing booked",
                            "proposal_id": proposal["proposal_id"], "client_order_id": key}
            order_id = f"ORD-{sum(1 for e in self._ledger() if e.get('kind') == 'fill') + 1:03d}"
            fill = {"qty": qty, "price": price, "label": broker_order["broker"] if broker_order else "MOCK", "cost_usd": cost}
            if broker_order:
                fill["broker_order"] = broker_order
                try:
                    b_qty, b_px = float(broker_order["filled_qty"]), float(broker_order["filled_avg_price"])
                except (KeyError, TypeError, ValueError):
                    b_qty = b_px = 0.0
                if broker_order.get("status") == "filled" and b_qty > 0 and b_px > 0:
                    # Book what the broker actually filled; spend the notional, never more.
                    qty, price = b_qty, b_px
                    cost = min(round(b_qty * b_px, 2), float(proposal["notional_usd"]))
                    fill.update(qty=qty, price=price, cost_usd=cost, book_price_label="BROKER FILL")
                else:
                    fill["book_price_label"] = "FIXTURE ESTIMATE (broker fill not yet reported)"
            account["cash_usd"] = round(float(account["cash_usd"]) - cost, 2)
            account.setdefault("positions", {})
            account["positions"][proposal["symbol"]] = round(float(account["positions"].get(proposal["symbol"], 0)) + qty, 4)
            self._save_account(account)
            proposal["executed_order_id"] = order_id
            proposals[proposal["proposal_id"]] = proposal
            self._save_proposals(proposals)
            self._append_ledger({"ts": _iso(_now()), "kind": "fill", "order_id": order_id, "proposal_id": proposal["proposal_id"],
                                 "symbol": proposal["symbol"], "fill": fill, "cash_after": account["cash_usd"],
                                 "work_order": work_order or proposal.get("work_order")})
            return {"label": PAPER, "order_id": order_id, "proposal_id": proposal["proposal_id"], "symbol": proposal["symbol"],
                    "fill": fill, "cash_after_usd": account["cash_usd"], "work_order": work_order or proposal.get("work_order")}

    def report(self) -> dict[str, Any]:
        with self._locked():
            account = self._account()
            ledger = self._ledger()
            fills = [e for e in ledger if e.get("kind") == "fill"]
            from_ledger: dict[str, float] = {}
            spent = 0.0
            for e in fills:
                from_ledger[e["symbol"]] = round(from_ledger.get(e["symbol"], 0) + float(e["fill"]["qty"]), 4)
                spent += float(e["fill"]["cost_usd"])
            positions = {s: round(float(q), 4) for s, q in account.get("positions", {}).items() if q}
            start_cash = float(json.loads((self.fixtures_dir / "account.json").read_text())["cash_usd"])
            reconciled = positions == {s: q for s, q in from_ledger.items() if q} and abs(start_cash - spent - float(account["cash_usd"])) < 0.01
            prices = account.get("prices", {})
            market = {s: round(q * float(prices[s]["price"]), 2) for s, q in positions.items() if s in prices}
            return {
                "label": PAPER, "cash_usd": account["cash_usd"], "positions": positions, "market_value_usd": market,
                "book_value_usd": round(float(account["cash_usd"]) + sum(market.values()), 2),
                "pnl_usd": round(float(account["cash_usd"]) + sum(market.values()) - start_cash, 2),
                "prices": {s: {"price": p["price"], "label": p.get("label", "FIXTURE"), "as_of": p["as_of"]} for s, p in prices.items()},
                "reconciliation": {"ledger_positions": from_ledger, "ledger_spent_usd": round(spent, 2),
                                   "starting_cash_usd": start_cash, "reconciled": reconciled},
                "ledger_lines": len(ledger), "fills": [{"order_id": e["order_id"], "symbol": e["symbol"], **e["fill"]} for e in fills],
            }
