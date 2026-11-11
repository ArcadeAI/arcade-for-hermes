"""The starter kit: a verb for every Arcade tool, the dial from yolo to strict, and founding a company.
Offline: the catalog is the committed snapshot; no network, no keys, no Hermes runtime."""

from __future__ import annotations

import json
import os
import stat

import pytest

from arcade_for_hermes import company as co
from arcade_for_hermes import found as fd
from arcade_for_hermes import hooks as hooks_mod
from arcade_for_hermes import verbs
from arcade_for_hermes.hooks import Governor
from arcade_for_hermes.identity import RoleContext
from arcade_for_hermes.policy import Policy, PolicyError, load_yaml
from arcade_for_hermes.runtime import Runtime

CATALOG = co.load_catalog()


# ----------------------------------------------------------------------------- verbs
@pytest.mark.parametrize("tool,verb", [
    ("Gmail.ListEmails", "look"), ("Gmail.SendEmail", "ship"), ("Stripe.CreateRefund", "ship"),
    ("Stripe.CreatePaymentLink", "ship"), ("GoogleDocs.CreateDocumentFromText", "draft"), ("X.PostTweet", "ship"),
    ("Linear.CreateIssue", "draft"), ("AsanaApi.AsanaCreateTeam", "draft"), ("Acme.Frobnicate", "ship"),
])
def test_every_tool_gets_a_verb_and_the_unknown_ship(tool, verb):
    assert verbs.classify(tool) == verb


def test_the_stricter_of_metadata_and_name_wins():
    # The name says draft, Arcade says destructive: ship. Arcade says read-only, the name says send: ship.
    assert verbs.classify("Foo.UpdateThing", {"destructive": True}) == "ship"
    assert verbs.classify("Foo.SendThing", {"read_only": True}) == "ship"
    assert verbs.classify("Foo.Thing", {"read_only": True}) == "look"


def test_the_snapshot_covers_the_whole_catalog():
    assert CATALOG["count"] == len(CATALOG["verbs"]) > 8000
    assert set(CATALOG["verbs"].values()) == {"look", "draft", "ship"}


# ----------------------------------------------------------------------------- the engine with the catalog
def _policy(**role):
    return Policy.from_dict({"version": 1, "default": "deny", "catalog": True,
                             "toolkits": {"github": ["Github"]},
                             "rules": [{"tool": "Github.CreateIssueComment", "verb": "ship"}],
                             "roles": {"r": {"grants": [{"toolkit": "*", "verbs": ["look", "draft", "ship"]}], **role},
                                       "gh": {"grants": [{"toolkit": "github", "verbs": ["look", "draft"]}]}}})


def test_any_catalog_tool_is_classified_and_cards_by_default():
    p = _policy()
    send = p.decide("r", "Gmail.SendEmail", {})
    assert send.allowed and send.requires_approval and send.rule == "catalog:ship"
    assert p.decide("r", "Gmail.ListEmails", {}).verb == "look"
    assert not p.decide("r", "Nowhere.DoThing", {}).allowed          # not an Arcade toolkit: default deny


def test_explicit_rules_beat_the_catalog_and_grants_still_bound_a_role():
    p = _policy()
    assert p.decide("r", "Github.CreateIssueComment", {}).verb == "ship"        # the catalog says draft
    assert not p.decide("gh", "Gmail.ListEmails", {}).allowed                   # no grant on gmail
    assert not p.decide("gh", "Github.CreateIssueComment", {}).allowed          # ship, gh only drafts


def test_a_tool_newer_than_the_snapshot_is_classified_by_name():
    d = _policy().decide("r", "Gmail.SendCarrierPigeon", {})
    assert d.rule == "catalog-name:ship" and d.requires_approval


def test_mandate_ships_without_a_card_but_limits_and_halt_still_hold():
    p = Policy.from_dict({"version": 1, "default": "deny", "catalog": True,
                          "rules": [{"tool": "Stripe.CreateRefund", "verb": "ship", "amount": "amount"}],
                          "roles": {"r": {"grants": [{"toolkit": "*", "verbs": ["look", "draft", "ship"]}],
                                          "approval": "mandate", "limits": {"per_call": 2000}}}})
    ok = p.decide("r", "Stripe.CreateRefund", {"amount": 1500})
    assert ok.allowed and ok.mandate and not ok.requires_approval and "mandate" in ok.reason
    assert not p.decide("r", "Stripe.CreateRefund", {"amount": 2500}).allowed
    assert not p.decide("r", "Stripe.CreateRefund", {}).allowed                 # full refund: no readable amount
    assert not p.decide("r", "Gmail.SendEmail", {}, halted="dinner").allowed


def test_approval_must_be_card_or_mandate():
    with pytest.raises(PolicyError):
        Policy.from_dict({"version": 1, "roles": {"r": {"approval": "off"}}})


# ----------------------------------------------------------------------------- the dial
TEMPLATES = sorted(fd.templates())


@pytest.mark.parametrize("name", TEMPLATES)
@pytest.mark.parametrize("setting", co.SETTINGS)
def test_every_template_builds_a_valid_policy_at_every_setting(name, setting):
    spec = load_yaml(fd.templates()[name])
    policy = Policy.from_dict(co.build_policy(spec, setting, CATALOG))
    assert policy.company["setting"] == setting
    assert policy.role_for_profile("default") == spec["lead"]


def test_the_dial_from_yolo_to_strict_on_the_shirt_shop():
    spec = load_yaml(fd.templates()["shirt-shop"])
    at = {s: Policy.from_dict(co.build_policy(spec, s, CATALOG)) for s in co.SETTINGS}
    refund = {"payment_intent": "pi_1", "amount": 1500}
    # yolo: support may refund (under the company default cap), no card
    d = at["yolo"].decide("support", "Stripe.CreateRefund", refund)
    assert d.allowed and not d.requires_approval
    assert not at["yolo"].decide("support", "Stripe.CreateRefund", {"payment_intent": "pi_1", "amount": 9000}).allowed
    # founder: the same refund waits for the card
    assert at["founder"].decide("support", "Stripe.CreateRefund", refund).requires_approval
    # roles: support has Stripe for reading only; the ops lead refunds on a card
    assert not at["roles"].decide("support", "Stripe.CreateRefund", refund).allowed
    assert at["roles"].decide("ops_lead", "Stripe.CreateRefund", refund).requires_approval
    assert not at["roles"].decide("support", "Slack.SendMessage", {}).allowed       # not one of its apps
    # strict: tools are pinned; a tool Arcade adds later is denied until the snapshot is rebuilt
    assert at["strict"].decide("ops_lead", "Stripe.CreateRefund", refund).requires_approval
    assert not at["strict"].decide("ops_lead", "Stripe.CreateSomethingNew", {}).allowed
    assert at["roles"].decide("ops_lead", "Stripe.CreateSomethingNew", {}).allowed   # roles reads it by name


def test_a_spec_with_a_made_up_app_is_refused_with_every_problem_named():
    with pytest.raises(co.SpecError) as err:
        co.normalize({"name": "X", "roles": {"a": {"apps": ["Shopify"], "ships": ["Gmail"]}}}, CATALOG)
    assert "'Shopify' is not an Arcade toolkit" in str(err.value) and "ships" in str(err.value)


def test_cron_schedules_read_like_people_write_them():
    assert fd.cron_schedule("weekdays 08:30") == "30 8 * * 1-5"
    assert fd.cron_schedule("everyday 7:05") == "5 7 * * *"
    assert fd.cron_schedule("every 2h") == "every 2h"


# ----------------------------------------------------------------------------- the gate under a mandate
@pytest.fixture
def gate(tmp_path, monkeypatch):
    def make(approval):
        path = tmp_path / f"policy-{approval}.json"
        path.write_text(json.dumps({"version": 1, "default": "deny", "catalog": True,
                                    "roles": {"r": {"grants": [{"toolkit": "*", "verbs": ["look", "draft", "ship"]}],
                                                    "approval": approval}}}))
        runtime = Runtime(policy_path=str(path), receipts_path=str(tmp_path / f"r-{approval}.jsonl"), cron_check=lambda: True)
        policy = runtime.policies.get()
        monkeypatch.setattr(hooks_mod, "resolve_role", lambda _p: RoleContext("p", "r", policy.principal("r"), "/tmp/h", routed=True))
        return runtime, Governor(runtime)
    return make


def test_a_mandate_ship_runs_from_cron_and_subagents_and_a_card_ship_does_not(gate):
    args = {"tool": "Gmail.SendEmail", "input": {"recipient": "a@b.co", "body": "hi"}}
    runtime, gov = gate("mandate")
    assert gov.pre_tool_call(tool_name="arcade_execute", args=args) is None             # allowed: no card, no handoff
    runtime, gov = gate("card")
    blocked = gov.pre_tool_call(tool_name="arcade_execute", args=args)
    assert blocked["action"] == "block"                                                 # routed child: handed back


# ----------------------------------------------------------------------------- founding
def test_found_dry_run_plans_profiles_tasks_and_schedules(tmp_path):
    plan = fd.found(fd.load_spec("trading-desk"), "roles", home=tmp_path, dry_run=True)
    assert plan["profiles"] == ["bowser-capital-analyst", "bowser-capital-skeptic", "bowser-capital-reporter"]
    assert {"title": "Morning thesis", "profile": "bowser-capital-analyst", "every": "30 8 * * 1-5"} in plan["tasks"]
    assert not (tmp_path / "arcade").exists()


@pytest.fixture
def fake_hermes(tmp_path):
    """A stand-in for the hermes CLI: `profile create NAME` makes the directory, everything else succeeds."""
    script = tmp_path / "hermes"
    script.write_text("#!/bin/sh\nif [ \"$1\" = profile ] && [ \"$2\" = create ]; then mkdir -p \"$HERMES_HOME/profiles/$3\"; fi\n"
                      "echo \"$@\" >> \"$HERMES_HOME/calls.log\"\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_found_writes_the_company_and_the_dial_moves_it(tmp_path, fake_hermes):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("ARCADE_API_KEY=k-test\nUNRELATED=x\n")
    (home / "arcade").mkdir()
    (home / "arcade" / "policy.yaml").write_text("version: 1\nshared_principal: me@example.com\nroles: {}\n")
    plan = fd.found(fd.load_spec("shirt-shop"), "founder", home=home, hermes=fake_hermes)
    assert not plan["problems"], plan["problems"]
    assert (home / "arcade" / "policy.before-company.yaml").exists()
    policy = Policy.load(home / "arcade" / "policy.yaml")
    assert policy.company == {"name": "Loud Tees", "setting": "founder"}
    assert policy.principal("support") == "me@example.com"          # carried over from the old policy
    support = home / "profiles" / "loud-tees-support"
    assert "support agent of Loud Tees" in (support / "SOUL.md").read_text()
    assert (support / ".env").read_text() == "ARCADE_API_KEY=k-test\n"                   # only the keys it needs
    assert (support / "plugins" / "arcade-for-hermes").is_symlink()
    calls = (home / "calls.log").read_text()
    assert "kanban --board loud-tees create Answer the inbox" in calls and "cron create 0 10 * * *" in calls
    fd.set_setting("yolo", home=home)
    assert Policy.load(home / "arcade" / "policy.yaml").roles["support"].approval == "mandate"


def test_an_agent_can_draft_a_company_but_not_start_one(tmp_path):
    spec = {"name": "Dent Books", "lead": "controller",
            "roles": {"controller": {"apps": ["XeroApi", "Gmail"], "ships": ["Gmail"]}, "clerk": {"apps": ["XeroApi"]}},
            "tasks": [{"title": "Reconcile", "role": "clerk"}]}
    out = fd.draft(spec, home=tmp_path)
    assert out["draft"].endswith("drafts/dent-books.yaml") and "/arcade found" in out["next"]
    assert not (tmp_path / "arcade" / "policy.yaml").exists() and not (tmp_path / "profiles").exists()


# ----------------------------------------------------------------------------- the gateway
def test_every_official_template_uses_only_apps_on_arcades_official_gateway():
    for name, path in fd.templates().items():
        spec = co.normalize(load_yaml(path), CATALOG)
        assert co.gateway_warnings(spec) == [], name
    # the trading desk says it brings its own gateway, and it is the one that would warn without that
    desk = co.normalize({**load_yaml(fd.templates()["trading-desk"]), "gateway": "arcade"}, CATALOG)
    assert "ArcadeAlpaca" in co.gateway_warnings(desk)[0]


def test_a_spec_with_an_unknown_gateway_is_refused():
    with pytest.raises(co.SpecError, match="gateway"):
        co.normalize({"name": "X", "roles": {"a": {"apps": ["Gmail"]}}, "gateway": "somewhere"}, CATALOG)


def test_only_arcade_gateways_are_carried_into_role_profiles():
    cfg = {"mcp_servers": {"arcade": {"url": "https://api.arcade.dev/mcp/arcade", "auth": "oauth"},
                           "desk": {"url": "https://api.arcade.dev/mcp/gw_123", "auth": "oauth"},
                           "off": {"url": "https://api.arcade.dev/mcp/x", "enabled": False},
                           "other": {"url": "https://example.com/mcp", "auth": "oauth"},
                           "local": {"command": "npx", "args": ["x"]}}}
    assert set(fd.gateway_servers(cfg)) == {"arcade", "desk"}


def test_found_gives_every_role_the_leads_gateway_and_sign_in(tmp_path, fake_hermes):
    home = tmp_path / "home"
    (home / "mcp-tokens").mkdir(parents=True)
    for f in ("arcade.json", "arcade.client.json", "arcade.meta.json", "arcadeish.json"):
        (home / "mcp-tokens" / f).write_text("{}")
    (home / "config.yaml").write_text("mcp_servers:\n  arcade:\n    url: https://api.arcade.dev/mcp/arcade\n    auth: oauth\n")
    plan = fd.found(fd.load_spec("software-startup"), "founder", home=home, hermes=fake_hermes)
    assert not plan["problems"] and not plan["warnings"]
    eng = home / "profiles" / "kitecat-labs-engineer"
    assert load_yaml(eng / "config.yaml")["mcp_servers"]["arcade"] == {"url": "https://api.arcade.dev/mcp/arcade", "auth": "oauth"}
    linked = sorted(p.name for p in (eng / "mcp-tokens").iterdir())
    assert linked == ["arcade.client.json", "arcade.json", "arcade.meta.json"]          # not arcadeish.json
    assert all((eng / "mcp-tokens" / n).is_symlink() for n in linked)
    # a kanban worker is its own process: it must read the company's policy and write where the Floor reads
    settings = load_yaml(eng / "config.yaml")["plugins"]["entries"]["arcade-for-hermes"]["settings"]
    assert settings["policy_path"] == str(home / "arcade" / "policy.yaml")
    assert settings["receipts_path"] == str(home / "plugin-data" / "arcade-for-hermes" / "receipts.jsonl")


def test_founding_replaces_hermess_stock_soul_but_never_yours(tmp_path, fake_hermes):
    from hermes_cli.default_soul import DEFAULT_SOUL_MD
    stock, mine = tmp_path / "stock", tmp_path / "mine"
    for h, text in ((stock, DEFAULT_SOUL_MD), (mine, "I am the founder's own soul.")):
        h.mkdir()
        (h / "SOUL.md").write_text(text)
        fd.found(fd.load_spec("coo"), "founder", home=h, hermes=fake_hermes)
    assert "COO of Solo COO" in (stock / "SOUL.md").read_text() and (stock / "SOUL.before-company.md").exists()
    assert (mine / "SOUL.md").read_text() == "I am the founder's own soul." and (mine / "arcade" / "lead-SOUL.md").exists()
