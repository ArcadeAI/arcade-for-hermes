"""A company spec, and the policy it becomes at each setting of the dial.

A spec is what the founder described (or a template): a name, roles with the apps they use, money
limits, and the first tasks. ``build_policy(spec, setting)`` turns it into an ordinary policy file,
so every setting is something you can read, diff and audit:

- ``yolo``: every role may use every tool in Arcade's catalog, and ship without a card. The floor
  still holds: receipts on every call, money limits, the kill switch. This is a mandate written in
  the policy, never Hermes's approvals-off switch.
- ``founder``: every role may use every tool; anything that ships waits for the founder's card.
- ``roles``: each role gets only its own apps; it ships only where the spec says it may, on a card.
- ``strict``: ``roles``, with each app's tools pinned by name from the catalog snapshot (a tool
  Arcade adds later is denied until you rebuild), plus the spec's own input-level rules.

Pure: no Hermes imports, no network. ``found.py`` writes the files and the profiles.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

SETTINGS = ("yolo", "founder", "roles", "strict")
# Where the company's tools come from: Arcade's official gateway, or one you deployed yourself.
GATEWAYS = ("arcade", "own")
# Reading the public web is a look every role gets, so any agent can research before it acts.
RESEARCH = ("GoogleSearch", "GoogleNews")
ALL_VERBS = ["look", "draft", "ship"]
_SLUG = re.compile(r"[^a-z0-9]+")


class SpecError(ValueError):
    """The company spec is malformed."""


def slugify(text: str) -> str:
    return _SLUG.sub("-", str(text).lower()).strip("-")[:32] or "company"


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    from .policy import BUNDLED_CATALOG  # noqa: WPS433 (kept local so this module stays importable alone)
    return json.loads(Path(path or BUNDLED_CATALOG).read_text(encoding="utf-8"))


def catalog_toolkits(catalog: Mapping[str, Any]) -> dict[str, str]:
    """lowercased toolkit -> the toolkit's own spelling, from the snapshot."""
    return {name.lower(): name for name in (catalog.get("toolkits") or {})}


def normalize(spec: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a spec against the catalog and fill defaults. Raises SpecError with every problem."""
    if not isinstance(spec, Mapping):
        raise SpecError("the company spec must be a mapping")
    known = catalog_toolkits(catalog)
    problems: list[str] = []
    name = str(spec.get("name") or "").strip()
    if not name:
        problems.append("name is required")
    slug = slugify(spec.get("slug") or name)
    roles_in = spec.get("roles") or {}
    if not isinstance(roles_in, Mapping) or not roles_in:
        problems.append("roles must be a mapping of role name -> {does, apps, ships, limits}")
        roles_in = {}
    default_limits = spec.get("limits") or {}
    if not isinstance(default_limits, Mapping) or any(k not in ("per_call", "per_day") for k in default_limits):
        problems.append("limits (the company default) takes only per_call and per_day")
        default_limits = {}
    roles: dict[str, dict[str, Any]] = {}
    for rname, raw in roles_in.items():
        rkey = slugify(rname).replace("-", "_")
        raw = raw or {}
        apps = []
        for app in raw.get("apps") or []:
            found = known.get(str(app).lower())
            if found is None:
                problems.append(f"roles.{rname}: {app!r} is not an Arcade toolkit (see data/arcade_verbs.json toolkits)")
            else:
                apps.append(found)
        ships = []
        for app in raw.get("ships") or []:
            found = known.get(str(app).lower())
            if found is None or found not in apps:
                problems.append(f"roles.{rname}.ships: {app!r} must be one of this role's apps")
            else:
                ships.append(found)
        limits = raw.get("limits") or default_limits
        if not isinstance(limits, Mapping) or any(k not in ("per_call", "per_day") for k in limits):
            problems.append(f"roles.{rname}.limits takes only per_call and per_day")
            limits = {}
        roles[rkey] = {"title": str(raw.get("title") or rname), "does": str(raw.get("does") or "").strip(),
                       "apps": apps, "ships": ships, "limits": dict(limits)}
    lead = slugify(spec.get("lead") or (next(iter(roles)) if roles else "")).replace("-", "_")
    if roles and lead not in roles:
        problems.append(f"lead {spec.get('lead')!r} is not one of the roles")
    money = []
    for i, m in enumerate(spec.get("money") or []):
        if not isinstance(m, Mapping) or not m.get("tool") or not m.get("amount"):
            problems.append(f"money[{i}] needs tool and amount (the input path holding dollars)")
        else:
            money.append({"tool": str(m["tool"]), "amount": str(m["amount"])})
    tasks = []
    for i, t in enumerate(spec.get("tasks") or []):
        if not isinstance(t, Mapping) or not t.get("title"):
            problems.append(f"tasks[{i}] needs a title")
            continue
        role = slugify(t.get("role") or lead).replace("-", "_")
        if role not in roles:
            problems.append(f"tasks[{i}].role {t.get('role')!r} is not one of the roles")
        tasks.append({"title": str(t["title"]), "role": role, "body": str(t.get("body") or ""),
                      "every": str(t.get("every") or "").strip() or None})
    rules = list(spec.get("rules") or [])
    gateway = str(spec.get("gateway") or "arcade").strip().lower()
    if gateway not in GATEWAYS:
        problems.append(f"gateway must be one of {GATEWAYS} (got {spec.get('gateway')!r})")
    if problems:
        raise SpecError("; ".join(problems))
    return {"name": name, "slug": slug, "pitch": str(spec.get("pitch") or "").strip(), "lead": lead,
            "limits": dict(default_limits),
            "shared_principal": str(spec.get("shared_principal") or "").strip() or None,
            "roles": roles, "money": money, "tasks": tasks, "rules": rules, "gateway": gateway,
            "setting": str(spec.get("setting") or "roles")}


def gateway_apps(path: Path | None = None) -> set[str]:
    """Lowercased apps on Arcade's official gateway, from the committed snapshot (empty if absent)."""
    p = Path(path) if path else Path(__file__).resolve().parent / "data" / "arcade_gateway_apps.json"
    try:
        return {a.lower() for a in json.loads(p.read_text(encoding="utf-8")).get("apps", [])}
    except (OSError, ValueError):
        return set()


def gateway_warnings(company: Mapping[str, Any], apps: set[str] | None = None) -> list[str]:
    """Apps the official gateway does not serve. A company on its own gateway (``gateway: own``) is
    the founder's word that it serves them; then there is nothing to warn about."""
    if company.get("gateway", "arcade") == "own":
        return []
    have = gateway_apps() if apps is None else apps
    if not have:
        return []
    missing = sorted({a for r in company["roles"].values() for a in r["apps"] if a.lower() not in have})
    if not missing:
        return []
    return [f"not on Arcade's official gateway: {', '.join(missing)}. Deploy a project gateway that serves "
            "them (arcade deploy, then a gateway in the Arcade dashboard), add it with hermes mcp add, "
            "and set gateway: own in the spec"]


def profile_name(slug: str, role: str) -> str:
    return f"{slug}-{role.replace('_', '-')}"


def build_policy(spec: Mapping[str, Any], setting: str, catalog: Mapping[str, Any]) -> dict[str, Any]:
    if setting not in SETTINGS:
        raise SpecError(f"setting must be one of {SETTINGS} (got {setting!r})")
    co = normalize(spec, catalog)
    apps = sorted({a for r in co["roles"].values() for a in r["apps"]} | set(RESEARCH))
    verbs = catalog.get("verbs") or {}
    toolkits = {a.lower(): [a] for a in apps}
    connect = {}
    for a in apps:
        who = f"{a}.WhoAmI"
        if who in verbs:
            connect[a.lower()] = who
    # Money first: a rule naming the amount is what the role's limits check.
    rules: list[dict[str, Any]] = [{"name": f"money:{m['tool']}", "tool": m["tool"], "verb": "ship", "amount": m["amount"]}
                                   for m in co["money"]]
    roles: dict[str, Any] = {}
    for rname, r in co["roles"].items():
        role: dict[str, Any] = {}
        if setting in ("yolo", "founder"):
            role["grants"] = [{"toolkit": "*", "verbs": list(ALL_VERBS)}]
        else:
            grants = []
            for a in r["apps"]:
                grants.append({"toolkit": a.lower(), "verbs": ALL_VERBS if a in r["ships"] else ["look", "draft"]})
            for a in RESEARCH:
                if a not in r["apps"]:
                    grants.append({"toolkit": a.lower(), "verbs": ["look"]})
            role["grants"] = grants
            reasons = {f"{a.lower()}.ship": f"the {r['title']} drafts on {a}; shipping there is another role's call"
                       for a in r["apps"] if a not in r["ships"]}
            if reasons:
                role["deny_reasons"] = reasons
        if setting == "yolo":
            role["approval"] = "mandate"
        if r["limits"]:
            role["limits"] = dict(r["limits"])
        roles[rname] = role
    policy: dict[str, Any] = {
        "version": 1, "default": "deny", "principal_prefix": co["slug"],
        "company": {"name": co["name"], "setting": setting},
        "toolkits": toolkits, "connect": connect,
        "profile_roles": {"default": co["lead"], **{profile_name(co["slug"], r): r for r in co["roles"]}},
        "roles": roles,
    }
    if co.get("shared_principal"):
        # Arcade's default OAuth apps accept only the signed-in Arcade user: every role acts as that one user.
        # Grants and receipts stay per role. Per-role principals need your own OAuth apps in Arcade.
        policy["shared_principal"] = co["shared_principal"]
    if setting == "strict":
        rules += [dict(x) for x in co["rules"]]
        pinned = sorted(t for t in verbs if t.split(".", 1)[0] in apps)
        rules += [{"tool": t, "verb": verbs[t]} for t in pinned]
    else:
        policy["catalog"] = True
    policy["rules"] = rules
    return policy
