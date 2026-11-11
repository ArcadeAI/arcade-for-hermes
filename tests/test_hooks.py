"""Offline tests for the governor: pre_tool_call directives, approval capture, receipts. No Hermes runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arcade_for_hermes import hooks as hooks_mod
from arcade_for_hermes.hooks import NEEDS_HUMAN, Governor
from arcade_for_hermes.identity import RoleContext
from arcade_for_hermes.policy import Policy
from arcade_for_hermes.runtime import Runtime

BOWSER = Path(__file__).resolve().parents[1] / "examples" / "bowser" / "policy.yaml"


class Role:
    """Mutable stand-in for the running profile."""

    def __init__(self, role="cos"):
        self.role = role


@pytest.fixture
def world(tmp_path, monkeypatch):
    who = Role()
    cron = {"on": False}
    runtime = Runtime(policy_path=str(BOWSER), receipts_path=str(tmp_path / "receipts.jsonl"), cron_check=lambda: cron["on"])
    policy = runtime.policies.get()

    def fake_resolve(_policy):
        if who.role is None:
            return RoleContext("mystery", None, None, "/tmp/h", "profile 'mystery' is not mapped to a role in the policy (profile_roles); failing closed")
        return RoleContext(who.role, who.role, policy.principal(who.role), "/tmp/h")

    monkeypatch.setattr(hooks_mod, "resolve_role", fake_resolve)
    return runtime, Governor(runtime), who, cron


def _receipts(runtime):
    return runtime.receipts.read()


def test_unrelated_tools_are_ignored(world):
    runtime, gov, who, _ = world
    assert gov.pre_tool_call(tool_name="terminal", args={"command": "ls"}) is None
    gov.post_tool_call(tool_name="terminal", args={"command": "ls"}, result='{"ok": true}')
    assert _receipts(runtime) == []


def test_look_is_allowed_and_receipted(world):
    runtime, gov, who, _ = world
    who.role = "cio"
    args = {"tool": "Github.ListIssues", "input": {"owner": "bowser", "repo": "capital"}, "work_order": "BC-2026-001"}
    assert gov.pre_tool_call(tool_name="arcade_execute", args=args, task_id="t1") is None
    gov.post_tool_call(tool_name="arcade_execute", args=args, task_id="t1",
                       result=json.dumps({"ok": True, "value": {"issues": [{"html_url": "https://github.com/bowser/capital/issues/1"}]}}))
    (r,) = _receipts(runtime)
    assert r["decision"] == "allowed" and r["verb"] == "look" and r["role"] == "cio"
    assert r["principal"] == "bowser/cio" and r["work_order"] == "BC-2026-001"
    assert r["url"] == "https://github.com/bowser/capital/issues/1" and r["outcome"] == "ok"


def test_denied_call_is_blocked_with_reason_and_receipted(world):
    runtime, gov, who, _ = world
    who.role = "skeptic"
    args = {"tool": "GoogleDocs.InsertTextAtEndOfDocument", "input": {"document_id": "thesis"}, "work_order": "BC-2026-001"}
    directive = gov.pre_tool_call(tool_name="arcade_execute", args=args)
    assert directive["action"] == "block"
    assert "DENIED" in directive["message"] and "skeptics comment" in directive["message"]
    gov.post_tool_call(tool_name="arcade_execute", args=args, result='{"error": "blocked"}', status="blocked",
                       error_message=directive["message"])
    (r,) = _receipts(runtime)
    assert r["decision"] == "denied" and r["outcome"] == "not_run" and "skeptics comment" in r["reason"]


def test_ship_escalates_with_per_action_rule_key(world):
    runtime, gov, who, _ = world
    who.role = "reporter"
    args = {"tool": "Github.UpdateIssue", "input": {"owner": "bowser", "repo": "capital", "issue_number": 7, "state": "closed"},
            "work_order": "BC-2026-001"}
    directive = gov.pre_tool_call(tool_name="arcade_execute", args=args)
    assert directive["action"] == "approve"
    expected = Policy.action_key("reporter", "Github.UpdateIssue", args["input"], "BC-2026-001")
    assert directive["rule_key"] == expected
    assert "SHIP" in directive["message"] and "reporter" in directive["message"] and "BC-2026-001" in directive["message"]
    # a different issue number is a different key, so an "always" answer cannot cover it
    other = dict(args, input=dict(args["input"], issue_number=8))
    assert gov.pre_tool_call(tool_name="arcade_execute", args=other)["rule_key"] != expected


def test_approved_ship_records_the_approver(world):
    runtime, gov, who, _ = world
    who.role = "cos"
    args = {"tool": "koopa_execute_not_arcade"}  # placeholder, replaced below
    args = {"proposal_id": "PR-002", "hash": "abc", "work_order": "BC-2026-001"}
    directive = gov.pre_tool_call(tool_name="koopa_execute", args=args)
    assert directive["action"] == "approve"
    key = directive["rule_key"]
    gov.post_approval_response(pattern_key=f"plugin_rule:{key}", choice="once", surface="gateway", session_key="telegram:1")
    assert gov.consume_ticket(key) is True  # the handler consumes the ticket exactly once
    assert gov.consume_ticket(key) is False
    gov.post_tool_call(tool_name="koopa_execute", args=args, result=json.dumps({"order_id": "ORD-1", "fill": {"label": "MOCK"}}))
    (r,) = _receipts(runtime)
    assert r["decision"] == "approved" and r["verb"] == "ship" and r["toolkit"] == "koopa"
    assert r["approver"] == {"choice": "once", "surface": "gateway", "session_key": "telegram:1", "decided_by": "human"}


def test_denied_at_the_gate_records_the_denial(world):
    runtime, gov, who, _ = world
    who.role = "cos"
    args = {"proposal_id": "PR-002", "hash": "abc", "work_order": "BC-2026-001"}
    directive = gov.pre_tool_call(tool_name="koopa_execute", args=args)
    key = directive["rule_key"]
    gov.post_approval_response(pattern_key=f"plugin_rule:{key}", choice="deny", surface="cli", session_key="s")
    gov.post_tool_call(tool_name="koopa_execute", args=args, result='{"error": "BLOCKED"}', status="blocked",
                       error_message="BLOCKED: plugin approval required for koopa_execute")
    (r,) = _receipts(runtime)
    assert r["decision"] == "denied" and r["approver"]["choice"] == "deny" and r["outcome"] == "not_run"
    assert gov.consume_ticket(key) is False  # a denied action leaves no usable ticket


def test_timeout_at_the_gate_is_a_denial(world):
    runtime, gov, who, _ = world
    args = {"proposal_id": "PR-002", "hash": "abc"}
    key = gov.pre_tool_call(tool_name="koopa_execute", args=args)["rule_key"]
    gov.post_approval_response(pattern_key=f"plugin_rule:{key}", choice="timeout", surface="gateway", session_key="s")
    gov.post_tool_call(tool_name="koopa_execute", args=args, result="{}", status="blocked", error_message="timed out")
    (r,) = _receipts(runtime)
    assert r["decision"] == "denied" and r["approver"]["choice"] == "timeout"


def test_no_human_present_is_needs_human(world):
    runtime, gov, who, _ = world
    args = {"proposal_id": "PR-002", "hash": "abc"}
    gov.pre_tool_call(tool_name="koopa_execute", args=args)
    gov.post_tool_call(tool_name="koopa_execute", args=args, result="{}", status="blocked",
                       error_message="BLOCKED: Tool 'koopa_execute' requires approval but no interactive user or gateway is present to approve it.")
    (r,) = _receipts(runtime)
    assert r["decision"] == NEEDS_HUMAN


def test_cron_blocks_ship_before_the_gate(world):
    runtime, gov, who, cron = world
    cron["on"] = True
    args = {"proposal_id": "PR-002", "hash": "abc"}
    directive = gov.pre_tool_call(tool_name="koopa_execute", args=args)
    assert directive["action"] == "block" and directive["message"].startswith(NEEDS_HUMAN)
    look = gov.pre_tool_call(tool_name="koopa_report", args={})
    assert look is None  # look still runs under cron


def test_unknown_profile_fails_closed(world):
    runtime, gov, who, _ = world
    who.role = None
    directive = gov.pre_tool_call(tool_name="arcade_execute", args={"tool": "Github.ListIssues", "input": {}})
    assert directive["action"] == "block" and "failing closed" in directive["message"]


def test_empty_tool_name_is_blocked(world):
    runtime, gov, who, _ = world
    directive = gov.pre_tool_call(tool_name="arcade_execute", args={"tool": "", "input": {}})
    assert directive["action"] == "block"


def test_broken_policy_blocks_arcade_but_not_other_tools(tmp_path, monkeypatch):
    bad = tmp_path / "policy.yaml"
    bad.write_text("default: allow\n")
    runtime = Runtime(policy_path=str(bad), receipts_path=str(tmp_path / "r.jsonl"))
    gov = Governor(runtime)
    assert gov.pre_tool_call(tool_name="terminal", args={"command": "ls"}) is None
    directive = gov.pre_tool_call(tool_name="arcade_execute", args={"tool": "Github.ListIssues", "input": {}})
    assert directive["action"] == "block" and "policy unavailable" in directive["message"]


def test_receipt_input_is_summarized_and_redacted(world):
    runtime, gov, who, _ = world
    who.role = "cio"
    args = {"tool": "GoogleDocs.CreateDocumentFromText", "input": {"title": "Thesis", "text_content": "x" * 1000, "token": "s3cr3t"}}
    gov.pre_tool_call(tool_name="arcade_execute", args=args)
    gov.post_tool_call(tool_name="arcade_execute", args=args, result='{"ok": true}')
    (r,) = _receipts(runtime)
    assert r["input"]["token"] == "[redacted]" and len(r["input"]["text_content"]) < 100


def test_timeout_is_not_recorded_as_a_human_decision(world):
    runtime, gov, who, _ = world
    who.role = "reporter"
    args = {"tool": "Github.UpdateIssue", "input": {"owner": "o", "repo": "r", "issue_number": 1, "state": "closed"}}
    d = gov.pre_tool_call(tool_name="arcade_execute", args=args)
    gov.post_approval_response(pattern_key="plugin_rule:" + d["rule_key"], choice="timeout", surface="gateway",
                               decided_by="human")
    gov.post_tool_call(tool_name="arcade_execute", args=args, status="blocked", error_message="timed out")
    row = runtime.receipts.read()[0]
    assert row["decision"] == "denied" and row["approver"]["decided_by"] == "nobody"


def test_a_ship_action_waits_at_the_founders_door_until_it_resolves(world):
    """The dashboard floor reads waiting.json to show who is waiting on the founder's phone."""
    runtime, gov, who, _ = world
    who.role = "cos"
    args = {"proposal_id": "PR-009", "hash": "abc", "work_order": "BC-2026-009"}
    directive = gov.pre_tool_call(tool_name="koopa_execute", args=args)
    (w,) = runtime.waiting.read()
    assert w["key"] == directive["rule_key"] and w["role"] == "cos" and w["tool"] == "koopa_execute"
    assert w["work_order"] == "BC-2026-009" and w["input"] == {"proposal_id": "PR-009", "hash": "abc", "work_order": "BC-2026-009"}
    gov.post_approval_response(pattern_key=f"plugin_rule:{directive['rule_key']}", choice="deny", surface="gateway")
    gov.post_tool_call(tool_name="koopa_execute", args=args, result='{"error": "BLOCKED"}', status="blocked")
    assert runtime.waiting.read() == []


def test_a_look_never_waits(world):
    runtime, gov, who, _ = world
    who.role = "cio"
    gov.pre_tool_call(tool_name="arcade_execute", args={"tool": "Github.ListIssues", "input": {}, "work_order": "W"})
    assert runtime.waiting.read() == []


def test_the_floor_sees_thinking_spoken_intent_and_local_tools_but_no_receipt(world):
    """activity.jsonl drives the thought clouds and the toolbox; it is a view, never a receipt."""
    from arcade_for_hermes.activity import read_activity
    runtime, gov, who, _ = world
    who.role = "cio"
    gov.on_api_start(task_id="t", model="m")
    gov.on_api_end(task_id="t")
    gov.on_interim_message(text="Pulling the desk price first. Then I size it, see https://x.example/doc?id=1 and mail ops@example.com")
    assert gov.pre_tool_call(tool_name="arcade_whoami", args={}) is None
    acts = read_activity(runtime.activity.path)
    assert [a["kind"] for a in acts] == ["think", "think_end", "say", "tool"]
    assert {a["role"] for a in acts} == {"cio"} and acts[3]["tool"] == "arcade_whoami"
    assert acts[2]["text"] == "Pulling the desk price first."
    assert _receipts(runtime) == []
    assert [a["n"] for a in read_activity(runtime.activity.path, after=acts[1]["n"])] == [acts[2]["n"], acts[3]["n"]]


def test_a_broken_activity_feed_never_breaks_a_call(world, monkeypatch):
    runtime, gov, who, _ = world
    monkeypatch.setattr(type(runtime), "activity", property(lambda self: (_ for _ in ()).throw(OSError("disk full"))))
    gov.on_api_start()
    gov.on_interim_message(text="hi")
    assert gov.pre_tool_call(tool_name="terminal", args={"command": "ls"}) is None
