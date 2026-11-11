"""The founder's kill switch and the daily money tally.

``halt.json`` sits next to the receipts. While it exists, the policy denies every draft and ship call
except rules marked ``exit`` (closing a position, cancelling an order), which still go to the card:
traders asked that exits never be blocked. ``/arcade halt [reason]`` writes it, ``/arcade resume``
removes it; both work from any surface that runs slash commands, the phone included.

The daily tally is read from the receipts, not kept in memory, so it survives restarts and is the
same number the audit shows: the sum of ``amount`` on this role's calls that ran (decision allowed or
approved, outcome ok) since midnight UTC.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .receipts import ReceiptStore

_RAN = {"allowed", "approved"}


class HaltSwitch:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def state(self) -> Optional[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            # An unreadable switch fails closed: treat it as on.
            return {"reason": "halt file unreadable", "ts": None}
        return data if isinstance(data, dict) else {"reason": "halt file malformed", "ts": None}

    def reason(self) -> Optional[str]:
        state = self.state()
        if state is None:
            return None
        return str(state.get("reason") or "no reason given")

    def halt(self, reason: str = "", by: str = "") -> dict[str, Any]:
        state = {"reason": (reason or "no reason given").strip()[:200], "by": by or None,
                 "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".halt.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, self.path)
        return state

    def resume(self) -> bool:
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


def spent_today(receipts: ReceiptStore, role: str, now: Optional[float] = None) -> float:
    day = datetime.fromtimestamp(now if now is not None else time.time(), timezone.utc).strftime("%Y-%m-%d")
    total = 0.0
    for row in receipts.read(role=role, limit=100_000):
        if not str(row.get("ts", "")).startswith(day):
            continue
        if row.get("decision") in _RAN and row.get("outcome") == "ok":
            try:
                total += float(row.get("amount") or 0)
            except (TypeError, ValueError):
                continue
    return total
