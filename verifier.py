"""A small custom user verifier for Arcade's consent flow.

When an Arcade project uses "Custom user verifier", every consent link sends the person to the
verifier URL with a ``flow_id``. The verifier decides which ``user_id`` that flow belongs to, calls
``POST /v1/auth/confirm_user`` with the project's API key, and forwards the person to the returned
``next_uri`` where the app's own sign-in continues. Arcade does not say which principal a flow was
started for, so this verifier shows the policy's roles and lets the founder pick the badge they are
consenting for. It binds to localhost by default, runs only while ``/arcade connect`` is active (a
TTL), and keeps a list of what it confirmed.
"""

from __future__ import annotations

import html
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping, Optional
from urllib.parse import parse_qs, quote, urlparse

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8765
DEFAULT_TTL = 15 * 60


class Verifier:
    def __init__(self, client_factory: Callable[[], Any], principals: Mapping[str, str], *, host: str = "127.0.0.1",
                 port: int = DEFAULT_PORT, ttl_seconds: int = DEFAULT_TTL, public_url: str = "") -> None:
        self._client_factory = client_factory
        self.principals = dict(principals)          # role -> Arcade user_id
        self.host, self.port, self.ttl = host, int(port), int(ttl_seconds)
        self._public_url = public_url.rstrip("/") if public_url else ""
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.started_at: Optional[float] = None
        self.confirmations: list[dict[str, Any]] = []
        self.errors: list[str] = []

    # ------------------------------------------------------------------ lifecycle
    @property
    def running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    @property
    def url(self) -> str:
        if self._public_url:
            return self._public_url
        port = self._server.server_address[1] if self._server else self.port
        return f"http://{self.host}:{port}"

    def start(self) -> str:
        with self._lock:
            if self.running:
                return self.url
            verifier = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, fmt, *args):  # quiet
                    logger.debug("verifier: " + fmt, *args)

                def do_GET(self):
                    verifier._handle(self)

            self._server = ThreadingHTTPServer((self.host, self.port), Handler)
            self._server.daemon_threads = True
            self._thread = threading.Thread(target=self._server.serve_forever, name="arcade-verifier", daemon=True)
            self._thread.start()
            self.started_at = time.time()
            threading.Timer(self.ttl, self.stop).start()
            return self.url

    def stop(self) -> None:
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass

    def seconds_left(self) -> int:
        if not self.running or self.started_at is None:
            return 0
        return max(0, int(self.ttl - (time.time() - self.started_at)))

    # ------------------------------------------------------------------ requests
    def _handle(self, req: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(req.path)
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
        flow_id = qs.get("flow_id", "").strip()
        role = qs.get("role", "").strip()
        user_id = qs.get("user_id", "").strip()
        if parsed.path.rstrip("/") == "/confirm" and flow_id and (role or user_id):
            principal = self.principals.get(role) or (user_id if user_id in self.principals.values() else "")
            if not principal:
                return self._page(req, 400, "Unknown role", f"<p>{html.escape(role or user_id)} is not a role in the policy.</p>")
            try:
                resp = self._client_factory().auth.confirm_user(flow_id=flow_id, user_id=principal)
            except Exception as exc:
                self.errors.append(f"{flow_id}: {type(exc).__name__}: {exc}")
                return self._page(req, 502, "Arcade refused the confirmation",
                                  f"<p>{html.escape(type(exc).__name__)}: {html.escape(str(exc)[:300])}</p>")
            self.confirmations.append({"flow_id": flow_id, "user_id": principal, "auth_id": resp.auth_id, "ts": time.time()})
            next_uri = getattr(resp, "next_uri", None)
            if next_uri:
                req.send_response(302)
                req.send_header("Location", next_uri)
                req.end_headers()
                return None
            return self._page(req, 200, "Confirmed", f"<p>Confirmed {html.escape(principal)}. You can close this tab.</p>")
        if flow_id:
            buttons = "".join(
                f'<p><a class="btn" href="/confirm?flow_id={quote(flow_id)}&role={quote(r)}">I am consenting as <b>{html.escape(r)}</b> ({html.escape(p)})</a></p>'
                for r, p in self.principals.items())
            return self._page(req, 200, "Which badge is this for?",
                              "<p>Arcade for Hermes: pick the role whose sign-in you are completing. "
                              "Each role is a separate Arcade principal; your app account is the same for all of them.</p>" + buttons)
        done = "".join(f"<li>{html.escape(c['user_id'])}</li>" for c in self.confirmations) or "<li>none yet</li>"
        return self._page(req, 200, "Arcade for Hermes verifier",
                          f"<p>Running, {self.seconds_left()}s left. Open a consent link from <code>/arcade connect</code>; "
                          f"Arcade will send you back here with a flow id.</p><p>Confirmed so far:</p><ul>{done}</ul>")

    @staticmethod
    def _page(req: BaseHTTPRequestHandler, status: int, title: str, body: str) -> None:
        doc = (f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
               "<style>body{font:16px system-ui;max-width:40em;margin:3em auto;padding:0 1em}"
               ".btn{display:inline-block;padding:.6em 1em;border:1px solid #888;border-radius:6px;text-decoration:none;color:inherit}</style>"
               f"<h1>{html.escape(title)}</h1>{body}").encode("utf-8")
        req.send_response(status)
        req.send_header("Content-Type", "text/html; charset=utf-8")
        req.send_header("Content-Length", str(len(doc)))
        req.end_headers()
        req.wfile.write(doc)
