"""Ship actions inside a subagent are handed back; the main session re-issues them with on_behalf_of.

Also: the audit shows outcomes, receipts never store consent links, and a missing YAML parser says so.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arcade_for_hermes import handlers as handlers_mod
from arcade_for_hermes import hooks as hooks_mod
from arcade_for_hermes.acting import HANDOFF
from arcade_for_hermes.commands import Commands
from arcade_for_hermes.handlers import Handlers
from arcade_for_hermes.hooks import Governor
from arcade_for_hermes.identity import RoleContext
from arcade_for_hermes.policy import PolicyError, load_yaml
from arcade_for_hermes.runtime import Runtime

BOWSER = Path(__file__).resolve().parents[1] / "examples" / "bowser" / "policy.yaml"
CLOSE = {"owner": "o", "repo": "r", "issue_number": 1, "state": "closed"}
WO = "BC-2026-001"


class Tools:
    def __init__(self):
        self.calls = []

    def execute(self, *, tool_name, input, user_id):
        self.calls.append((tool_name, user_id))
        return SimpleNamespace(success=True, status="success", execution_id="e1",
                               output=SimpleNamespace(authorization=None, error=None,
                                                      value={"html_url": "https://github.com/o/r/issues/1"}))


@pytest.fixture
def world(tmp_path, monkeypatch):
    runtime = Runtime(policy_path=str(BOWSER), receipts_path=str(tmp_path / "r.jsonl"))
    policy = runtime.policies.get()
    who = {"role": "cos", "routed": False}
    tools = Tools()

    def fake_resolve(_policy):
        return RoleContext(who["role"], who["role"], policy.principal(who["role"]), "/tmp/h", routed=who["routed"])

    for mod in (hooks_mod, handlers_mod):
        monkeypatch.setattr(mod, "resolve_role", fake_resolve)
    monkeypatch.setattr(handlers_mod, "get_client", lambda: SimpleNamespace(tools=tools))
    gov = Governor(runtime)
    return runtime, gov, Handlers(runtime, gov), who, tools


def _call(gov, handlers, args, *, choice=None, run=True):
    """Drive one arcade_execute the way Hermes does: pre hook, optional gate answer, handler, post hook."""
    directive = gov.pre_tool_call(tool_name="arcade_execute", args=args)
    result, status, err = None, None, None
    if directive and directive["action"] == "block":
        status, err = "blocked", directive["message"]
    elif directive and directive["action"] == "approve":
        gov.post_approval_response(pattern_key="plugin_rule:" + directive["rule_key"], choice=choice or "deny",
                                   surface="gateway")
        if choice in (None, "deny"):
            status, err = "blocked", "denied by user"
    if status != "blocked" and run:
        result = handlers.execute(args)
    gov.post_tool_call(tool_name="arcade_execute", args=args, result=result, status=status, error_message=err)
    return directive, (json.loads(result) if result else None)


def test_ship_inside_a_subagent_is_handed_back_and_never_runs(world):
    runtime, gov, handlers, who, tools = world
    who.update(role="reporter", routed=True)
    args = {"tool": "Github.UpdateIssue", "input": CLOSE, "work_order": WO}
    directive, _ = _call(gov, handlers, args)
    assert directive["action"] == "block" and directive["message"].startswith(HANDOFF)
    assert '"on_behalf_of": "reporter"' in directive["message"]
    assert tools.calls == []
    row = runtime.receipts.read()[0]
    assert (row["decision"], row["outcome"], row["role"]) == ("handed_back", "not_run", "reporter")


def test_handler_refuses_a_subagent_ship_even_without_the_hook(world):
    _, _, handlers, who, tools = world
    who.update(role="reporter", routed=True)
    out = json.loads(handlers.execute({"tool": "Github.UpdateIssue", "input": CLOSE, "work_order": WO}))
    assert out["status"] == HANDOFF and out["denied"] and tools.calls == []


def test_look_and_draft_still_run_inside_a_subagent(world):
    _, gov, handlers, who, tools = world
    who.update(role="reporter", routed=True)
    directive, out = _call(gov, handlers, {"tool": "Github.ListIssues", "input": {"owner": "o", "repo": "r"}, "work_order": WO})
    assert directive is None and out["ok"]
    assert tools.calls == [("Github.ListIssues", "bowser/reporter")]


def test_main_session_ships_on_behalf_with_a_card_naming_both_roles(world):
    runtime, gov, handlers, who, tools = world
    args = {"tool": "Github.UpdateIssue", "input": CLOSE, "work_order": WO, "on_behalf_of": "reporter"}
    directive, out = _call(gov, handlers, args, choice="once")
    assert directive["action"] == "approve"
    assert directive["message"].startswith("SHIP: reporter (bowser/reporter) via cos wants Github.UpdateIssue")
    assert out["ok"] and out["via"] == "cos"
    assert tools.calls == [("Github.UpdateIssue", "bowser/reporter")]
    row = runtime.receipts.read()[0]
    assert (row["role"], row["via"], row["decision"], row["approver"]["choice"]) == ("reporter", "cos", "approved", "once")


def test_on_behalf_denied_at_the_card_never_runs(world):
    runtime, gov, handlers, _, tools = world
    args = {"tool": "Github.UpdateIssue", "input": CLOSE, "work_order": WO, "on_behalf_of": "reporter"}
    _call(gov, handlers, args, choice="deny")
    assert tools.calls == []
    assert runtime.receipts.read()[0]["decision"] == "denied"


@pytest.mark.parametrize("args, why", [
    ({"tool": "Github.ListIssues", "input": {"owner": "o", "repo": "r"}, "on_behalf_of": "reporter"}, "only for ship"),
    ({"tool": "Github.UpdateIssue", "input": CLOSE, "on_behalf_of": "intern"}, "not a role"),
    ({"tool": "GoogleDocs.InsertTextAtEndOfDocument", "input": {"document_id": "x", "text_content": "y"},
      "on_behalf_of": "skeptic"}, "skeptic"),
])
def test_on_behalf_never_widens_a_grant(world, args, why):
    _, gov, handlers, _, tools = world
    directive, _ = _call(gov, handlers, args)
    assert directive["action"] == "block" and why in directive["message"]
    assert tools.calls == []


def test_on_behalf_is_refused_inside_a_subagent(world):
    _, gov, handlers, who, tools = world
    who.update(role="cio", routed=True)
    directive, _ = _call(gov, handlers, {"tool": "Github.UpdateIssue", "input": CLOSE, "on_behalf_of": "reporter"})
    assert directive["action"] == "block" and "main session" in directive["message"]
    assert tools.calls == []


def test_receipts_never_store_a_consent_link(world):
    runtime, gov, _, who, _ = world
    who.update(role="cio")
    args = {"tool": "GoogleDocs.CreateDocumentFromText", "input": {"title": "t", "text_content": "x"}, "work_order": WO}
    gov.pre_tool_call(tool_name="arcade_execute", args=args)
    consent = json.dumps({"status": "authorization_required", "url": "https://cloud.arcade.dev/a/secret"})
    gov.post_tool_call(tool_name="arcade_execute", args=args, result=consent)
    row = runtime.receipts.read()[0]
    assert row["outcome"] == "authorization_required" and not row.get("url")
    assert "cloud.arcade.dev" not in runtime.receipts_path.read_text()


def test_audit_shows_outcome_and_via(world):
    runtime, gov, handlers, _, _ = world
    _call(gov, handlers, {"tool": "Github.UpdateIssue", "input": CLOSE, "work_order": WO, "on_behalf_of": "reporter"}, choice="once")
    out = Commands(runtime).audit(WO)
    assert "| outcome |" in out.splitlines()[1]
    assert "reporter via cos | ship | Github.UpdateIssue | approved | ok | once@gateway" in out


def test_missing_yaml_parser_says_so(tmp_path, monkeypatch):
    for name in ("ruamel", "ruamel.yaml", "yaml"):
        monkeypatch.setitem(sys.modules, name, None)
    p = tmp_path / "p.yaml"
    p.write_text("version: 1\n")
    with pytest.raises(ValueError, match="no YAML parser found"):
        load_yaml(p)


def test_audit_names_the_swarm_profile_behind_a_shared_role(world, monkeypatch):
    runtime, gov, handlers, _, _ = world
    policy = runtime.policies.get()
    monkeypatch.setattr(hooks_mod, "resolve_role", lambda _p: RoleContext(
        "analyst-sol", "analyst", policy.principal("analyst"), "/tmp/h", routed=True))
    monkeypatch.setattr(handlers_mod, "resolve_role", lambda _p: RoleContext(
        "analyst-sol", "analyst", policy.principal("analyst"), "/tmp/h", routed=True))
    _call(gov, handlers, {"tool": "Github.ListIssues", "input": {"owner": "o", "repo": "r"}, "work_order": WO})
    assert "| analyst (analyst-sol) | look | Github.ListIssues |" in Commands(runtime).audit(WO)
