"""Label every outbound BlueBubbles message with "Hermes: ".

The iMessage line is shared with another agent (P2) whose texts carry no label, so every text
Hermes sends must start with the label. Hermes has no outbound-message hook, so this wraps the one
place the BlueBubbles adapter posts text, ``BlueBubblesAdapter._post_message``: ``send()`` splits a
reply into one bubble per paragraph and posts each through it, approval requests on this platform
are plain-text ``send()`` calls (BlueBubbles renders no buttons), cron and home-channel deliveries
use the same adapter, and a new chat's first message goes through it too.

It also keeps a reply to one bubble: the adapter splits every paragraph into its own bubble, which
on a shared line read as a stack of "Hermes: " texts. Only replies over iMessage's length limit
still split, and each piece is labeled.
"""

from __future__ import annotations

import functools
import logging
import re

LABEL = "Hermes: "
_MARK = "_imessage_label_wrapped"
# The adapter's send() makes every paragraph its own bubble, so a five-paragraph reply arrived as
# five "Hermes: " bubbles. format_message (run first inside send) joins paragraphs with this
# invisible separator so send() posts one bubble; _post_message turns it back into a blank line.
_PARA = "\n\u2063\n"
logger = logging.getLogger(__name__)


def tidy(text: str) -> str:
    """Plain-text cleanup for a bubble: no trailing spaces, at most one blank line in a row."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln == "" and out and out[-1] == "":
            continue
        out.append(ln)
    return "\n".join(out).strip()


def labeled(text: str) -> str:
    """The text with the label in front, exactly once."""
    # A length split can cut a separator in half, so drop any lone one too.
    stripped = tidy(text.replace(_PARA, "\n\n").replace("\u2063", ""))
    return stripped if stripped.startswith(LABEL) else LABEL + stripped


def _one_bubble(text: str) -> str:
    return re.sub(r"\n\s*\n", _PARA, tidy(text)) if isinstance(text, str) else text


def wrap(adapter_cls) -> bool:
    """Wrap ``adapter_cls._post_message`` so any payload carrying a text ``message`` is labeled.
    Idempotent: wrapping twice is a no-op. Returns True when the class is (now) wrapped."""
    original = getattr(adapter_cls, "_post_message", None)
    if original is None:
        return False
    if getattr(original, _MARK, False):
        return True

    @functools.wraps(original)
    async def _post_message(self, path, payload):
        if isinstance(payload, dict) and isinstance(payload.get("message"), str) and payload["message"]:
            payload = {**payload, "message": labeled(payload["message"])}
        return await original(self, path, payload)

    setattr(_post_message, _MARK, True)
    adapter_cls._post_message = _post_message

    fmt = getattr(adapter_cls, "format_message", None)
    if fmt is not None and not getattr(fmt, _MARK, False):
        @functools.wraps(fmt)
        def format_message(self, content):
            return _one_bubble(fmt(self, content))

        setattr(format_message, _MARK, True)
        adapter_cls.format_message = format_message
    return True


def wrap_loaded() -> int:
    """Wrap every BlueBubblesAdapter class already imported, under any module name. The gateway
    loads the bundled platform as ``hermes_plugins.platforms__bluebubbles.adapter``, a different
    class object from ``plugins.platforms.bluebubbles.adapter`` (found live, 2026-11-08)."""
    import sys

    n = 0
    for name, mod in list(sys.modules.items()):
        cls = getattr(mod, "BlueBubblesAdapter", None) if name.endswith("bluebubbles.adapter") else None
        if isinstance(cls, type) and wrap(cls):
            n += 1
    return n


def wrap_registry(registry_cls) -> bool:
    """Wrap ``PlatformRegistry.create_adapter`` so the class of the adapter the gateway actually
    builds for ``bluebubbles`` is labeled before it connects, whatever module it came from."""
    original = registry_cls.create_adapter
    if getattr(original, _MARK, False):
        return True

    @functools.wraps(original)
    def create_adapter(self, name, config):
        adapter = original(self, name, config)
        if adapter is not None and str(name).lower() == "bluebubbles" and not wrap(type(adapter)):
            logger.error("imessage-label: %s has no _post_message; outbound texts are NOT labeled",
                         type(adapter).__name__)
        return adapter

    setattr(create_adapter, _MARK, True)
    registry_cls.create_adapter = create_adapter
    return True


def register(ctx) -> None:
    try:
        from gateway.platform_registry import PlatformRegistry
        wrap_registry(PlatformRegistry)
    except Exception as exc:
        logger.warning("imessage-label: platform registry not importable (%s)", exc)
    try:
        import plugins.platforms.bluebubbles.adapter  # noqa: F401  (the path tests and cron use)
    except Exception:
        pass
    wrap_loaded()
