"""Poll BlueBubbles and hand Hermes the texts that belong to it, as webhook events.

BlueBubbles Server 1.9.12 refuses to register a webhook to any local address, so Hermes's bundled
BlueBubbles adapter never receives messages by itself. Its listener still runs on
127.0.0.1:8645/bluebubbles-webhook, so this bridge polls the same REST API P2 polls and forwards
each message Hermes should see as {"type": "new-message", "data": <message>}.

A message is forwarded only when ALL of these hold:
  - the line is routed to Hermes: ~/.config/bluebubbles/route.json says target "hermes", its
    "until" is in the future, and the message's dateCreated >= its "since";
  - it is not from me (isFromMe), not a group chat (";+;" in the chat guid), not empty;
  - the sender (handle.address) is exactly one of ALLOWED_SENDER_IDS in ~/arcade-on-phone/.env;
  - it is not a control text P2 owns ("hermes", "hermes on", "talk to hermes", "back",
    "hermes off", "stop hermes"), matched with P2's own patterns (src/route.ts).

Secrets: the BlueBubbles password is read from ~/.config/bluebubbles/password at startup, sent only
to 127.0.0.1, and never printed. Logs carry guid prefixes and decisions, never message text or
sender addresses.

    python scripts/bluebubbles_bridge.py            # run until Ctrl+C
    python scripts/bluebubbles_bridge.py --once     # one poll, for a smoke test
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

HOME = Path.home()
PASSWORD_FILE = HOME / ".config" / "bluebubbles" / "password"
ROUTE_FILE = HOME / ".config" / "bluebubbles" / "route.json"
P2_ENV = HOME / "arcade-on-phone" / ".env"
BB_URL = "http://127.0.0.1:1234"
HERMES_WEBHOOK = "http://127.0.0.1:8645/bluebubbles-webhook"

# Same patterns as P2's src/route.ts, so exactly one agent ever answers a control text.
HANDOFF = re.compile(r"^\s*(?:hermes|hermes on|talk to hermes)\s*[.!]*\s*$", re.I)
BACK = re.compile(r"^\s*(?:back|hermes off|stop hermes)\s*[.!]*\s*$", re.I)

log = logging.getLogger("bluebubbles-bridge")


def read_password(path: Path = PASSWORD_FILE) -> str:
    value = path.read_text().strip()
    if not value:
        raise SystemExit(f"{path} is empty")
    return value


def read_allowed(path: Path = P2_ENV) -> frozenset[str]:
    for line in path.read_text().splitlines():
        if line.startswith("ALLOWED_SENDER_IDS="):
            ids = [v.strip().strip('"').strip("'") for v in line.split("=", 1)[1].split(",")]
            ids = [v for v in ids if v]
            if ids:
                return frozenset(ids)
    raise SystemExit(f"ALLOWED_SENDER_IDS is missing from {path}")


def read_route(path: Path = ROUTE_FILE) -> Optional[dict[str, Any]]:
    """The route when it is active for Hermes right now, else None (missing/expired/unreadable)."""
    try:
        r = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if r.get("target") == "hermes" and isinstance(r.get("until"), (int, float)) and r["until"] > time.time() * 1000:
        return r
    return None


def is_control(text: str) -> bool:
    return bool(HANDOFF.match(text) or BACK.match(text))


def decide(m: dict[str, Any], route: Optional[dict[str, Any]], allowed: frozenset[str]) -> str:
    """'forward' or the reason to skip. Pure, so every rule is testable without a server."""
    if m.get("isFromMe"):
        return "skip:from_me"
    chats = m.get("chats") or []
    chat_guid = (chats[0].get("guid") if chats and isinstance(chats[0], dict) else "") or ""
    if ";+;" in chat_guid:
        return "skip:group"
    sender = ((m.get("handle") or {}).get("address") or "").strip()
    if sender not in allowed:
        return "skip:sender"
    text = (m.get("text") or "").strip()
    if not text and not m.get("attachments"):
        return "skip:empty"
    if text and is_control(text):
        return "skip:control"
    if route is None:
        return "skip:route_inactive"
    created = m.get("dateCreated")
    if not isinstance(created, (int, float)) or created < route.get("since", 0):
        return "skip:before_route"
    return "forward"


@dataclass
class Bridge:
    password: str
    allowed: frozenset[str]
    route_path: Path = ROUTE_FILE
    bb_url: str = BB_URL
    webhook: str = HERMES_WEBHOOK
    after: int = field(default_factory=lambda: int(time.time() * 1000))
    seen: dict[str, None] = field(default_factory=dict)
    post: Optional[Callable[[str, dict[str, Any]], Any]] = None

    def _post(self, url: str, body: dict[str, Any]) -> Any:
        if self.post is not None:
            return self.post(url, body)
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read()
        try:
            return json.loads(raw) if raw else {}
        except ValueError:  # the Hermes webhook answers plain "ok"
            return {}

    def _query_url(self) -> str:
        return f"{self.bb_url}/api/v1/message/query?password={urllib.parse.quote(self.password, safe='')}"

    def _webhook_url(self) -> str:
        return f"{self.webhook}?password={urllib.parse.quote(self.password, safe='')}"

    def poll_once(self) -> list[tuple[str, str]]:
        """One poll. Returns (guid prefix, decision) for every new message seen."""
        body = {"limit": 50, "offset": 0, "after": self.after, "sort": "ASC", "with": ["chat", "handle", "attachment"]}
        res = self._post(self._query_url(), body) or {}
        rows = res.get("data") if isinstance(res, dict) else None
        decisions: list[tuple[str, str]] = []
        route = read_route(self.route_path)
        for m in rows or []:
            guid = str(m.get("guid") or "")
            created = m.get("dateCreated")
            if isinstance(created, (int, float)) and created > self.after:
                self.after = int(created)
            if not guid or guid in self.seen:
                continue
            self.seen[guid] = None
            while len(self.seen) > 2000:
                self.seen.pop(next(iter(self.seen)))
            decision = decide(m, route, self.allowed)
            if decision == "forward":
                try:
                    self._post(self._webhook_url(), {"type": "new-message", "data": m})
                except (urllib.error.URLError, OSError) as exc:
                    decision = f"error:webhook:{type(exc).__name__}"
            decisions.append((guid[:8], decision))
            log.info("%s %s", guid[:8], decision)
        return decisions


def main() -> None:
    ap = argparse.ArgumentParser(description="Forward Hermes's iMessage texts from BlueBubbles to its webhook")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    bridge = Bridge(read_password(), read_allowed())
    log.info("polling %s every %.0fs from now; %d allowed sender(s); route file %s",
             BB_URL, args.interval, len(bridge.allowed), ROUTE_FILE)
    while True:
        try:
            bridge.poll_once()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("poll failed: %s", type(exc).__name__)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
