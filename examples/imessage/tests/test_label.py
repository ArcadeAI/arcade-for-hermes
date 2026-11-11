"""Every text the real BlueBubbles adapter posts starts with "Hermes: ", exactly once.

Drives Hermes's own BlueBubblesAdapter (plain send, multi-paragraph send, the approval text the
gateway sends on a platform without buttons) with only the HTTP client faked.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

bb = pytest.importorskip("plugins.platforms.bluebubbles.adapter")
from gateway.config import PlatformConfig  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("imessage_label", ROOT / "imessage_label" / "__init__.py")
label = importlib.util.module_from_spec(spec)
spec.loader.exec_module(label)


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"status": 200, "data": {"guid": "g-1"}}


class FakeClient:
    def __init__(self):
        self.posts = []

    async def post(self, url, json=None, **kw):
        self.posts.append((url, json))
        return FakeResponse()


@pytest.fixture
def adapter(monkeypatch):
    label.wrap(bb.BlueBubblesAdapter)
    a = bb.BlueBubblesAdapter(PlatformConfig(extra={"server_url": "http://127.0.0.1:1234", "password": "pw"}))
    a.client = FakeClient()

    async def guid(_chat):
        return "iMessage;-;+15550000000"

    monkeypatch.setattr(a, "_resolve_chat_guid", guid)
    return a


def _texts(a):
    return [body["message"] for _, body in a.client.posts if "message" in body]


def test_a_plain_send_arrives_labeled(adapter):
    asyncio.run(adapter.send("+15550000000", "Book is $10,000 cash, PAPER MODE."))
    assert _texts(adapter) == ["Hermes: Book is $10,000 cash, PAPER MODE."]


def test_a_multi_paragraph_reply_is_one_tidy_bubble_labeled_once(adapter):
    asyncio.run(adapter.send("+15550000000", "**First** part.  \n\n\n\nSecond part.\n\n- a\n- b"))
    assert _texts(adapter) == ["Hermes: First part.\n\nSecond part.\n\na\nb"] or \
        _texts(adapter) == ["Hermes: First part.\n\nSecond part.\n\n- a\n- b"]
    assert "\u2063" not in _texts(adapter)[0]


def test_the_label_is_never_doubled(adapter):
    asyncio.run(adapter.send("+15550000000", "Hermes: already labeled."))
    assert _texts(adapter) == ["Hermes: already labeled."]


def test_a_reply_over_the_length_limit_still_splits_and_every_piece_is_labeled(adapter):
    long = "\n\n".join(["word " * 300] * 4)
    asyncio.run(adapter.send("+15550000000", long))
    bubbles = _texts(adapter)
    assert len(bubbles) > 1 and all(b.startswith("Hermes: ") and "\u2063" not in b for b in bubbles)


def test_an_approval_request_arrives_labeled(adapter):
    from gateway.run import _format_exec_approval_fallback

    text = _format_exec_approval_fallback(
        "SHIP: cos wants koopa_execute on koopa for BC-2026-004", "plugin approval rule", "/")
    asyncio.run(adapter.send("+15550000000", text, metadata={"is_approval_prompt": True}))
    bubbles = _texts(adapter)
    assert bubbles and all(b.startswith("Hermes: ") for b in bubbles)
    assert any("koopa_execute" in b for b in bubbles)


def test_the_adapter_the_registry_builds_is_labeled_even_from_another_module_copy(monkeypatch):
    """Live run 2026-11-08: the gateway loads BlueBubbles as hermes_plugins.platforms__bluebubbles,
    a second class object, so wrapping the import-path class left real replies unlabeled."""
    import types

    from gateway.platform_registry import PlatformRegistry

    class OtherCopy:  # stands in for the separately loaded adapter class
        async def _post_message(self, path, payload):
            self.sent = payload["message"]

    label.wrap_registry(PlatformRegistry)
    monkeypatch.setattr(PlatformRegistry, "get", lambda self, name: types.SimpleNamespace(
        check_fn=lambda: True, ensure_deps_fn=None, install_hint="", validate_config=None,
        adapter_factory=lambda cfg: OtherCopy(), label="BlueBubbles"), raising=False)
    a = PlatformRegistry().create_adapter("bluebubbles", object())
    asyncio.run(a._post_message("/api/v1/message/text", {"message": "reply"}))
    assert a.sent == "Hermes: reply"


def test_wrapping_twice_is_a_no_op(adapter):
    label.wrap(bb.BlueBubblesAdapter)
    asyncio.run(adapter.send("+15550000000", "once"))
    assert _texts(adapter) == ["Hermes: once"]
