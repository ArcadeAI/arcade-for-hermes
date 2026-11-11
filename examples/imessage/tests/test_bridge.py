"""The bridge forwards exactly the texts that belong to Hermes, and nothing it logs carries text."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("bluebubbles_bridge", ROOT / "scripts" / "bluebubbles_bridge.py")
bridge_mod = importlib.util.module_from_spec(spec)
sys.modules["bluebubbles_bridge"] = bridge_mod  # dataclasses resolve annotations via sys.modules
spec.loader.exec_module(bridge_mod)

ME = "+15550001111"
ALLOWED = frozenset({ME})
NOW = int(time.time() * 1000)


def msg(guid, text="buy the dip?", sender=ME, chat="iMessage;-;+15550001111", created=None, **kw):
    return {"guid": guid, "text": text, "isFromMe": False, "dateCreated": created or NOW + 1000,
            "handle": {"address": sender}, "chats": [{"guid": chat}], **kw}


@pytest.fixture
def route(tmp_path):
    path = tmp_path / "route.json"

    def set_route(active=True, since=NOW - 60_000):
        path.write_text(json.dumps({"target": "hermes" if active else "none",
                                    "until": NOW + 3_600_000 if active else 0, "since": since}))
        return path
    return set_route


def bridge(route_path, rows_by_call):
    sent = []

    def post(url, body):
        if "/message/query" in url:
            return {"data": rows_by_call.pop(0) if rows_by_call else []}
        sent.append((url, body))
        return {}
    b = bridge_mod.Bridge("p@ss w0rd/&", ALLOWED, route_path=route_path, post=post, after=NOW)
    return b, sent


@pytest.mark.parametrize("m, why", [
    (msg("g-from-me", isFromMe=True), "skip:from_me"),
    (msg("g-group", chat="iMessage;+;chat123"), "skip:group"),
    (msg("g-stranger", sender="+15559999999"), "skip:sender"),
    (msg("g-hand", text="Hermes"), "skip:control"),
    (msg("g-hand2", text="talk to hermes!"), "skip:control"),
    (msg("g-back", text=" back. "), "skip:control"),
    (msg("g-off", text="stop hermes"), "skip:control"),
    (msg("g-old", created=NOW - 120_000), "skip:before_route"),
])
def test_only_hermes_texts_are_forwarded(route, m, why):
    b, sent = bridge(route(), [[m]])
    assert b.poll_once() == [(m["guid"][:8], why)] and sent == []


def test_a_routed_text_is_forwarded_once_as_a_webhook_event_with_the_password_url_encoded(route):
    m = msg("g-ok-1")
    b, sent = bridge(route(), [[m], [m]])
    assert b.poll_once() == [("g-ok-1"[:8], "forward")]
    assert b.poll_once() == []                      # deduped by guid on the next poll
    (url, body), = sent
    assert url.startswith("http://127.0.0.1:8645/bluebubbles-webhook?password=p%40ss%20w0rd%2F%26")
    assert body == {"type": "new-message", "data": m}


def test_nothing_reaches_hermes_while_the_route_is_inactive(route, tmp_path):
    b, sent = bridge(route(active=False), [[msg("g-a"), msg("g-b")]])
    assert {d for _, d in b.poll_once()} == {"skip:route_inactive"} and sent == []
    b2, sent2 = bridge(tmp_path / "missing.json", [[msg("g-c")]])
    assert b2.poll_once() == [("g-c", "skip:route_inactive")] and sent2 == []


def test_the_query_starts_now_and_advances_with_date_created(route):
    seen = []
    b = bridge_mod.Bridge("pw", ALLOWED, route_path=route(), post=lambda url, body: None)
    assert abs(b.after - int(time.time() * 1000)) < 5000
    later = b.after + 5000  # relative to the bridge's own start, so a slow suite cannot make it stale

    def post(url, body):
        if "/message/query" in url:
            seen.append(body["after"])
            return {"data": [msg("g-1", created=later)]} if len(seen) == 1 else {"data": []}
        return {}
    b.post = post
    b.poll_once()
    b.poll_once()
    assert seen[1] == later


def test_a_plain_text_webhook_answer_still_logs_the_forward(route, monkeypatch):
    """Live run 2026-11-08: Hermes answers the webhook with plain 'ok'; parsing it as JSON raised
    after the forward, so the decision was lost and the poll reported a failure."""
    class Res:
        def __init__(self, body): self.body = body
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen(req, timeout=10):
        if "/message/query" in req.full_url:
            return Res(json.dumps({"data": [msg("g-live-1")]}).encode())
        return Res(b"ok")
    monkeypatch.setattr(bridge_mod.urllib.request, "urlopen", urlopen)
    b = bridge_mod.Bridge("pw", ALLOWED, route_path=route(), after=NOW)
    assert b.poll_once() == [("g-live-1", "forward")]


def test_logs_never_carry_message_text_or_sender(route, caplog):
    caplog.set_level(logging.INFO)
    b, _ = bridge(route(), [[msg("g-secret", text="my account number is 1234"), msg("g-x", sender="+15559999999")]])
    b.poll_once()
    out = caplog.text
    assert "1234" not in out and "account" not in out and "+1555" not in out
    assert "g-secret"[:8] in out
