"""The Arcade client, created lazily on first use.

``hermes plugins doctor`` blocks sockets while ``register()`` runs, and the API key depends on the
active profile's secret scope, so nothing here runs at import or registration time. The key is read
with ``agent.secret_scope.get_secret`` (catalog rule 11): a routed child reads its own profile's key.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any, Optional

KEY_NAME = "ARCADE_API_KEY"
BASE_URL_NAME = "ARCADE_BASE_URL"

_clients: dict[str, Any] = {}
_lock = threading.Lock()


class ArcadeUnavailable(RuntimeError):
    """Arcade cannot be called from this context. The message is safe to show the model."""


def _secret(name: str) -> Optional[str]:
    try:
        from agent.secret_scope import get_secret
    except ImportError:  # outside Hermes (tests): fall back to the process environment
        import os

        return os.environ.get(name) or None
    try:
        value = get_secret(name)
    except Exception as exc:  # UnscopedSecretError under multiplexing: fail closed, say why
        raise ArcadeUnavailable(f"cannot read {name} in this context: {exc}") from exc
    return value or None


def key_present() -> bool:
    """True when ARCADE_API_KEY resolves for the active profile. Never returns the value."""
    try:
        return _secret(KEY_NAME) is not None
    except ArcadeUnavailable:
        return False


def get_client():
    """An ``arcadepy.Arcade`` for the active profile's key, cached per key fingerprint."""
    key = _secret(KEY_NAME)
    if not key:
        raise ArcadeUnavailable(
            f"{KEY_NAME} is not set for this profile. Put it in the profile's .env "
            "(`hermes config env-path`) and start a new session. Every role profile needs it.")
    base_url = _secret(BASE_URL_NAME)
    fingerprint = hashlib.sha256(f"{key}|{base_url or ''}".encode("utf-8")).hexdigest()[:12]
    with _lock:
        client = _clients.get(fingerprint)
        if client is None:
            try:
                from arcadepy import Arcade
            except ImportError as exc:
                raise ArcadeUnavailable("the arcadepy package is not installed; run `hermes plugins validate <plugin> --install-deps`") from exc
            kwargs: dict[str, Any] = {"api_key": key, "max_retries": 1, "timeout": 60.0}
            if base_url:
                kwargs["base_url"] = base_url
            client = Arcade(**kwargs)
            _clients[fingerprint] = client
    return client


def reset_clients() -> None:
    with _lock:
        _clients.clear()


def describe_error(exc: BaseException) -> dict[str, Any]:
    """A clean, model-safe description of an arcadepy failure (never the key, never a stack trace)."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if name == "AuthenticationError":
        return {"error": "Arcade rejected the API key (401). Check ARCADE_API_KEY for this profile.", "status_code": status, "can_retry": False}
    if name == "PermissionDeniedError":
        return {"error": "Arcade refused this request (403) for this API key.", "status_code": status, "can_retry": False}
    if name == "RateLimitError":
        return {"error": "Arcade rate limit hit (429) after one retry. Wait and try again.", "status_code": status, "can_retry": True}
    if name in ("InternalServerError",) or (isinstance(status, int) and status >= 500):
        return {"error": f"Arcade returned a server error ({status}) after one retry.", "status_code": status, "can_retry": True}
    if name in ("APIConnectionError", "APITimeoutError"):
        return {"error": f"could not reach Arcade: {name}", "can_retry": True}
    text = str(exc)
    return {"error": f"{name}: {text[:300]}", "status_code": status, "can_retry": False}
