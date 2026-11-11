"""The floor's activity feed: who is thinking right now, the one line they said before acting, and
the local Hermes tools they reached for (the toolbox). It is a view and never a record: receipts stay
the audit trail. Nothing here can block or change a call, and every write swallows its own errors.

One JSON line per event in ``activity.jsonl`` next to the receipts. Each line carries ``n``, a
nanosecond clock that only grows, so a reader asks for "after n" and the file can be trimmed without
renumbering. Spoken lines are cut to one short sentence with links, addresses and long tokens
scrubbed: a thought bubble should show intent, not leak a document or a credential.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

MAX_TEXT = 96
MAX_BYTES = 512_000
KEEP_LINES = 400

_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_MARKUP = re.compile(r"[`*_#>|]+")


def scrub(text: Any) -> str:
    """One short, safe line from whatever the model said."""
    s = str(text or "")
    s = _URL.sub("[link]", s)
    s = _EMAIL.sub("[address]", s)
    s = _TOKEN.sub("[id]", s)
    s = _PHONE.sub("[number]", s)
    s = _MARKUP.sub("", s)
    s = " ".join(s.split())
    # the first sentence carries the intent; the rest is usually a list or a quote
    m = re.match(r"(.+?[.!?])(\s|$)", s)
    if m and len(m.group(1)) >= 12:
        s = m.group(1)
    return s if len(s) <= MAX_TEXT else s[: MAX_TEXT - 3].rstrip() + "..."


class ActivityFeed:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._last = 0

    def _n(self) -> int:
        n = time.time_ns()
        if n <= self._last:
            n = self._last + 1
        self._last = n
        return n

    def add(self, kind: str, role: Optional[str], profile: Optional[str] = None, **fields: Any) -> None:
        row: dict[str, Any] = {"kind": kind, "role": role, "profile": profile}
        for k, v in fields.items():
            if v is None:
                continue
            row[k] = scrub(v) if k == "text" else (str(v)[:64] if isinstance(v, str) else v)
        try:
            with self._lock:
                row["n"] = self._n()
                row["ts"] = time.time()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
                if self.path.stat().st_size > MAX_BYTES:
                    lines = self.path.read_text(encoding="utf-8").splitlines()[-KEEP_LINES:]
                    tmp = self.path.with_name(f".{self.path.name}.tmp")
                    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    tmp.replace(self.path)
        except OSError:
            pass


def read_activity(path: Path | str, after: int = 0, limit: int = 300) -> list[dict[str, Any]]:
    """Events newer than ``after`` (the reader's last ``n``), oldest first."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and int(row.get("n") or 0) > after:
            out.append({k: row.get(k) for k in ("n", "ts", "kind", "role", "profile", "tool", "text", "model") if row.get(k) is not None})
    return out[-limit:]
