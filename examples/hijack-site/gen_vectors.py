"""Build the challenge site's policy from the real Bowser policy, and pin the JS engine to the Python one.

Writes, next to this file:
- policies.json: one policy per scenario. "trading" is the subset of examples/bowser/policy.yaml the site's agents use (GitHub, Google
  Docs, Koopa, Alpaca rules; the cos and reporter roles), plus one level-5 role, ``cos_capped``, that
  adds a per-call limit and reads koopa_execute's amount. Nothing else is changed. The shirt shop,
  accounts payable and law firm policies are written below and validated by the same Policy class.
- vectors.json: decisions from policy.py (the plugin's own engine) for a spread of calls. The page
  and check_parity.js run the JS port over the same calls and must get the same answers.

Run with the Hermes venv from the repo root:
    ~/hermes-v0.23.0/.venv/bin/python examples/hijack-site/gen_vectors.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
import importlib.util  # noqa: E402

# policy.py is pure (no Hermes imports): load it alone, as tests/conftest.py loads the package.
_spec = importlib.util.spec_from_file_location("afh_policy", ROOT / "policy.py")
_policy = importlib.util.module_from_spec(_spec)
sys.modules["afh_policy"] = _policy
_spec.loader.exec_module(_policy)
Policy, load_yaml = _policy.Policy, _policy.load_yaml

KEEP_TOOLKITS = {"github", "google_docs", "alpaca"}


def site_policy() -> dict:
    src = load_yaml(ROOT / "examples" / "bowser" / "policy.yaml")
    toolkits = {k: v for k, v in src["toolkits"].items() if k in KEEP_TOOLKITS}
    aliases = {a.lower() for names in toolkits.values() for a in names}
    rules = []
    for rule in src["rules"]:
        tool = rule["tool"]
        if rule.get("toolkit") == "koopa" or ("." in tool and tool.split(".", 1)[0].lower() in aliases):
            rules.append(copy.deepcopy(rule))
    roles = {name: copy.deepcopy(src["roles"][name]) for name in ("cos", "reporter")}
    # Level 5: the same Chief of Staff with a money cap. koopa_execute names its amount here.
    capped = copy.deepcopy(roles["cos"])
    capped["limits"] = {"per_call": 500, "per_day": 1000}
    roles["cos_capped"] = capped
    for rule in rules:
        if rule["tool"] == "koopa_execute":
            rule["amount"] = "notional"
    return {"version": 1, "default": "deny", "principal_prefix": "bowser", "toolkits": toolkits,
            "rules": rules, "roles": roles}


TOOLS = [
    ("Github.GetIssue", {"issue_number": 1}),
    ("Github.CreateIssueComment", {"issue_number": 1, "body": "hi"}),
    ("Github.UpdateIssue", {"issue_number": 1, "state": "closed"}),
    ("Github.UpdateIssue", {"issue_number": 1, "state": "CLOSED"}),
    ("Github.UpdateIssue", {"issue_number": 1, "state": "open", "body": "x"}),
    ("Github.UpdateIssue", {"issue_number": 1, "title": "new"}),
    ("github.updateissue", {"state": "closed"}),
    ("GoogleDocs.SearchAndRetrieveDocuments", {"document_contains": ["memo"]}),
    ("GoogleDocs.CreateDocumentFromText", {"title": "Brief", "text_content": "x"}),
    ("GoogleDocs.EditDocument", {"document_id": "d1"}),
    ("GoogleDocs.EditDocument", {"document_id": "d1", "requests": [{"insertText": {}}]}),
    ("GoogleDocs.DeleteDocument", {"document_id": "d1"}),
    ("koopa_report", {}),
    ("koopa_propose", {"symbol": "BTC/USD", "side": "buy", "notional": 400}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": 400}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": 12000}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": "$1,200.50"}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": "499.99"}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": 500}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": 500.5}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": 300}),
    ("koopa_execute", {"proposal_id": "PR-001"}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": "lots"}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": True}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": -5}),
    ("koopa_execute", {"proposal_id": "PR-001", "notional": ""}),
    ("ArcadeAlpaca.SubmitOrder", {"symbol": "BTC/USD", "side": "buy", "notional": 12000}),
    ("ArcadeAlpaca.ClosePosition", {"symbol": "BTC/USD"}),
    ("ArcadeAlpaca.CancelAllOrders", {}),
    ("ArcadeAlpaca.GetAccount", {}),
    ("ArcadeAlpaca.Transfer", {"amount": 5}),
    ("Slack.SendMessage", {"text": "x"}),
    ("send_money", {}),
]
ROLES = ["reporter", "cos", "cos_capped", "exit_check", "intern"]
STATES = [{}, {"halted": "founder at dinner"}, {"spent_today": 700}]


# ----------------------------------------------------------------------------- the other scenarios
# Same engine, same five rooms; only the business changes. Each policy names three roles: a low badge
# (room 3), the one role that ships (room 4) and that role capped (room 5). Tool names follow Arcade's
# naming; on the page they are fixtures.

def _email_rules(domain: str) -> list:
    # One tool, two verbs: mail inside the company is a draft, mail to anyone else ships.
    return [{"tool": "Gmail.ListEmails", "verb": "look"},
            {"name": "email-inside", "tool": "Gmail.SendEmail", "verb": "draft", "input": {"recipient": "*@" + domain}},
            {"name": "email-outside", "tool": "Gmail.SendEmail", "verb": "ship"}]


def shirts_policy() -> dict:
    return {"version": 1, "default": "deny", "principal_prefix": "loudtees",
            "toolkits": {"gmail": ["Gmail"], "shopify": ["Shopify"], "stripe": ["Stripe"], "sheets": ["GoogleSheets"]},
            "rules": _email_rules("loudtees.co") + [
                {"tool": "Shopify.GetOrder", "verb": "look"},
                {"tool": "Shopify.ListOrders", "verb": "look"},
                {"tool": "GoogleSheets.GetSpreadsheet", "verb": "look"},
                {"tool": "Shopify.CreateDiscountCode", "verb": "ship"},
                {"name": "price-change", "tool": "Shopify.UpdateProduct", "verb": "ship", "input": {"price": "*"}},
                {"tool": "Shopify.UpdateProduct", "verb": "draft"},
                {"tool": "Stripe.CreateRefund", "verb": "ship", "amount": "amount"},
            ],
            "roles": {
                "support": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft", "ship"]},
                                       {"toolkit": "shopify", "verbs": ["look"]}],
                            "deny_reasons": {"stripe.ship": "support answers customers; refunds go to the ops lead's card",
                                             "shopify.ship": "support doesn't set prices or discounts",
                                             "sheets": "supplier costs stay with ops"}},
                "ops": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft", "ship"]},
                                   {"toolkit": "shopify", "verbs": ["look", "draft", "ship"]},
                                   {"toolkit": "stripe", "verbs": ["ship"]},
                                   {"toolkit": "sheets", "verbs": ["look"]}]},
                "ops_capped": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft", "ship"]},
                                          {"toolkit": "shopify", "verbs": ["look", "draft", "ship"]},
                                          {"toolkit": "stripe", "verbs": ["ship"]},
                                          {"toolkit": "sheets", "verbs": ["look"]}],
                               "limits": {"per_call": 50, "per_day": 150}},
            }}


def finance_policy() -> dict:
    return {"version": 1, "default": "deny", "principal_prefix": "ledgerline",
            "toolkits": {"gmail": ["Gmail"], "quickbooks": ["QuickBooks"], "payments": ["Payments"], "drive": ["GoogleDrive"]},
            "rules": _email_rules("ledgerline.io") + [
                {"tool": "QuickBooks.GetVendor", "verb": "look"},
                {"tool": "QuickBooks.ListBills", "verb": "look"},
                {"tool": "QuickBooks.CreateBill", "verb": "draft"},
                {"tool": "QuickBooks.UpdateVendorBankAccount", "verb": "ship"},
                {"tool": "Payments.PayBill", "verb": "ship", "amount": "amount"},
                {"tool": "GoogleDrive.SearchFiles", "verb": "look"},
            ],
            "roles": {
                "ap_clerk": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft"]},
                                        {"toolkit": "quickbooks", "verbs": ["look", "draft"]}],
                             "deny_reasons": {"quickbooks.ship": "the clerk enters bills; bank details change only on the controller's card",
                                              "payments": "the clerk enters bills; the controller pays them",
                                              "gmail.ship": "the clerk doesn't email outside the company",
                                              "drive": "payroll is the controller's"}},
                "controller": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft", "ship"]},
                                          {"toolkit": "quickbooks", "verbs": ["look", "draft", "ship"]},
                                          {"toolkit": "payments", "verbs": ["ship"]},
                                          {"toolkit": "drive", "verbs": ["look"]}]},
                "controller_capped": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft", "ship"]},
                                                 {"toolkit": "quickbooks", "verbs": ["look", "draft", "ship"]},
                                                 {"toolkit": "payments", "verbs": ["ship"]},
                                                 {"toolkit": "drive", "verbs": ["look"]}],
                                      "limits": {"per_call": 2500, "per_day": 5000}},
            }}


def legal_policy() -> dict:
    return {"version": 1, "default": "deny", "principal_prefix": "hartvale",
            "toolkits": {"gmail": ["Gmail"], "google_docs": ["GoogleDocs"], "docusign": ["DocuSign"], "escrow": ["Escrow"]},
            "rules": _email_rules("hartvale.law") + [
                {"tool": "GoogleDocs.SearchAndRetrieveDocuments", "verb": "look"},
                {"name": "edit-document-read", "tool": "GoogleDocs.EditDocument", "verb": "look", "input": {"requests": "!"}},
                {"tool": "GoogleDocs.EditDocument", "verb": "draft"},
                {"tool": "DocuSign.SendEnvelope", "verb": "ship"},
                {"tool": "Escrow.GetBalance", "verb": "look"},
                {"tool": "Escrow.ReleaseFunds", "verb": "ship", "amount": "amount"},
            ],
            "roles": {
                "paralegal": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft"]},
                                         {"toolkit": "google_docs", "verbs": ["look", "draft"]}],
                              "deny_reasons": {"gmail.ship": "nothing leaves the firm without a partner",
                                               "docusign": "only a partner sends for signature",
                                               "escrow": "client funds move only on a partner's card"}},
                "partner": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft", "ship"]},
                                       {"toolkit": "google_docs", "verbs": ["look", "draft"]},
                                       {"toolkit": "docusign", "verbs": ["ship"]},
                                       {"toolkit": "escrow", "verbs": ["look", "ship"]}]},
                "partner_capped": {"grants": [{"toolkit": "gmail", "verbs": ["look", "draft", "ship"]},
                                              {"toolkit": "google_docs", "verbs": ["look", "draft"]},
                                              {"toolkit": "docusign", "verbs": ["ship"]},
                                              {"toolkit": "escrow", "verbs": ["look", "ship"]}],
                                   "limits": {"per_call": 1000, "per_day": 1000}},
            }}


def _money_cases(tool, base):
    return [(tool, {**base, "amount": v}) for v in (38, 49.99, 50, 50.01, 999, 1000, 2140, 2500.01, 120000, "$1,200.50", "lots", True, -5, "")] + [(tool, base)]


SUITES = {
    "shirts": (shirts_policy, ["support", "ops", "ops_capped", "nobody"], [
        ("Gmail.ListEmails", {}), ("Gmail.SendEmail", {"recipient": "maya@loudtees.co", "body": "x"}),
        ("Gmail.SendEmail", {"recipient": "Maya@LoudTees.co", "body": "x"}), ("Gmail.SendEmail", {"recipient": "a@gmail.com", "body": "x"}),
        ("Gmail.SendEmail", {"recipient": "a@loudtees.co.evil.com", "body": "x"}), ("Gmail.SendEmail", {"body": "x"}),
        ("Shopify.GetOrder", {"order_id": "1042"}), ("Shopify.CreateDiscountCode", {"code": "X", "percent": 100}),
        ("Shopify.UpdateProduct", {"product_id": "p1", "price": 1}), ("Shopify.UpdateProduct", {"product_id": "p1", "title": "x"}),
        ("GoogleSheets.GetSpreadsheet", {"spreadsheet_id": "s1"}), ("Shopify.DeleteProduct", {"product_id": "p1"}),
    ] + _money_cases("Stripe.CreateRefund", {"order_id": "1042"})),
    "finance": (finance_policy, ["ap_clerk", "controller", "controller_capped", "nobody"], [
        ("Gmail.ListEmails", {}), ("Gmail.SendEmail", {"recipient": "dana@ledgerline.io", "body": "x"}),
        ("Gmail.SendEmail", {"recipient": "billing@northwind-paper.com", "body": "x"}),
        ("QuickBooks.GetVendor", {"vendor": "Northwind Paper"}), ("QuickBooks.CreateBill", {"vendor": "Northwind Paper", "amount": 5}),
        ("QuickBooks.UpdateVendorBankAccount", {"vendor": "Northwind Paper", "routing": "1", "account": "2"}),
        ("GoogleDrive.SearchFiles", {"query": "payroll"}), ("QuickBooks.DeleteVendor", {"vendor": "x"}),
    ] + _money_cases("Payments.PayBill", {"bill_id": "B-311"})),
    "legal": (legal_policy, ["paralegal", "partner", "partner_capped", "nobody"], [
        ("Gmail.ListEmails", {}), ("Gmail.SendEmail", {"recipient": "ana@hartvale.law", "body": "x"}),
        ("Gmail.SendEmail", {"recipient": "counsel@acme-legal.com", "body": "x"}),
        ("GoogleDocs.SearchAndRetrieveDocuments", {"document_contains": ["memo"]}),
        ("GoogleDocs.EditDocument", {"document_id": "d1"}), ("GoogleDocs.EditDocument", {"document_id": "d1", "requests": [{}]}),
        ("DocuSign.SendEnvelope", {"document_id": "doc-nda-v3", "recipient": "counsel@acme-legal.com"}),
        ("Escrow.GetBalance", {}), ("Escrow.CloseAccount", {}),
    ] + _money_cases("Escrow.ReleaseFunds", {"payee": "x"})),
}


def suite(policy_data: dict, roles: list, tools: list) -> list:
    policy = Policy.from_dict(policy_data)
    cases = []
    for role in roles:
        for tool, args in tools:
            for state in STATES:
                d = policy.decide(role, tool, args, **state).as_dict()
                cases.append({"role": role, "tool": tool, "input": args, "state": state,
                              "expect": {k: d[k] for k in ("allowed", "verb", "toolkit", "reason", "rule",
                                                           "requires_approval", "amount", "exit")}})
    return cases


def main() -> None:
    data = site_policy()
    # The vectors also cover exits under halt and limits on Alpaca orders, which no site role reaches:
    # one extra role, in the vectors' policy only.
    checked = copy.deepcopy(data)
    checked["roles"]["exit_check"] = {"grants": [{"toolkit": "alpaca", "verbs": ["look", "ship"]}],
                                      "limits": {"per_call": 500, "per_day": 1000}}
    policies = {"trading": data}
    suites = [{"scenario": "trading", "policy": checked, "cases": suite(checked, ROLES, TOOLS)}]
    for key, (make, roles, tools) in SUITES.items():
        policies[key] = make()
        suites.append({"scenario": key, "policy": policies[key], "cases": suite(policies[key], roles, tools)})
    (HERE / "policies.json").write_text(json.dumps(policies, indent=1) + "\n")
    (HERE / "vectors.json").write_text(json.dumps({"suites": suites}, separators=(",", ":")) + "\n")
    print("policies.json:", {k: len(v["rules"]) for k, v in policies.items()},
          "; vectors.json:", {s["scenario"]: len(s["cases"]) for s in suites})


if __name__ == "__main__":
    main()
