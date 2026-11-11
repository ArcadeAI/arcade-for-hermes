"""Receipts: one JSON line per governed call. Never a token, never a document body.

A receipt names the actor (role and Arcade principal), the tool, the verb, the decision, the approver
when the approval gate answered, the work order, and the external URL of the artifact when the result
carried one. Inputs are summarized: strings are truncated and credential-looking keys are redacted.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

SCHEMA_VERSION = 1
MAX_STRING = 80
MAX_LIST = 10
MAX_DEPTH = 3
_SENSITIVE = ("authorization", "api_key", "apikey", "token", "secret", "password", "cookie", "bearer", "credential")
_URL_KEYS = ("html_url", "url", "documentUrl", "document_url", "webViewLink", "web_view_link", "link", "permalink")


def summarize_input(value: Any, depth: int = 0) -> Any:
    """A bounded, redacted copy of a tool input suitable for a receipt."""
    if depth > MAX_DEPTH:
        return "[...]"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            k = str(key)
            if any(word in k.lower() for word in _SENSITIVE):
                out[k] = "[redacted]"
            else:
                out[k] = summarize_input(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_LIST:
            return f"[{len(value)} items]"
        return [summarize_input(v, depth + 1) for v in value]
    if isinstance(value, str):
        return value if len(value) <= MAX_STRING else value[:MAX_STRING] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:MAX_STRING]


def extract_url(result: Any, depth: int = 0) -> Optional[str]:
    """First http(s) URL found under a well-known key, searching nested dicts a few levels deep."""
    if depth > 4 or not isinstance(result, Mapping):
        return None
    for key in _URL_KEYS:
        value = result.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    for value in result.values():
        if isinstance(value, Mapping):
            found = extract_url(value, depth + 1)
            if found:
                return found
        elif isinstance(value, list):
            for item in value[:5]:
                found = extract_url(item, depth + 1)
                if found:
                    return found
    return None


class WaitingBoard:
    """The ship actions waiting on the founder right now, as a small JSON file next to the receipts.

    The approval card lives in the gateway's memory; the dashboard runs in another process. This is
    the one shared fact it needs ("someone is at the founder's door"): set when the governor raises
    the card, cleared when the call resolves. Entries older than ``max_age`` are dropped on every
    write, so a crashed gateway cannot leave a ghost at the door."""

    def __init__(self, path: Path | str, max_age: float = 900.0) -> None:
        self.path = Path(path)
        self.max_age = max_age
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex[:6]}.tmp")
        tmp.write_text(json.dumps(data, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(self.path)

    def _fresh(self, data: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).timestamp()
        return {k: v for k, v in data.items() if isinstance(v, dict) and now - float(v.get("since", 0)) <= self.max_age}

    def add(self, key: str, **fields: Any) -> None:
        row = {k: (summarize_input(v) if k == "input" else v) for k, v in fields.items() if v is not None}
        row["since"] = datetime.now(timezone.utc).timestamp()
        with self._lock:
            data = self._fresh(self._load())
            data[key] = row
            self._save(data)

    def remove(self, key: str) -> None:
        with self._lock:
            data = self._load()
            if key in data:
                data.pop(key, None)
                self._save(self._fresh(data))

    def read(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._fresh(self._load())
        return sorted(({"key": k, **v} for k, v in data.items()), key=lambda r: r.get("since", 0))


class ReceiptStore:
    """Append-only JSONL store with a process lock. Reads return newest first."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, **fields: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "v": SCHEMA_VERSION,
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        for key, value in fields.items():
            if value is None:
                continue
            row[key] = summarize_input(value) if key == "input" else value
        line = json.dumps(row, sort_keys=True, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
        return row

    def read(self, work_order: Optional[str] = None, role: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self._lock:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if work_order and row.get("work_order") != work_order:
                continue
            if role and row.get("role") != role:
                continue
            rows.append(row)
        rows.reverse()
        return rows[:limit]
