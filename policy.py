"""The look/draft/ship policy engine.

Pure Python and offline: no Hermes imports, no network, no secrets. The policy file decides, for a
role and a tool call, whether the call is allowed and which verb it is:

- ``look``: read. Allowed, with a receipt.
- ``draft``: create or edit an artifact. Allowed, with a receipt.
- ``ship``: anything others see, or anything that moves money. Goes to Hermes's approval gate.

Everything unknown is denied: an unknown role, a tool no rule classifies, a toolkit the policy does
not declare, a verb the role has no grant for. A rule can match on the tool's input as well as its
name, so one general Arcade tool (``Github.UpdateIssue``) is ``draft`` when it edits and ``ship``
when it closes. Non-Arcade Hermes tools are governed by the same rules when a rule names them with an
explicit ``toolkit``; nothing about any particular local tool lives in this module.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

VERBS: tuple[str, ...] = ("look", "draft", "ship")
ACTION_KEY_PREFIX = "arcade:"


class PolicyError(ValueError):
    """The policy file is malformed. Raised at load, never at decision time."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    role: str
    tool: str
    verb: Optional[str]
    toolkit: Optional[str]
    reason: str
    rule: Optional[str] = None
    amount: Optional[float] = None     # the money this call moves, read from the rule's `amount` input path
    exit: bool = False                 # a rule marked exit (close, cancel): still runs, to the card, while halted
    mandate: bool = False              # a ship the role may run without a card (approval: mandate)

    @property
    def requires_approval(self) -> bool:
        return self.allowed and self.verb == "ship" and not self.mandate

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed, "role": self.role, "tool": self.tool, "verb": self.verb,
            "toolkit": self.toolkit, "reason": self.reason, "rule": self.rule,
            "requires_approval": self.requires_approval, "amount": self.amount, "exit": self.exit,
            "mandate": self.mandate,
        }


@dataclass(frozen=True)
class Rule:
    name: str
    tool: str
    verb: str
    toolkit: Optional[str]
    input: Mapping[str, Any]
    amount: Optional[str] = None       # dotted input path holding the money amount (e.g. "notional")
    exit: bool = False

    def matches(self, tool_name: str, tool_input: Mapping[str, Any]) -> bool:
        if not fnmatch.fnmatchcase(tool_name.lower(), self.tool.lower()):
            return False
        return all(_match_value(expected, _get_path(tool_input, key)) for key, expected in self.input.items())


@dataclass(frozen=True)
class Grant:
    toolkit: str
    verbs: tuple[str, ...]
    owns: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class Role:
    name: str
    principal: Optional[str]
    grants: tuple[Grant, ...]
    deny_reasons: Mapping[str, str]
    limits: Mapping[str, float] = None  # per_call / per_day caps on calls whose rule names an amount
    approval: str = "card"              # "card": ship waits for the founder; "mandate": ship runs, receipted


LIMIT_KEYS = ("per_call", "per_day")
APPROVALS = ("card", "mandate")
ANY_TOOLKIT = "*"
BUNDLED_CATALOG = Path(__file__).resolve().parent / "data" / "arcade_verbs.json"


def _verbs_module():
    """verbs.py, whether this file is loaded as part of the plugin package or on its own."""
    try:
        from . import verbs  # type: ignore
        return verbs
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location("afh_verbs", Path(__file__).resolve().parent / "verbs.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module


def _amount(value: Any) -> Optional[float]:
    """A positive finite number from an input value ("1,200.50" and 1200.5 both read), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("$", "").strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"),) and number >= 0 else None


def _get_path(data: Any, dotted: str) -> Any:
    current = data
    for part in dotted.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return None
    return current


def _match_value(expected: Any, actual: Any) -> bool:
    """Input matcher: ``"*"`` means present, ``"!"`` means absent, a list means any of, a string is a
    case-insensitive glob, a bool or number must be equal."""
    if expected == "*":
        return actual is not None
    if expected == "!":
        return actual is None
    if isinstance(expected, list):
        return any(_match_value(item, actual) for item in expected)
    if isinstance(expected, bool):
        return actual is expected or (isinstance(actual, str) and actual.lower() == str(expected).lower())
    if isinstance(expected, (int, float)):
        return actual == expected
    if isinstance(expected, str):
        if actual is None or isinstance(actual, (Mapping, list)):
            return False
        return fnmatch.fnmatchcase(str(actual).lower(), expected.lower())
    return expected == actual


def _as_list(value: Any, what: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PolicyError(f"{what} must be a list")
    return value


def load_yaml(path: Path) -> Any:
    """Parse a YAML file with whatever loader is present: ruamel.yaml (ships with Hermes), PyYAML, or
    JSON as a last resort (every JSON file is a YAML file)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        from ruamel.yaml import YAML  # type: ignore

        return YAML(typ="safe").load(text)
    except ImportError:
        pass
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        pass
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ValueError("no YAML parser found (ruamel.yaml ships with Hermes; install it or PyYAML), and the file is "
                         f"not JSON either: {exc}") from exc


class Policy:
    """A parsed, validated policy. Build with :meth:`load` or :meth:`from_dict`."""

    def __init__(self, data: Mapping[str, Any], *, source: str = "<dict>") -> None:
        if not isinstance(data, Mapping):
            raise PolicyError(f"{source}: policy must be a mapping")
        self.source = source
        self.version = int(data.get("version", 1) or 1)
        default = str(data.get("default", "deny")).lower()
        if default != "deny":
            raise PolicyError(f"{source}: default must be 'deny' (got {default!r}); this policy never allows by default")
        self.principal_prefix = str(data.get("principal_prefix") or "agent").strip().strip("/")
        # One Arcade user_id for every role. Works with Arcade's default OAuth apps, which only accept the
        # signed-in Arcade user. Grants and receipts stay per role; Arcade itself sees one user.
        self.shared_principal = str(data.get("shared_principal") or "").strip() or None
        # Set by /arcade found: which company and which setting of the dial made this file.
        self.company = dict(data.get("company") or {}) if isinstance(data.get("company"), Mapping) else {}

        aliases: dict[str, str] = {}
        toolkit_ids: dict[str, str] = {}
        toolkits = data.get("toolkits") or {}
        if not isinstance(toolkits, Mapping):
            raise PolicyError(f"{source}: toolkits must be a mapping of canonical name -> aliases")
        for canonical, names in toolkits.items():
            canon = str(canonical).lower()
            aliases[canon] = canon
            listed = _as_list(names, f"toolkits.{canonical}")
            # Arcade's toolkit filter wants the id as it appears before the dot, lowercased ("googledocs").
            toolkit_ids[canon] = str(listed[0]).lower() if listed else canon
            for alias in listed:
                aliases[str(alias).lower()] = canon
        self._aliases = aliases
        self._toolkit_ids = toolkit_ids

        # The catalog: a verb for every Arcade tool (data/arcade_verbs.json, built by scripts/build_verbs.py).
        # With it on, any tool of any catalog toolkit is classified; explicit rules still come first.
        self._catalog: dict[str, str] = {}
        self._catalog_toolkits: set[str] = set()
        self._classify_name = None
        catalog = data.get("catalog", False)
        if catalog:
            cpath = BUNDLED_CATALOG if catalog is True else Path(str(catalog)).expanduser()
            if catalog is not True and not cpath.is_absolute() and source != "<dict>":
                cpath = Path(source).resolve().parent / cpath
            try:
                snapshot = json.loads(cpath.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise PolicyError(f"{source}: catalog {cpath} cannot be read: {exc}") from exc
            for name, verb in (snapshot.get("verbs") or {}).items():
                if verb in VERBS:
                    self._catalog[str(name).lower()] = verb
                    self._catalog_toolkits.add(str(name).split(".", 1)[0].lower())
            self._classify_name = _verbs_module().classify

        rules: list[Rule] = []
        for i, raw in enumerate(_as_list(data.get("rules"), "rules")):
            if not isinstance(raw, Mapping) or not raw.get("tool") or not raw.get("verb"):
                raise PolicyError(f"{source}: rules[{i}] needs 'tool' and 'verb'")
            verb = str(raw["verb"]).lower()
            if verb not in VERBS:
                raise PolicyError(f"{source}: rules[{i}] verb {verb!r} is not one of {VERBS}")
            matchers = raw.get("input") or {}
            if not isinstance(matchers, Mapping):
                raise PolicyError(f"{source}: rules[{i}].input must be a mapping")
            toolkit = raw.get("toolkit")
            amount = raw.get("amount")
            if amount is not None and (not isinstance(amount, str) or not amount.strip()):
                raise PolicyError(f"{source}: rules[{i}].amount must be the input path that holds the amount, e.g. notional")
            rules.append(Rule(
                name=str(raw.get("name") or f"rules[{i}]:{raw['tool']}"), tool=str(raw["tool"]), verb=verb,
                toolkit=str(toolkit).lower() if toolkit else None, input=dict(matchers),
                amount=amount.strip() if amount else None, exit=bool(raw.get("exit", False)),
            ))
        self.rules: tuple[Rule, ...] = tuple(rules)
        local_toolkits = {r.toolkit for r in rules if r.toolkit}
        self._known_toolkits = set(aliases.values()) | local_toolkits | self._catalog_toolkits

        roles: dict[str, Role] = {}
        raw_roles = data.get("roles") or {}
        if not isinstance(raw_roles, Mapping):
            raise PolicyError(f"{source}: roles must be a mapping")
        for name, raw in raw_roles.items():
            raw = raw or {}
            if not isinstance(raw, Mapping):
                raise PolicyError(f"{source}: roles.{name} must be a mapping")
            grants: list[Grant] = []
            for j, g in enumerate(_as_list(raw.get("grants"), f"roles.{name}.grants")):
                if not isinstance(g, Mapping) or not g.get("toolkit"):
                    raise PolicyError(f"{source}: roles.{name}.grants[{j}] needs 'toolkit'")
                toolkit = str(g["toolkit"]).lower()
                if toolkit != ANY_TOOLKIT and toolkit not in self._known_toolkits:
                    raise PolicyError(f"{source}: roles.{name}.grants[{j}] toolkit {toolkit!r} is not declared under toolkits or by a rule")
                verbs = tuple(str(v).lower() for v in _as_list(g.get("verbs"), f"roles.{name}.grants[{j}].verbs"))
                for v in verbs:
                    if v not in VERBS:
                        raise PolicyError(f"{source}: roles.{name}.grants[{j}] verb {v!r} is not one of {VERBS}")
                owns = g.get("owns")
                if owns is not None and not isinstance(owns, Mapping):
                    raise PolicyError(f"{source}: roles.{name}.grants[{j}].owns must be a mapping of input matchers")
                grants.append(Grant(toolkit=toolkit, verbs=verbs, owns=dict(owns) if owns else None))
            deny_reasons = raw.get("deny_reasons") or {}
            if not isinstance(deny_reasons, Mapping):
                raise PolicyError(f"{source}: roles.{name}.deny_reasons must be a mapping")
            principal = raw.get("principal")
            limits_raw = raw.get("limits") or {}
            if not isinstance(limits_raw, Mapping) or any(k not in LIMIT_KEYS for k in limits_raw):
                raise PolicyError(f"{source}: roles.{name}.limits takes only {LIMIT_KEYS}")
            limits: dict[str, float] = {}
            for k, v in limits_raw.items():
                if _amount(v) is None:
                    raise PolicyError(f"{source}: roles.{name}.limits.{k} must be a number >= 0")
                limits[k] = _amount(v)
            approval = str(raw.get("approval") or "card").lower()
            if approval not in APPROVALS:
                raise PolicyError(f"{source}: roles.{name}.approval must be one of {APPROVALS} (got {approval!r})")
            roles[str(name)] = Role(
                name=str(name), principal=str(principal) if principal else None, grants=tuple(grants),
                deny_reasons={str(k): str(v) for k, v in deny_reasons.items()}, limits=limits, approval=approval,
            )
        self.roles: dict[str, Role] = roles

        profile_roles = data.get("profile_roles") or {}
        if not isinstance(profile_roles, Mapping):
            raise PolicyError(f"{source}: profile_roles must be a mapping of profile -> role")
        for profile, role in profile_roles.items():
            if str(role) not in roles:
                raise PolicyError(f"{source}: profile_roles.{profile} names unknown role {role!r}")
        self.profile_roles: dict[str, str] = {str(k): str(v) for k, v in profile_roles.items()}

        connect = data.get("connect") or {}
        if not isinstance(connect, Mapping):
            raise PolicyError(f"{source}: connect must be a mapping of toolkit -> representative tool name")
        self.connect: dict[str, str] = {str(k).lower(): str(v) for k, v in connect.items()}

    # ----------------------------------------------------------------------------- constructors
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Policy":
        return cls(data)

    @classmethod
    def load(cls, path: Path | str) -> "Policy":
        path = Path(path)
        try:
            data = load_yaml(path)
        except FileNotFoundError:
            raise PolicyError(f"policy file not found: {path}") from None
        except Exception as exc:  # malformed YAML/JSON
            raise PolicyError(f"{path}: cannot parse policy: {exc}") from exc
        return cls(data or {}, source=str(path))

    # ----------------------------------------------------------------------------- lookups
    @property
    def toolkits(self) -> list[str]:
        return sorted(self._known_toolkits)

    @property
    def arcade_toolkits(self) -> list[str]:
        """Canonical names of the toolkits that live in Arcade (declared under ``toolkits``)."""
        return sorted(self._toolkit_ids)

    def arcade_toolkit_id(self, canonical: str) -> Optional[str]:
        """The toolkit id Arcade's list filter accepts for a canonical name, or None for a local toolkit."""
        return self._toolkit_ids.get(canonical.lower())

    def toolkit_of(self, tool_name: str) -> Optional[str]:
        """Canonical toolkit for a tool name: an explicit rule toolkit for local tools, else the Arcade
        prefix before the dot resolved through the alias table."""
        for rule in self.rules:
            if rule.toolkit and fnmatch.fnmatchcase(tool_name.lower(), rule.tool.lower()):
                return rule.toolkit
        if "." in tool_name:
            prefix = tool_name.split(".", 1)[0].lower()
            found = self._aliases.get(prefix)
            if found is None and prefix in self._catalog_toolkits:
                return prefix
            return found
        return None

    @property
    def catalog_size(self) -> int:
        return len(self._catalog)

    def classify(self, tool_name: str, tool_input: Optional[Mapping[str, Any]]) -> Optional[Rule]:
        tool_input = tool_input if isinstance(tool_input, Mapping) else {}
        for rule in self.rules:
            if rule.matches(tool_name, tool_input):
                return rule
        if self._classify_name is not None and "." in tool_name:
            verb = self._catalog.get(tool_name.lower())
            source = "catalog"
            if verb is None and tool_name.split(".", 1)[0].lower() in self._catalog_toolkits:
                verb, source = self._classify_name(tool_name), "catalog-name"   # a tool newer than the snapshot
            if verb:
                return Rule(name=f"{source}:{verb}", tool=tool_name, verb=verb, toolkit=None, input={})
        return None

    def rules_for_tool(self, tool_name: str) -> list[Rule]:
        """Every rule whose name glob matches, in order, regardless of input matchers."""
        return [rule for rule in self.rules if fnmatch.fnmatchcase(tool_name.lower(), rule.tool.lower())]

    def governs(self, tool_name: str) -> bool:
        """True for a non-Arcade Hermes tool the policy names (a rule with an explicit toolkit)."""
        if "." in tool_name or tool_name == "arcade_execute":
            return False
        return any(rule.toolkit and fnmatch.fnmatchcase(tool_name.lower(), rule.tool.lower()) for rule in self.rules)

    def role_for_profile(self, profile: Optional[str]) -> Optional[str]:
        if not profile:
            return None
        mapped = self.profile_roles.get(profile)
        if mapped:
            return mapped
        if profile in self.roles:
            return profile
        # Wildcards ("analyst-*": analyst) let a swarm of profiles share a role. Exact names win;
        # among patterns the longest (most specific) wins, so the answer never depends on order.
        matches = [(len(p), r) for p, r in self.profile_roles.items()
                   if any(c in p for c in "*?[") and fnmatch.fnmatchcase(profile, p)]
        return max(matches)[1] if matches else None

    def principal(self, role: str) -> str:
        if self.shared_principal:
            return self.shared_principal
        spec = self.roles.get(role)
        if spec is not None and spec.principal:
            return spec.principal
        return f"{self.principal_prefix}/{role}"

    def grants_for(self, role: str, toolkit: str) -> list[Grant]:
        spec = self.roles.get(role)
        return [g for g in (spec.grants if spec else ()) if g.toolkit in (toolkit, ANY_TOOLKIT)]

    def ownership_enforced(self, role: str, toolkit: str) -> bool:
        return any(g.owns for g in self.grants_for(role, toolkit))

    # ----------------------------------------------------------------------------- the decision
    def decide(self, role: str, tool_name: str, tool_input: Optional[Mapping[str, Any]],
               work_order: Optional[str] = None, *, halted: Optional[str] = None,
               spent_today: float = 0.0) -> Decision:
        """``halted`` is the founder's halt reason when the kill switch is on (every draft and ship is
        denied except rules marked exit). ``spent_today`` is what this role already moved today under
        rules that name an amount; the caller reads it from the receipts."""
        tool_input = tool_input if isinstance(tool_input, Mapping) else {}
        if role not in self.roles:
            return Decision(False, role, tool_name, None, None, f"role {role!r} is not in the policy; default deny")
        rule = self.classify(tool_name, tool_input)
        if rule is None:
            return Decision(False, role, tool_name, None, self.toolkit_of(tool_name),
                            f"no rule classifies {tool_name}; default deny")
        toolkit = rule.toolkit or self.toolkit_of(tool_name)
        if toolkit is None:
            return Decision(False, role, tool_name, rule.verb, None,
                            f"toolkit of {tool_name} is not declared in the policy; default deny", rule.name)
        verb = rule.verb
        matching = [g for g in self.grants_for(role, toolkit) if verb in g.verbs]
        if not matching:
            reason = f"{role} has no {verb} grant on {toolkit}"
            extra = self.roles[role].deny_reasons.get(f"{toolkit}.{verb}") or self.roles[role].deny_reasons.get(toolkit)
            if extra:
                reason = f"{reason}: {extra}"
            return Decision(False, role, tool_name, verb, toolkit, reason, rule.name)
        unowned = [g for g in matching if g.owns and not all(_match_value(v, _get_path(tool_input, k)) for k, v in g.owns.items())]
        if unowned and len(unowned) == len(matching):
            owns = unowned[0].owns or {}
            return Decision(False, role, tool_name, verb, toolkit,
                            f"{tool_name} targets an artifact {role} does not own (owns: {json.dumps(owns, sort_keys=True)})",
                            rule.name)
        amount = _amount(_get_path(tool_input, rule.amount)) if rule.amount else None
        def deny(reason: str) -> Decision:
            return Decision(False, role, tool_name, verb, toolkit, reason, rule.name, amount, rule.exit)
        if halted and verb != "look" and not rule.exit:
            why = "" if str(halted).strip().lower() in ("", "true", "halted by the founder") else f" ({halted})"
            return deny(f"halted by the founder{why}; only exits run until /arcade resume")
        limits = self.roles[role].limits or {}
        if rule.amount and limits and not rule.exit:
            if amount is None:
                return deny(f"{tool_name} has no readable amount at '{rule.amount}', so {role}'s limits cannot be checked")
            cap = limits.get("per_call")
            if cap is not None and amount > cap:
                return deny(f"{amount:,.2f} is over {role}'s per-call limit of {cap:,.2f}")
            cap = limits.get("per_day")
            if cap is not None and spent_today + amount > cap:
                return deny(f"{amount:,.2f} would take {role} to {spent_today + amount:,.2f} today, over the daily limit of {cap:,.2f}")
        mandate = verb == "ship" and self.roles[role].approval == "mandate"
        reason = f"{role} may {verb} on {toolkit}" + (" under the founder's mandate (no card)" if mandate else "")
        return Decision(True, role, tool_name, verb, toolkit, reason, rule.name, amount, rule.exit, mandate)

    # ----------------------------------------------------------------------------- reporting
    def status_rows(self) -> list[dict[str, Any]]:
        rows = []
        for name, spec in self.roles.items():
            grants: dict[str, list[str]] = {}
            ownership: dict[str, bool] = {}
            for g in spec.grants:
                merged = grants.setdefault(g.toolkit, [])
                for v in VERBS:
                    if v in g.verbs and v not in merged:
                        merged.append(v)
                ownership[g.toolkit] = ownership.get(g.toolkit, False) or bool(g.owns)
            rows.append({"role": name, "principal": self.principal(name), "grants": grants, "ownership": ownership})
        return rows

    @staticmethod
    def action_key(role: str, tool_name: str, tool_input: Optional[Mapping[str, Any]], work_order: Optional[str]) -> str:
        """Per-action approval key: a 'session' or 'always' answer covers this exact action only."""
        payload = json.dumps({"role": role, "tool": tool_name, "input": tool_input or {}, "work_order": work_order or ""},
                             sort_keys=True, default=str, separators=(",", ":"))
        return ACTION_KEY_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
