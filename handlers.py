"""Tool handlers: arcade_search_tools, arcade_authorize, arcade_execute, arcade_whoami.

Every handler returns a JSON string and never raises. ``arcade_execute`` re-checks the policy and
refuses anything denied, and refuses a ship action that did not pass through the pre_tool_call gate,
so the hook is not the only control.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Optional

from .client import ArcadeUnavailable, describe_error, get_client, key_present
from .acting import HANDOFF, acting_for
from .hooks import NEEDS_HUMAN, Governor
from .identity import resolve_role
from .policy import Policy, PolicyError
from .receipts import extract_url
from .runtime import Runtime

logger = logging.getLogger(__name__)

MAX_VALUE_CHARS = 20_000
MAX_LIST_PER_TOOLKIT = 300


def _dumps(payload: Any) -> str:
    return json.dumps(payload, default=str)


def _auth_payload(auth: Any) -> Optional[dict[str, Any]]:
    if auth is None:
        return None
    status = getattr(auth, "status", None)
    url = getattr(auth, "url", None)
    if url or status in ("not_started", "pending"):
        return {"status": status, "url": url, "authorization_id": getattr(auth, "id", None),
                "provider_id": getattr(auth, "provider_id", None), "scopes": getattr(auth, "scopes", None)}
    return None


def _auth_from_error(exc: BaseException) -> Optional[dict[str, Any]]:
    """Arcade (Nov 2026) answers an unauthorized execute with HTTP 403 ``tool_authorization_required`` and the
    consent URL in the body, not with a 200 whose ``output.authorization`` is set. Read from a live call."""
    body = getattr(exc, "body", None)
    if isinstance(body, Mapping) and body.get("name") == "tool_authorization_required":
        auth = body.get("authorization") or {}
        if isinstance(auth, Mapping):
            return {"status": auth.get("status"), "url": auth.get("url"), "authorization_id": auth.get("id"),
                    "provider_id": auth.get("provider_id"), "scopes": auth.get("scopes")}
    return None


def _authorization_required(base: dict[str, Any], toolkit: Optional[str], principal: Optional[str], auth: dict[str, Any]) -> str:
    return _dumps({**base, **auth, "status": "authorization_required", "arcade_status": auth.get("status"),
                   "instructions": (f"{base.get('tool')} needs consent for principal {principal} (a new app or more "
                                    f"scopes on {toolkit}). Show this url to the human; if it is missing, call "
                                    f"arcade_authorize with tool={base.get('tool')!r}, not just the toolkit, since another "
                                    "tool on the same toolkit can already be connected. Wait for consent, then call "
                                    "arcade_execute again with the same input. No grant is escalated automatically.")})


class Handlers:
    def __init__(self, runtime: Runtime, governor: Governor) -> None:
        self.runtime = runtime
        self.governor = governor

    # ------------------------------------------------------------------ shared
    def _policy_and_role(self) -> tuple[Optional[Policy], Any, Optional[dict[str, Any]]]:
        try:
            policy = self.runtime.policies.get()
        except PolicyError as exc:
            return None, None, {"denied": True, "reason": f"Arcade policy unavailable: {exc}"}
        ctx = resolve_role(policy)
        if not ctx.ok:
            return policy, ctx, {"denied": True, "reason": ctx.error, "profile": ctx.profile, "hermes_home": ctx.home}
        return policy, ctx, None

    # ------------------------------------------------------------------ arcade_whoami
    def draft_company(self, args: dict, **kwargs: Any) -> str:
        from . import company as co
        from . import found as fd

        spec = args.get("spec") if isinstance(args, Mapping) else None
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except ValueError:
                return _dumps({"error": "spec must be an object (or JSON text of one)"})
        try:
            return _dumps(fd.draft(spec or {}, policy_path=self.runtime.policies.candidates()[0]))
        except co.SpecError as exc:
            return _dumps({"error": f"the spec needs fixing: {exc}"})
        except Exception as exc:
            logger.exception("arcade_draft_company failed")
            return _dumps({"error": f"{type(exc).__name__}: {exc}"})

    def whoami(self, args: dict, **kwargs: Any) -> str:
        try:
            policy, ctx, err = self._policy_and_role()
            if err and policy is None:
                return _dumps(err)
            out: dict[str, Any] = ctx.as_dict()
            out["policy"] = str(policy.source)
            out["api_key_present"] = key_present()
            if not ctx.ok:
                out["denied"] = True
                return _dumps(out)
            row = next((r for r in policy.status_rows() if r["role"] == ctx.role), None)
            out["grants"] = row["grants"] if row else {}
            out["ownership_enforced"] = row["ownership"] if row else {}
            if args.get("check_connections"):
                out["connections"] = self._connections(policy, ctx)
            return _dumps(out)
        except Exception as exc:  # never raise out of a handler
            logger.exception("arcade_whoami failed")
            return _dumps({"error": f"arcade_whoami failed: {type(exc).__name__}: {exc}"})

    def _connections(self, policy: Policy, ctx: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        try:
            client = get_client()
        except ArcadeUnavailable as exc:
            return {"error": str(exc)}
        for toolkit in policy.arcade_toolkits:
            if not policy.grants_for(ctx.role, toolkit):
                continue
            tool = policy.connect.get(toolkit)
            if not tool:
                result[toolkit] = {"status": "unknown", "reason": "no connect tool in policy"}
                continue
            try:
                resp = client.tools.authorize(tool_name=tool, user_id=ctx.principal)
                result[toolkit] = {"status": resp.status, "connected": resp.status == "completed"}
            except Exception as exc:
                result[toolkit] = describe_error(exc)
        return result

    # ------------------------------------------------------------------ arcade_search_tools
    def search_tools(self, args: dict, **kwargs: Any) -> str:
        try:
            query = str(args.get("query") or "").strip().lower()
            wanted = str(args.get("toolkit") or "").strip().lower() or None
            try:
                limit = max(1, min(int(args.get("limit") or 25), 100))
            except (TypeError, ValueError):
                limit = 25
            try:
                policy = self.runtime.policies.get()
            except PolicyError as exc:
                return _dumps({"error": f"Arcade policy unavailable: {exc}"})
            ctx = resolve_role(policy)
            toolkits = [wanted] if wanted else policy.arcade_toolkits
            try:
                client = get_client()
            except ArcadeUnavailable as exc:
                return _dumps({"error": str(exc)})
            found: list[dict[str, Any]] = []
            errors: dict[str, Any] = {}
            for canon in toolkits:
                toolkit_id = policy.arcade_toolkit_id(canon) or canon
                try:
                    page = client.tools.list(toolkit=toolkit_id, limit=100)
                    seen = 0
                    for tool in page:
                        seen += 1
                        if seen > MAX_LIST_PER_TOOLKIT:
                            break
                        name = tool.qualified_name
                        desc = (tool.description or "").strip().split("\n")[0]
                        if query and query not in f"{name} {desc}".lower():
                            continue
                        rules = policy.rules_for_tool(name)
                        rule = policy.classify(name, {})
                        entry: dict[str, Any] = {
                            "name": name, "description": desc[:160], "toolkit": canon,
                            "verb": rule.verb if rule else "denied (no rule)",
                            "verb_depends_on_input": any(r.input for r in rules),
                        }
                        if ctx.ok:
                            entry["allowed_for_role"] = policy.decide(ctx.role, name, {}).allowed
                        found.append(entry)
                except Exception as exc:
                    errors[canon] = describe_error(exc)
            found.sort(key=lambda e: e["name"])
            out: dict[str, Any] = {"count": len(found), "tools": found[:limit], "toolkits": toolkits,
                                   "role": ctx.role, "note": "Verbs come from the policy file; a tool with no rule is denied by default. Nothing was executed."}
            if len(found) > limit:
                out["truncated"] = True
            if errors:
                out["errors"] = errors
            return _dumps(out)
        except Exception as exc:
            logger.exception("arcade_search_tools failed")
            return _dumps({"error": f"arcade_search_tools failed: {type(exc).__name__}: {exc}"})

    # ------------------------------------------------------------------ arcade_authorize
    def authorize(self, args: dict, **kwargs: Any) -> str:
        try:
            policy, ctx, err = self._policy_and_role()
            if err:
                return _dumps(err)
            toolkit = str(args.get("toolkit") or "").strip().lower()
            tool = str(args.get("tool") or "").strip() or policy.connect.get(toolkit)
            if not tool:
                return _dumps({"error": f"no connect tool for toolkit {toolkit!r} in the policy; add one under 'connect:' or pass 'tool'"})
            if self.runtime.in_cron():
                return _dumps({"status": NEEDS_HUMAN, "toolkit": toolkit, "principal": ctx.principal,
                               "instructions": "Connecting an app needs a person in a browser. Run /arcade connect from an interactive session."})
            try:
                client = get_client()
                resp = client.tools.authorize(tool_name=tool, user_id=ctx.principal)
            except ArcadeUnavailable as exc:
                return _dumps({"error": str(exc)})
            except Exception as exc:
                return _dumps(describe_error(exc))
            self.runtime.receipts.append(role=ctx.role, principal=ctx.principal, tool=tool, toolkit=toolkit,
                                         verb="connect", decision="connected" if resp.status == "completed" else "auth_link",
                                         outcome=resp.status)
            out = {"status": resp.status, "toolkit": toolkit, "tool": tool, "principal": ctx.principal,
                   "url": resp.url, "authorization_id": resp.id}
            if resp.status == "completed":
                out["instructions"] = f"{toolkit} is already connected for {ctx.principal}."
            else:
                out["instructions"] = (f"Show this link to the human. It connects {toolkit} for principal {ctx.principal} only "
                                       "(each role connects separately). After consent, retry the original call.")
            return _dumps(out)
        except Exception as exc:
            logger.exception("arcade_authorize failed")
            return _dumps({"error": f"arcade_authorize failed: {type(exc).__name__}: {exc}"})

    # ------------------------------------------------------------------ arcade_execute
    def execute(self, args: dict, **kwargs: Any) -> str:
        try:
            tool = str(args.get("tool") or "").strip()
            raw_input = args.get("input")
            tool_input: Mapping[str, Any] = raw_input if isinstance(raw_input, Mapping) else {}
            work_order = str(args.get("work_order") or "").strip() or None
            if not tool:
                return _dumps({"denied": True, "reason": "arcade_execute needs a non-empty 'tool' name"})
            policy, ctx, err = self._policy_and_role()
            if err:
                return _dumps(err)
            acting = acting_for(policy, ctx, tool, tool_input, work_order, args.get("on_behalf_of"), guard=self.runtime.guard)
            if acting.error:
                return _dumps({"tool": tool, "role": acting.role, "denied": True, "reason": acting.error})
            decision = acting.decision
            base = {"tool": tool, "role": acting.role, "principal": acting.principal, "verb": decision.verb,
                    "toolkit": decision.toolkit, "work_order": work_order}
            if acting.via:
                base["via"] = acting.via
            if acting.handoff:
                return _dumps({**base, "denied": True, "status": HANDOFF, "reason": acting.handoff})
            if not decision.allowed:
                return _dumps({**base, "denied": True, "reason": decision.reason})
            key = Policy.action_key(acting.role, tool, tool_input, work_order)
            had_ticket = self.governor.consume_ticket(key)
            if decision.requires_approval:
                if self.runtime.in_cron():
                    return _dumps({**base, "denied": True, "status": NEEDS_HUMAN,
                                   "reason": "ship actions need a human; this is a cron run"})
                if not had_ticket:
                    return _dumps({**base, "denied": True,
                                   "reason": "ship action reached the handler without passing the approval gate; refusing"})
            try:
                client = get_client()
                resp = client.tools.execute(tool_name=tool, input=dict(tool_input), user_id=acting.principal)
            except ArcadeUnavailable as exc:
                return _dumps({**base, "error": str(exc)})
            except Exception as exc:
                auth = _auth_from_error(exc)
                if auth:
                    return _authorization_required(base, decision.toolkit, acting.principal, auth)
                return _dumps({**base, **describe_error(exc)})
            output = getattr(resp, "output", None)
            auth = _auth_payload(getattr(output, "authorization", None)) if output is not None else None
            if auth:
                return _authorization_required(base, decision.toolkit, acting.principal, auth)
            error = getattr(output, "error", None) if output is not None else None
            if error is not None:
                return _dumps({**base, "error": getattr(error, "message", str(error)), "kind": getattr(error, "kind", None),
                               "can_retry": getattr(error, "can_retry", None), "status": getattr(resp, "status", None)})
            value = getattr(output, "value", None) if output is not None else None
            text = json.dumps(value, default=str)
            truncated = len(text) > MAX_VALUE_CHARS
            out = {**base, "ok": getattr(resp, "success", None) is not False, "status": getattr(resp, "status", None),
                   "execution_id": getattr(resp, "execution_id", None),
                   "url": extract_url(value) if isinstance(value, Mapping) else None,
                   "value": value if not truncated else text[:MAX_VALUE_CHARS] + "...", "truncated": truncated}
            return _dumps(out)
        except Exception as exc:
            logger.exception("arcade_execute failed")
            return _dumps({"error": f"arcade_execute failed: {type(exc).__name__}: {exc}"})
