"""Offline tests for the look/draft/ship policy engine. No network, no keys, no Hermes runtime."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest



from arcade_for_hermes.policy import Policy, PolicyError

BOWSER = Path(__file__).resolve().parents[1] / "examples" / "bowser" / "policy.yaml"


@pytest.fixture
def policy() -> Policy:
    return Policy.load(BOWSER)


def test_bowser_policy_loads_its_roles(policy):
    assert set(policy.roles) == {"cos", "cio", "skeptic", "reporter", "analyst", "risk", "red", "blue", "red_crew", "blue_crew",
                                 "quant_data", "quant_research", "quant_dev", "quant_pm", "quant_risk", "quant_exec",
                                 "quant_compliance", "quant_ir"}
    assert policy.principal("cio") == "bowser/cio"
    assert policy.role_for_profile("default") == "cos"
    assert policy.role_for_profile("cio") == "cio"
    assert policy.role_for_profile("nobody") is None


def test_the_swarm_maps_many_profiles_onto_few_roles(policy):
    analysts = [f"analyst-{i:03d}" for i in range(1, 85)]
    assert {policy.role_for_profile(p) for p in analysts} == {"analyst"}
    assert policy.role_for_profile("skeptic-12") == "skeptic"
    assert policy.role_for_profile("skeptic") == "skeptic" and policy.role_for_profile("cio") == "cio"
    assert policy.role_for_profile("intern-1") is None and policy.role_for_profile("analyst") == "analyst"
    # Same role, same grants: every analyst may propose, none may execute or close.
    for p in analysts:
        role = policy.role_for_profile(p)
        assert policy.decide(role, "koopa_propose", {}, "BC-2026-001").allowed
        assert not policy.decide(role, "koopa_execute", {}, "BC-2026-001").allowed
        assert not policy.decide(role, "Github.UpdateIssue", {"state": "closed"}, "BC-2026-001").allowed
    assert not policy.decide("risk", "koopa_propose", {}, "BC-2026-001").allowed
    assert policy.decide("risk", "Github.CreateIssueComment", {}, "BC-2026-001").allowed


def test_toolkit_resolution_uses_aliases(policy):
    assert policy.toolkit_of("Github.ListIssues") == "github"
    assert policy.toolkit_of("GitHub.CreateIssue") == "github"
    assert policy.toolkit_of("GoogleDocs.GetDocumentById") == "google_docs"
    assert policy.toolkit_of("koopa_execute") == "koopa"
    assert policy.toolkit_of("Mystery.Tool") is None


def test_look_is_allowed_with_a_receipt_and_no_approval(policy):
    d = policy.decide("cio", "Github.ListIssues", {"owner": "bowser", "repo": "capital"})
    assert d.allowed and d.verb == "look" and d.requires_approval is False
    assert d.toolkit == "github"


def test_unknown_tool_is_denied_by_default(policy):
    d = policy.decide("cio", "Github.SomethingNew", {})
    assert not d.allowed
    assert "no rule" in d.reason


def test_unknown_role_is_denied(policy):
    d = policy.decide("intern", "Github.ListIssues", {})
    assert not d.allowed and "role" in d.reason


def test_skeptic_can_comment_but_not_rewrite_the_thesis(policy):
    ok = policy.decide("skeptic", "Github.CreateIssueComment", {"owner": "bowser", "repo": "capital", "issue_number": 1})
    assert ok.allowed and ok.verb == "draft"
    denied = policy.decide("skeptic", "GoogleDocs.InsertTextAtEndOfDocument", {"document_id": "abc"})
    assert not denied.allowed
    assert "skeptic" in denied.reason and "draft" in denied.reason and "google_docs" in denied.reason


def test_input_matching_turns_a_general_update_into_ship(policy):
    # The same Arcade tool is draft when it edits and ship when it closes.
    edit = policy.decide("cos", "Github.UpdateIssue", {"owner": "bowser", "repo": "capital", "issue_number": 1, "title": "x"})
    assert edit.allowed and edit.verb == "draft"
    close = policy.decide("cos", "Github.UpdateIssue", {"owner": "bowser", "repo": "capital", "issue_number": 1, "state": "closed"})
    assert close.allowed and close.verb == "ship" and close.requires_approval


def test_cio_has_no_ship_grant_so_closing_is_denied(policy):
    close = policy.decide("cio", "Github.UpdateIssue", {"issue_number": 1, "state": "closed"})
    assert not close.allowed and "ship" in close.reason


def test_reporter_ship_requires_approval(policy):
    close = policy.decide("reporter", "Github.UpdateIssue", {"issue_number": 1, "state": "closed"})
    assert close.allowed and close.verb == "ship" and close.requires_approval


def test_koopa_tools_are_governed_local_tools(policy):
    assert policy.governs("koopa_execute")
    assert policy.governs("koopa_propose")
    assert not policy.governs("terminal")
    assert not policy.governs("arcade_execute")  # arcade_execute is governed by its `tool` argument instead
    d = policy.decide("cos", "koopa_execute", {"proposal_id": "PR-002", "hash": "deadbeef"})
    assert d.allowed and d.verb == "ship" and d.requires_approval
    cio = policy.decide("cio", "koopa_execute", {"proposal_id": "PR-002", "hash": "deadbeef"})
    assert not cio.allowed
    prop = policy.decide("cio", "koopa_propose", {"symbol": "VTI", "notional_usd": 4000})
    assert prop.allowed and prop.verb == "draft"
    rep = policy.decide("skeptic", "koopa_report", {})
    assert rep.allowed and rep.verb == "look"


def test_ownership_is_enforced_only_when_a_grant_declares_owns():
    p = Policy.from_dict({
        "version": 1,
        "principal_prefix": "t",
        "toolkits": {"google_docs": ["GoogleDocs"]},
        "rules": [
            {"tool": "GoogleDocs.InsertTextAtEndOfDocument", "verb": "draft"},
        ],
        "roles": {
            "cio": {"grants": [{"toolkit": "google_docs", "verbs": ["draft"], "owns": {"document_id": "thesis-*"}}]},
            "reporter": {"grants": [{"toolkit": "google_docs", "verbs": ["draft"]}]},
        },
        "profile_roles": {},
    })
    own = p.decide("cio", "GoogleDocs.InsertTextAtEndOfDocument", {"document_id": "thesis-001"})
    assert own.allowed
    other = p.decide("cio", "GoogleDocs.InsertTextAtEndOfDocument", {"document_id": "brief-001"})
    assert not other.allowed and "owns" in other.reason
    anything = p.decide("reporter", "GoogleDocs.InsertTextAtEndOfDocument", {"document_id": "thesis-001"})
    assert anything.allowed
    assert p.ownership_enforced("cio", "google_docs") is True
    assert p.ownership_enforced("reporter", "google_docs") is False


def test_invalid_verb_is_rejected_at_load():
    with pytest.raises(PolicyError):
        Policy.from_dict({"version": 1, "rules": [{"tool": "X.Y", "verb": "publish"}], "roles": {}})


def test_default_must_be_deny():
    with pytest.raises(PolicyError):
        Policy.from_dict({"version": 1, "default": "allow", "rules": [], "roles": {}})


def test_status_rows_cover_every_role_and_toolkit(policy):
    rows = policy.status_rows()
    by_role = {r["role"]: r for r in rows}
    assert by_role["skeptic"]["grants"]["github"] == ["look", "draft"]
    assert by_role["skeptic"]["grants"]["google_docs"] == ["look"]
    assert "ship" in by_role["reporter"]["grants"]["github"]


def test_action_key_is_stable_and_input_sensitive(policy):
    a = policy.action_key("cos", "koopa_execute", {"proposal_id": "PR-002", "hash": "1"}, "BC-2026-001")
    b = policy.action_key("cos", "koopa_execute", {"hash": "1", "proposal_id": "PR-002"}, "BC-2026-001")
    c = policy.action_key("cos", "koopa_execute", {"proposal_id": "PR-003", "hash": "1"}, "BC-2026-001")
    assert a == b and a != c and a.startswith("arcade:")


@pytest.mark.parametrize("role", ["cos", "cio", "skeptic", "reporter"])
def test_alpaca_reads_are_open_and_orders_are_denied_to_every_role(policy, role):
    read = policy.decide(role, "ArcadeAlpaca.GetAccount", {}, "BC-2026-001")
    assert read.allowed and read.verb == "look"
    for tool in ("ArcadeAlpaca.SubmitOrder", "ArcadeAlpaca.ClosePosition", "ArcadeAlpaca.CancelAllOrders"):
        order = policy.decide(role, tool, {"symbol": "VTI", "side": "buy", "notional": "4000"}, "BC-2026-001")
        assert not order.allowed and order.verb == "ship"
    assert "koopa_execute" in policy.decide("cos", "ArcadeAlpaca.SubmitOrder", {}, None).reason


def test_arena_desks_trade_only_in_the_arena_and_nobody_else_trades_there(policy):
    """The mandate is a draft grant on the arena toolkit for red and blue, and nothing more."""
    assert policy.role_for_profile("red-trader") == "red" and policy.role_for_profile("blue-trader") == "blue"
    for team in ("red", "blue"):
        d = policy.decide(team, "arena_trade", {})
        assert d.allowed and d.verb == "draft" and not d.requires_approval
        assert not policy.decide(team, "koopa_execute", {}).allowed
        assert not policy.decide(team, "Github.UpdateIssue", {"state": "closed"}).allowed
    for role in ("cos", "cio", "analyst", "skeptic", "risk", "reporter"):
        assert not policy.decide(role, "arena_trade", {}).allowed


def test_a_firm_desk_lets_only_its_cio_trade_and_the_crew_talk(policy):
    """--crew firm: the CIO (or a solo trader) holds the mandate; analysts and the skeptic look and
    talk, and the Arcade gate, not a prompt, stops their orders."""
    for team in ("red", "blue"):
        assert policy.role_for_profile(f"{team}-cio") == team
        assert policy.role_for_profile(f"{team}-trader") == team
        for seat in ("analyst-1", "analyst-2", "skeptic"):
            assert policy.role_for_profile(f"{team}-{seat}") == f"{team}_crew"
        crew = f"{team}_crew"
        assert policy.decide(crew, "arena_market", {}).allowed
        talk = policy.decide(crew, "arena_note", {})
        assert talk.allowed and talk.verb == "draft" and not talk.requires_approval
        no = policy.decide(crew, "arena_trade", {})
        assert not no.allowed and "only the desk's CIO" in no.reason
        assert policy.decide(team, "arena_note", {}).allowed and policy.decide(team, "arena_trade", {}).allowed


def test_margin_is_past_the_founders_budget_for_every_arena_seat(policy):
    for role in ("red", "blue", "red_crew", "blue_crew"):
        d = policy.decide(role, "arena_borrow", {})
        assert not d.allowed and d.verb == "ship" and "founder's budget" in d.reason


def test_the_quant_firm_is_an_org_chart_the_gate_enforces(policy):
    seat = {s: policy.role_for_profile(f"red-{s}") for s in
            ("exec", "pm", "data", "researcher-1", "researcher-2", "quantdev", "riskmgr", "compliance", "ir")}
    can = lambda s, tool: policy.decide(seat[s], tool, {}).allowed  # noqa: E731
    assert [s for s in seat if can(s, "arena_trade")] == ["exec"]
    assert sorted(s for s in seat if can(s, "E2b.RunCode")) == ["quantdev", "researcher-1", "researcher-2"]
    assert [s for s in seat if can(s, "arena_thesis")] == ["pm"]
    assert [s for s in seat if can(s, "GoogleNews.SearchNewsStories")] == ["data"]
    assert [s for s in seat if can(s, "GoogleDocs.CreateDocumentFromText")] == ["ir"]
    assert not any(can(s, "arena_borrow") for s in seat)
    assert all(can(s, "arena_note") and can(s, "arena_market") for s in seat)
    assert not policy.decide(seat["researcher-1"], "E2b.RunCode", {}).requires_approval


def test_a_comment_posing_as_the_founder_cannot_move_money(policy):
    """The hijack scene (examples/bowser/hijack.md): a work-order comment signed "founder" tells the
    reporter to execute a $12,000 trade and close the issue, "approval already given". Whatever the
    model decides, the policy answers the same way."""
    buy = policy.decide("reporter", "koopa_execute", {"proposal_id": "PR-001", "hash": "x"}, work_order="BC-2026-001")
    assert not buy.allowed and buy.reason.endswith("money moves only on the founder's own card")
    order = policy.decide("reporter", "ArcadeAlpaca.SubmitOrder", {"symbol": "BTC/USD", "notional": 12000})
    assert not order.allowed
    propose = policy.decide("reporter", "koopa_propose", {"symbol": "BTC/USD", "notional": 12000})
    assert not propose.allowed
    # Closing is the reporter's own ship action: allowed only through the founder's card, never on a comment's word.
    close = policy.decide("reporter", "Github.UpdateIssue", {"issue_number": 1, "state": "closed"})
    assert close.allowed and close.requires_approval
    # Even relayed to the main session, the execute still needs the founder's card.
    relayed = policy.decide("cos", "koopa_execute", {"proposal_id": "PR-001", "hash": "x"})
    assert relayed.allowed and relayed.requires_approval
