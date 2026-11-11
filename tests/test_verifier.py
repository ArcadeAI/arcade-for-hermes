"""The custom user verifier: picks a role for a flow, confirms it with Arcade, forwards to next_uri. No network."""

from __future__ import annotations

import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from arcade_for_hermes.verifier import Verifier


class FakeAuth:
    def __init__(self):
        self.calls = []

    def confirm_user(self, *, flow_id, user_id):
        self.calls.append((flow_id, user_id))
        return SimpleNamespace(auth_id="ar_1", next_uri=f"https://cloud.arcade.dev/continue/{flow_id}")


@pytest.fixture
def verifier():
    auth = FakeAuth()
    client = SimpleNamespace(auth=auth)
    v = Verifier(lambda: client, {"cio": "bowser/cio", "reporter": "bowser/reporter"}, port=0, ttl_seconds=30)
    url = v.start()
    try:
        yield v, url, auth
    finally:
        v.stop()


def _get(url, follow=False):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(url, timeout=5)
        return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def test_status_page_without_flow(verifier):
    v, url, auth = verifier
    status, _, body = _get(url + "/")
    assert status == 200 and "Running" in body and auth.calls == []


def test_flow_page_lists_roles(verifier):
    v, url, auth = verifier
    status, _, body = _get(url + "/?flow_id=f-123")
    assert status == 200 and "bowser/cio" in body and "bowser/reporter" in body
    assert "/confirm?flow_id=f-123&role=cio" in body
    assert auth.calls == []


def test_confirm_calls_arcade_and_redirects(verifier):
    v, url, auth = verifier
    status, headers, _ = _get(url + "/confirm?flow_id=f-123&role=cio")
    assert status == 302 and headers["Location"] == "https://cloud.arcade.dev/continue/f-123"
    assert auth.calls == [("f-123", "bowser/cio")]
    assert v.confirmations[0]["user_id"] == "bowser/cio"


def test_unknown_role_is_refused(verifier):
    v, url, auth = verifier
    status, _, body = _get(url + "/confirm?flow_id=f-1&role=intern")
    assert status == 400 and auth.calls == []


def test_start_is_idempotent_and_stop_ends_it(verifier):
    v, url, auth = verifier
    assert v.start() == url and v.running
    v.stop()
    assert not v.running
