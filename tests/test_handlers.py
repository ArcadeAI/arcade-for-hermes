"""Offline tests for the tool handlers with a fake Arcade client. No network, no keys."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from arcade_for_hermes import hooks as hooks_mod
from arcade_for_hermes import handlers as tools_mod
from arcade_for_hermes.hooks import Governor
from arcade_for_hermes.identity import RoleContext
from arcade_for_hermes.policy import Policy
from arcade_for_hermes.runtime import Runtime
from arcade_for_hermes.handlers import Handlers

BOWSER = Path(__file__).resolve().parents[1] / "examples" / "bowser" / "policy.yaml"


class FakeTools:
    def __init__(self):
        self.calls = []
        self.auth_status = "completed"
        self.execute_auth = None

    def execute(self, *, tool_name, input, user_id):
        self.calls.append(("execute", tool_name, input, user_id))
        if self.execute_auth:
            return SimpleNamespace(success=False, status="pending", execution_id="e1",
                                   output=SimpleNamespace(authorization=self.execute_auth, error=None, value=None))
        return SimpleNamespace(success=True, status="success", execution_id="e1",
                               output=SimpleNamespace(authorization=None, error=None,
                                                      value={"html_url": "https://github.com/bowser/capital/issues/1", "number": 1}))

    def authorize(self, *, tool_name, user_id):
        self.calls.append(("authorize", tool_name, user_id))
        return SimpleNamespace(status=self.auth_status, url=None if self.auth_status == "completed" else "https://accounts.example/consent",
                               id="auth1", provider_id="github", scopes=["repo"])

    def list(self, *, toolkit, limit):
        self.calls.append(("list", toolkit, limit))
        names = {"github": ["Github.ListIssues", "Github.CreateIssue", "Github.UpdateIssue", "Github.DeleteRepository"],
                 "googledocs": ["GoogleDocs.GetDocumentById", "GoogleDocs.EditDocument"]}
        return [SimpleNamespace(qualified_name=n, description=f"{n} does things\nmore") for n in names.get(toolkit, [])]


@pytest.fixture
def world(tmp_path, monkeypatch):
    runtime = Runtime(policy_path=str(BOWSER), receipts_path=str(tmp_path / "r.jsonl"))
    policy = runtime.policies.get()
    who = {"role": "cos"}
    fake = SimpleNamespace(tools=FakeTools())

    def fake_resolve(_policy):
        return RoleContext(who["role"], who["role"], policy.principal(who["role"]), "/tmp/h")

    monkeypatch.setattr(tools_mod, "resolve_role", fake_resolve)
    monkeypatch.setattr(hooks_mod, "resolve_role", fake_resolve)
    monkeypatch.setattr(tools_mod, "get_client", lambda: fake)
    monkeypatch.setattr(tools_mod, "key_present", lambda: True)
    gov = Governor(runtime)
    return runtime, gov, Handlers(runtime, gov), who, fake.tools


def test_execute_denied_never_calls_arcade(world):
    runtime, gov, h, who, fake = world
    who["role"] = "skeptic"
    out = json.loads(h.execute({"tool": "GoogleDocs.InsertTextAtEndOfDocument", "input": {"document_id": "d"}}))
    assert out["denied"] and "skeptics comment" in out["reason"]
    assert fake.calls == []


def test_execute_look_runs_as_the_role_principal(world):
    runtime, gov, h, who, fake = world
    who["role"] = "cio"
    out = json.loads(h.execute({"tool": "Github.ListIssues", "input": {"owner": "bowser", "repo": "capital"}, "work_order": "BC-2026-001"}))
    assert out["ok"] and out["verb"] == "look" and out["principal"] == "bowser/cio"
    assert out["url"] == "https://github.com/bowser/capital/issues/1"
    assert fake.calls == [("execute", "Github.ListIssues", {"owner": "bowser", "repo": "capital"}, "bowser/cio")]


def test_execute_ship_without_gate_ticket_is_refused(world):
    runtime, gov, h, who, fake = world
    args = {"tool": "Github.UpdateIssue", "input": {"issue_number": 1, "state": "closed"}, "work_order": "BC-2026-001"}
    out = json.loads(h.execute(args))
    assert out["denied"] and "approval gate" in out["reason"]
    assert fake.calls == []


def test_execute_ship_with_gate_ticket_runs_once(world):
    runtime, gov, h, who, fake = world
    args = {"tool": "Github.UpdateIssue", "input": {"issue_number": 1, "state": "closed"}, "work_order": "BC-2026-001"}
    directive = gov.pre_tool_call(tool_name="arcade_execute", args=args)
    assert directive["action"] == "approve"
    out = json.loads(h.execute(args))
    assert out["ok"] and out["verb"] == "ship"
    again = json.loads(h.execute(args))  # the ticket was consumed; a replay without the gate is refused
    assert again["denied"]
    assert len([c for c in fake.calls if c[0] == "execute"]) == 1


def test_execute_surfaces_authorization_required_without_escalating(world):
    runtime, gov, h, who, fake = world
    who["role"] = "cio"
    fake.execute_auth = SimpleNamespace(status="pending", url="https://accounts.example/consent", id="a1", provider_id="google", scopes=None)
    out = json.loads(h.execute({"tool": "GoogleDocs.GetDocumentById", "input": {"document_id": "d"}}))
    assert out["status"] == "authorization_required" and out["url"].startswith("https://")
    assert out["principal"] == "bowser/cio"


class FakeStatusError(Exception):
    """Shape of arcadepy.PermissionDeniedError for an unauthorized execute (observed live, Nov 2026)."""

    def __init__(self):
        super().__init__("authorization required")
        self.status_code = 403
        self.body = {"name": "tool_authorization_required", "message": "authorization required",
                     "authorization": {"url": "https://cloud.arcade.dev/a/abc", "id": "ar_1", "user_id": "bowser/cio",
                                       "provider_id": "arcade-github", "status": "pending"}}


def test_execute_maps_403_tool_authorization_required_to_a_link(world):
    runtime, gov, h, who, fake = world
    who["role"] = "cio"

    def raise_auth(**kwargs):
        raise FakeStatusError()

    fake.execute = raise_auth
    out = json.loads(h.execute({"tool": "Github.ListIssues", "input": {"owner": "bowser", "repo": "capital"}}))
    assert out["status"] == "authorization_required" and out["url"] == "https://cloud.arcade.dev/a/abc"
    assert out["arcade_status"] == "pending" and out["principal"] == "bowser/cio" and "error" not in out


def test_authorize_returns_link_for_the_role_principal(world):
    runtime, gov, h, who, fake = world
    who["role"] = "reporter"
    fake.auth_status = "pending"
    out = json.loads(h.authorize({"toolkit": "google_docs"}))
    assert out["status"] == "pending" and out["url"] and out["principal"] == "bowser/reporter"
    assert fake.calls[-1] == ("authorize", "GoogleDocs.WhoAmI", "bowser/reporter")
    (r,) = runtime.receipts.read()
    assert r["decision"] == "auth_link" and "url" not in r


def test_search_tools_reports_verbs_and_default_deny(world):
    runtime, gov, h, who, fake = world
    who["role"] = "cio"
    out = json.loads(h.search_tools({"query": "issue", "toolkit": "github"}))
    by_name = {t["name"]: t for t in out["tools"]}
    assert by_name["Github.ListIssues"]["verb"] == "look" and by_name["Github.ListIssues"]["allowed_for_role"] is True
    assert by_name["Github.CreateIssue"]["verb"] == "draft" and by_name["Github.CreateIssue"]["allowed_for_role"] is False
    assert by_name["Github.UpdateIssue"]["verb_depends_on_input"] is True
    assert "Github.DeleteRepository" not in by_name  # query filter
    out_all = json.loads(h.search_tools({"toolkit": "github"}))
    assert {t["name"]: t["verb"] for t in out_all["tools"]}["Github.DeleteRepository"] == "denied (no rule)"
    assert not any(c[0] == "execute" for c in fake.calls)


def test_whoami_shows_grants(world):
    runtime, gov, h, who, fake = world
    who["role"] = "skeptic"
    out = json.loads(h.whoami({}))
    assert out["role"] == "skeptic" and out["principal"] == "bowser/skeptic"
    assert out["grants"]["github"] == ["look", "draft"] and out["api_key_present"] is True


def test_authorization_required_names_the_tool_to_authorize(world):
    runtime, gov, handlers, who, tools = world
    who["role"] = "cio"
    tools.execute_auth = SimpleNamespace(id="a1", status="pending", url="https://consent/x", provider_id="google",
                                         scopes=["drive"])
    gov.issue_ticket(Policy.action_key("cio", "GoogleDocs.GetDocumentById", {"document_id": "d"}, None))
    out = json.loads(handlers.execute({"tool": "GoogleDocs.GetDocumentById", "input": {"document_id": "d"}}))
    assert out["status"] == "authorization_required"
    assert "tool='GoogleDocs.GetDocumentById'" in out["instructions"]
