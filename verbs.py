"""A verb for every Arcade tool, so a company can be granted any of the catalog's toolkits.

Two sources, and the stricter one wins (look < draft < ship):

1. Arcade's own behavior metadata, where the tool has it (about a fifth of the catalog on
   2026-11-08): ``read_only`` means look, ``destructive`` or a ``delete`` operation means ship,
   ``create``/``update`` means draft.
2. The tool's name: Get/List/Search read, Create/Update/Add write a draft, Send/Delete/Pay/Publish
   ship. A money or exposure word anywhere in the name (Refund, Payment, Invite, Permission,
   Webhook...) makes it ship whatever the leading verb says: ``CreateRefund`` moves money.

Anything neither source can place is ship, so an unknown tool goes to the founder's card, never
straight through. ``data/arcade_verbs.json`` is this function run over the live catalog by
``scripts/build_verbs.py``; the policy reads that snapshot and falls back to the name rules for a
tool the snapshot does not know.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

ORDER = {"look": 0, "draft": 1, "ship": 2}

_SHIP = re.compile(r"^(Send|Delete|Remove|Pay|Transfer|Refund|Charge|Capture|Payout|Merge|Publish|Post|Invite|Share|Close|"
                   r"Archive|Cancel|Void|Approve|Reject|Submit|Execute|Run|Trigger|Deploy|Release|Revoke|Grant|Ban|Kick|Purge|"
                   r"Destroy|Terminate|Disable|Reply|Forward|Tweet|Broadcast|Schedule|Dispatch|Rollback|Restore|Reset|"
                   r"Unpublish|Withdraw|Issue|Finalize|Sign|Logout|Suppress|Anonymize|Permanently|Abort|Batch|Bulk|Manage)")
_LOOK = re.compile(r"^(Get|List|Search|Read|Fetch|Find|Query|Retrieve|Lookup|Look|Describe|Count|Check|Who|Show|Preview|"
                   r"Download|Export|Compare|Estimate|Validate|Inspect|Browse|View|Summarize|Analyze|Scrape|Crawl|Map)")
_DRAFT = re.compile(r"^(Create|Update|Add|Edit|Set|Insert|Append|Upload|Write|Modify|Patch|Put|Rename|Move|Copy|Duplicate|"
                    r"Tag|Label|Assign|Comment|Draft|Save|Start|Mark|Upsert|Link|Attach|Enable|Configure|Change|Replace|"
                    r"Generate|Convert|Format)")
# Words that make a call money or exposure wherever they appear in the name.
_SHIP_ANYWHERE = re.compile(r"(Refund|Payment|Payout|Charge|Transfer|Invoice|Subscription|Purchase|Order|Price|Discount|"
                            r"Coupon|Payroll|Wire|Balance|Send|Publish|Post(?!gres|hog|man)|Tweet|Invite|Permission|Sharing|"
                            r"Share|Role|Access|Secret|Key|Token|Webhook|Deploy|Domain|Member|Owner|Admin|Password|Delete)")


def stricter(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a is None:
        return b
    if b is None:
        return a
    return a if ORDER[a] >= ORDER[b] else b


def _strip_toolkit_words(name: str, toolkit: str) -> str:
    # "AsanaApi.AsanaCreateTeam" reads as "CreateTeam": drop the toolkit's own name from the front.
    base = re.sub(r"Api$", "", toolkit or "")
    return name[len(base):] if base and name.startswith(base) and len(name) > len(base) else name


def from_name(qualified: str) -> Optional[str]:
    toolkit, _, name = qualified.rpartition(".")
    name = _strip_toolkit_words(name or qualified, toolkit)
    verb: Optional[str] = None
    if _SHIP.match(name):
        verb = "ship"
    elif _LOOK.match(name):
        verb = "look"
    elif _DRAFT.match(name):
        verb = "draft"
    if verb != "look" and _SHIP_ANYWHERE.search(name):
        verb = "ship"
    return verb


def from_metadata(behavior: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not behavior:
        return None
    if behavior.get("destructive"):
        return "ship"
    ops = set(behavior.get("operations") or [])
    if "delete" in ops:
        return "ship"
    if behavior.get("read_only") or ops == {"read"}:
        return "look"
    if ops and ops <= {"create", "update", "read"}:
        return "draft"
    return None


def classify(qualified: str, behavior: Optional[Mapping[str, Any]] = None) -> str:
    """The verb for one tool. Never None: what nothing can place is ship."""
    return stricter(from_metadata(behavior), from_name(qualified)) or "ship"
