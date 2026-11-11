"""Governing Arcade's official gateway: the same policy, cards and receipts for mcp__<server>__Arcade_UseTool.

The argument shape is the one Hermes 0.23.0 handed pre_tool_call live on 2026-11-08 for a gateway added
with `hermes mcp add arcade --url https://api.arcade.dev/mcp/arcade --auth oauth`. Offline: no network."""

from __future__ import annotations

import json

import pytest

from arcade_for_hermes import hooks as hooks_mod
from arcade_for_hermes.hooks import Governor, is_gateway_execute
from arcade_for_hermes.identity import RoleContext
from arcade_for_hermes.policy import PolicyError
from arcade_for_hermes.runtime import Runtime

USE = "mcp__arcade__Arcade_UseTool"


def _call(tool, inputs=None):
    return {"tool_name": tool, "inputs": inputs or {}, "query_id": "q-1"}


@pytest.fixture
def gate(tmp_path, monkeypatch):
    def make(**support):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({
            "version": 1, "default": "deny", "catalog": True,
            "rules": [{"tool": "Stripe.CreateRefund", "verb": "ship", "amount": "amount"}],
            "roles": {"support": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft", "ship"]},
                                             {"toolkit": "stripe", "verbs": ["look"]}], **support}},
            "toolkits": {"gmail": ["Gmail"], "stripe": ["Stripe"]}}))
        runtime = Runtime(policy_path=str(path), receipts_path=str(tmp_path / "receipts.jsonl"), cron_check=lambda: False)
        policy = runtime.policies.get()
        monkeypatch.setattr(hooks_mod, "resolve_role",
                            lambda _p: RoleContext("p", "support", policy.principal("support"), "/tmp/h"))
        return runtime, Governor(runtime)
    return make


@pytest.mark.parametrize("name,yes", [
    (USE, True), ("mcp__arcade__Arcade_UseToolWithUI", True), ("mcp__team_arcade__Arcade_UseTool", True),
    ("mcp__arcade__Arcade_ListApps", False), ("mcp__arcade__Arcade_SelectTools", False),
    ("Arcade_UseTool", False), ("mcp____Arcade_UseTool", False), ("arcade_execute", False),
])
def test_gateway_execute_is_recognized_under_any_server_name(name, yes):
    assert is_gateway_execute(name) is yes


def test_a_look_through_the_gateway_runs_and_is_receipted(gate):
    runtime, gov = gate()
    args = _call("Gmail.ListEmails", {"n_emails": 3})
    assert gov.pre_tool_call(tool_name=USE, args=args) is None
    gov.post_tool_call(tool_name=USE, args=args, result=json.dumps({"ok": True}))
    (r,) = runtime.receipts.read()
    assert r["tool"] == "Gmail.ListEmails" and r["hermes_tool"] == USE
    assert r["decision"] == "allowed" and r["verb"] == "look" and r["role"] == "support"


def test_a_ship_through_the_gateway_raises_the_founders_card(gate):
    _, gov = gate()
    out = gov.pre_tool_call(tool_name=USE, args=_call("Gmail.SendEmail", {"recipient": "a@b.co", "body": "hi"}))
    assert out["action"] == "approve" and "Gmail.SendEmail" in out["message"]
    assert out["rule_key"]                     # per-action, so "always" never covers every UseTool call


def test_the_gateway_cannot_reach_past_a_roles_grants(gate):
    runtime, gov = gate()
    refund = _call("Stripe.CreateRefund", {"payment_intent": "pi_1", "amount": 500})
    out = gov.pre_tool_call(tool_name=USE, args=refund)
    assert out["action"] == "block" and out["message"].startswith("DENIED")
    out = gov.pre_tool_call(tool_name=USE, args=_call("Slack.SendMessage"))
    assert out["action"] == "block"
    gov.post_tool_call(tool_name=USE, args=refund, status="blocked", error_message=out["message"])
    assert runtime.receipts.read()[-1]["decision"] == "denied"


def test_a_mandate_ships_through_the_gateway_without_a_card_inside_its_limits(gate):
    _, gov = gate(approval="mandate", limits={"per_call": 2000})
    assert gov.pre_tool_call(tool_name=USE, args=_call("Gmail.SendEmail", {"recipient": "a@b.co"})) is None


def test_a_gateway_call_without_a_tool_name_is_denied(gate):
    _, gov = gate()
    out = gov.pre_tool_call(tool_name=USE, args={"inputs": {}, "query_id": "q"})
    assert out["action"] == "block" and "tool_name" in out["message"]


def test_discovery_tools_pass_through(gate):
    _, gov = gate()
    assert gov.pre_tool_call(tool_name="mcp__arcade__Arcade_SelectTools", args={"tasks": ["send an email"]}) is None


def test_a_broken_policy_fails_gateway_calls_closed(gate, monkeypatch):
    runtime, gov = gate()
    monkeypatch.setattr(runtime.policies, "get", lambda: (_ for _ in ()).throw(PolicyError("bad yaml")))
    assert gov.pre_tool_call(tool_name=USE, args=_call("Gmail.ListEmails"))["action"] == "block"
    assert gov.pre_tool_call(tool_name="mcp__arcade__Arcade_ListApps", args={}) is None


class _Ctx:
    """Records what register() hands Hermes; accepts any other registration."""

    def __init__(self):
        self.tools = {}

    def register_tool(self, name, toolset, **kw):
        self.tools[name] = {"toolset": toolset, **kw}

    def __getattr__(self, _name):
        return lambda *a, **k: None


def test_our_tools_never_share_a_toolset_name_with_the_gateway_server():
    import arcade_for_hermes

    ctx = _Ctx()
    arcade_for_hermes.register(ctx)
    assert ctx.tools and {t["toolset"] for t in ctx.tools.values()} == {"arcade-for-hermes"}
    # the three that need ARCADE_API_KEY hide without it, so a gateway-only setup sees only the gateway
    keyed = {n for n, t in ctx.tools.items() if t.get("check_fn") is not None}
    assert keyed == {"arcade_search_tools", "arcade_authorize", "arcade_execute"}


def test_a_gateway_ship_inside_a_subagent_is_handed_back_naming_the_gateway_tool(gate, monkeypatch):
    runtime, gov = gate()
    policy = runtime.policies.get()
    monkeypatch.setattr(hooks_mod, "resolve_role",
                        lambda _p: RoleContext("p", "support", policy.principal("support"), "/tmp/h", routed=True))
    out = gov.pre_tool_call(tool_name=USE, args=_call("Gmail.SendEmail", {"recipient": "a@b.co", "body": "hi"}))
    assert out["action"] == "block" and out["message"].startswith("HANDOFF")
    assert f"call {USE} with exactly" in out["message"] and "arcade_execute" not in out["message"]
    assert '"tool_name": "Gmail.SendEmail"' in out["message"] and "on_behalf_of" not in out["message"]


def test_the_model_is_told_when_the_founder_approves_and_not_otherwise(gate):
    _, gov = gate()
    args = _call("Gmail.SendEmail", {"recipient": "a@b.co", "body": "hi"})
    card = gov.pre_tool_call(tool_name=USE, args=args)
    gov.post_approval_response(pattern_key="plugin_rule:" + card["rule_key"], choice="once", surface="cli")
    gov.post_tool_call(tool_name=USE, args=args, result=json.dumps({"ok": True}))
    out = gov.transform_tool_result(tool_name=USE, args=args, result='{"ok": true}')
    assert out.startswith('{"ok": true}') and "founder approved" in out and "(once)" in out
    assert gov.transform_tool_result(tool_name=USE, args=args, result='{"ok": true}') is None   # once only
    look = _call("Gmail.ListEmails", {"n_emails": 3})
    assert gov.pre_tool_call(tool_name=USE, args=look) is None
    gov.post_tool_call(tool_name=USE, args=look, result="{}")
    assert gov.transform_tool_result(tool_name=USE, args=look, result="{}") is None


def test_the_model_is_told_when_the_transform_runs_before_post_tool_call(gate):
    # Hermes's agent loop fires transform_tool_result inside dispatch, before its terminal post_tool_call.
    _, gov = gate()
    args = _call("Gmail.SendEmail", {"recipient": "a@b.co", "body": "hi"})
    card = gov.pre_tool_call(tool_name=USE, args=args)
    gov.post_approval_response(pattern_key="plugin_rule:" + card["rule_key"], choice="once", surface="cli")
    out = gov.transform_tool_result(tool_name=USE, args=args, result='{"ok": true}')
    assert out and "founder approved" in out and "(once)" in out
    gov.post_tool_call(tool_name=USE, args=args, result=json.dumps({"ok": True}))
    assert gov.transform_tool_result(tool_name=USE, args=args, result='{"ok": true}') is None   # no second note
    denied = _call("Gmail.SendEmail", {"recipient": "c@d.co", "body": "no"})
    card = gov.pre_tool_call(tool_name=USE, args=denied)
    gov.post_approval_response(pattern_key="plugin_rule:" + card["rule_key"], choice="deny", surface="cli")
    assert gov.transform_tool_result(tool_name=USE, args=denied, result="{}") is None


def test_no_approval_note_when_the_approved_call_fails(gate):
    # The founder approved the card, but the call errored: the model must not be told it ran.
    err = json.dumps({"error": "tool not found, it is not enabled for this gateway"})
    _, gov = gate()
    args = _call("Gmail.SendEmail", {"recipient": "a@b.co", "body": "hi"})
    card = gov.pre_tool_call(tool_name=USE, args=args)
    gov.post_approval_response(pattern_key="plugin_rule:" + card["rule_key"], choice="once", surface="cli")
    assert gov.transform_tool_result(tool_name=USE, args=args, result=err) is None      # transform first
    gov.post_tool_call(tool_name=USE, args=args, result=err)
    assert gov.transform_tool_result(tool_name=USE, args=args, result=err) is None

    _, gov = gate()
    card = gov.pre_tool_call(tool_name=USE, args=args)
    gov.post_approval_response(pattern_key="plugin_rule:" + card["rule_key"], choice="once", surface="cli")
    gov.post_tool_call(tool_name=USE, args=args, result=err)                               # post first
    assert gov.transform_tool_result(tool_name=USE, args=args, result=err) is None
