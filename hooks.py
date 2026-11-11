"""The governor: pre_tool_call decides, post_approval_response records who answered, post_tool_call
writes the receipt. One instance per process, shared with the tool handlers for the ship ticket.

Hermes semantics this relies on (read from hermes-agent v0.23.0 source):

- ``pre_tool_call`` may return ``{"action": "block", "message": ...}`` (message required) or
  ``{"action": "approve", "message": ..., "rule_key": ...}``. ``rule_key`` is the grain of a
  "session" or "always" answer; without it Hermes uses the tool name, so every later
  ``arcade_execute`` would be covered. We pass a per-action key.
- An approve directive runs ``tools.approval.request_tool_approval``; a denial, timeout or gate
  error blocks the call. Where no human can answer (cron, ``-q``), the gate fails closed.
- ``post_tool_call`` fires for blocked calls too, with ``status="blocked"`` and the block text in
  ``error_message``; the receipt for a denied call is written there.
- ``post_approval_response`` carries ``pattern_key="plugin_rule:<rule_key>"`` and ``choice`` in
  once, session, always, deny, timeout, cancelled, notify_failed, smart_approve, smart_deny.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Mapping, Optional

from .acting import acting_for
from .identity import RoleContext, resolve_role
from .policy import ACTION_KEY_PREFIX, Policy, PolicyError
from .receipts import extract_url, summarize_input
from .runtime import Runtime

logger = logging.getLogger(__name__)

EXECUTE_TOOL = "arcade_execute"
# Arcade's official gateway (the ArcadeAI/arcade-plugin package, or `hermes mcp add` of
# https://api.arcade.dev/mcp/arcade) reaches every Arcade tool through one meta-tool. Hermes names
# MCP tools mcp__<server>__<tool> and hands pre_tool_call {"tool_name": "Gmail.SendEmail",
# "inputs": {...}, "query_id": ...} (seen live on Hermes 0.23.0, 2026-11-08). Its discovery tools
# (Arcade_ListApps, Arcade_SelectTools) read only and pass through ungoverned.
GATEWAY_EXECUTE = ("Arcade_UseTool", "Arcade_UseToolWithUI")
TICKET_TTL_SECONDS = 15 * 60
PENDING_TTL_SECONDS = 60 * 60
NEEDS_HUMAN = "NEEDS_HUMAN"
_DENIED_CHOICES = {"deny", "timeout", "cancelled", "notify_failed", "smart_deny"}
_NOBODY_CHOICES = {"timeout", "cancelled", "notify_failed"}


def _fingerprint(tool_name: str, args: Any) -> str:
    payload = json.dumps({"t": tool_name, "a": args if isinstance(args, Mapping) else {}},
                         sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def is_gateway_execute(tool_name: str) -> bool:
    """``mcp__<any server>__Arcade_UseTool``: a call into Arcade's gateway, whatever the server is named."""
    if not isinstance(tool_name, str) or not tool_name.startswith("mcp__"):
        return False
    server, sep, tool = tool_name[len("mcp__"):].rpartition("__")
    return bool(server and sep) and tool in GATEWAY_EXECUTE


def is_execute(tool_name: str) -> bool:
    """A call that runs some Arcade tool named in its arguments: ours or the gateway's."""
    return tool_name == EXECUTE_TOOL or is_gateway_execute(tool_name)


def _parse_result(result: Any) -> Any:
    if isinstance(result, (dict, list)):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except (TypeError, ValueError):
            return {"text": result[:200]}
    return {"text": str(result)[:200]}


def _failed(parsed: Any) -> bool:
    """True when a tool result says the call did not succeed (error, denial or a sign-in request)."""
    if not isinstance(parsed, Mapping):
        return False
    return bool(parsed.get("error") or parsed.get("denied") or parsed.get("authorization_required")
                or parsed.get("status") == "authorization_required")


class Governor:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}     # fingerprint -> record
        self._tickets: dict[str, float] = {}              # action key -> issued at
        self._approvals: dict[str, dict[str, Any]] = {}   # action key -> who answered
        self._notes: dict[str, str] = {}                  # call fingerprint -> approval note for the model

    # ------------------------------------------------------------------ helpers
    def target(self, policy: Policy, tool_name: str, args: Any) -> Optional[tuple[str, Mapping[str, Any], Optional[str]]]:
        """``(governed tool, its input, work order)`` or None when this call is none of our business."""
        args = args if isinstance(args, Mapping) else {}
        if is_execute(tool_name):
            name_key, input_key = ("tool", "input") if tool_name == EXECUTE_TOOL else ("tool_name", "inputs")
            tool = args.get(name_key)
            if not isinstance(tool, str) or not tool.strip():
                return ("", {}, None)
            raw_input = args.get(input_key)
            return (tool.strip(), raw_input if isinstance(raw_input, Mapping) else {}, _work_order(args))
        if policy.governs(tool_name):
            return (tool_name, args, _work_order(args))
        return None

    def issue_ticket(self, key: str) -> None:
        with self._lock:
            self._tickets[key] = time.monotonic()

    def consume_ticket(self, key: str) -> bool:
        """True once per issued ticket, within its TTL. The handler calls this for ship actions."""
        with self._lock:
            issued = self._tickets.pop(key, None)
        return issued is not None and (time.monotonic() - issued) <= TICKET_TTL_SECONDS

    def _stash(self, fingerprint: str, record: dict[str, Any]) -> None:
        now = time.monotonic()
        record["_t"] = now
        with self._lock:
            self._pending[fingerprint] = record
            stale = [k for k, v in self._pending.items() if now - v.get("_t", now) > PENDING_TTL_SECONDS]
            for k in stale:
                self._pending.pop(k, None)

    def _pending_like(self, tool_name: str, args: Any) -> Optional[dict[str, Any]]:
        """The pending ship call for the same Arcade tool and input, when Hermes hands this hook its args
        in a different shape than pre_tool_call saw (so the fingerprints differ). Caller holds the lock."""
        try:
            policy = self.runtime.policies.get()
            target = self.target(policy, tool_name, args) if policy else None
        except Exception:
            return None
        if target is None:
            return None
        tool, tool_input, _ = target
        want = json.dumps(dict(tool_input or {}), sort_keys=True, default=str)
        for record in reversed(list(self._pending.values())):
            if record.get("decision") == "pending_approval" and record.get("tool") == tool \
                    and json.dumps(dict(record.get("input") or {}), sort_keys=True, default=str) == want:
                return record
        return None

    def _pop(self, fingerprint: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._pending.pop(fingerprint, None)

    # ------------------------------------------------------------------ the floor's activity feed
    def _activity(self, policy: Optional[Policy], kind: str, **fields: Any) -> None:
        """Best effort and silent: the floor is a view, it must never slow or break an agent."""
        try:
            if policy is None:
                policy = self.runtime.policies.get()
            ctx = resolve_role(policy)
            if not ctx.profile:
                return
            self.runtime.activity.add(kind, ctx.role, ctx.profile, **fields)
        except Exception as exc:
            logger.debug("arcade-for-hermes: activity not recorded: %s", exc)

    def on_api_start(self, model: str = "", **kwargs: Any) -> None:
        self._activity(None, "think", model=model or None)

    def on_api_end(self, **kwargs: Any) -> None:
        self._activity(None, "think_end")

    def on_interim_message(self, text: str = "", **kwargs: Any) -> None:
        if text:
            self._activity(None, "say", text=text)

    # ------------------------------------------------------------------ hooks
    def pre_tool_call(self, tool_name: str = "", args: Any = None, task_id: str = "", session_id: str = "", **kwargs: Any):
        try:
            policy = self.runtime.policies.get()
        except PolicyError as exc:
            if is_execute(tool_name):
                return {"action": "block", "message": f"DENIED: Arcade policy unavailable ({exc}); failing closed"}
            return None  # a broken policy must not take unrelated Hermes tools down
        target = self.target(policy, tool_name, args)
        if target is None:
            self._activity(policy, "tool", tool=tool_name)  # a local Hermes tool: the floor's toolbox
            return None
        tool, tool_input, work_order = target
        fp = _fingerprint(tool_name, args)
        record: dict[str, Any] = {"hermes_tool": tool_name, "tool": tool, "work_order": work_order,
                                  "task_id": task_id or None, "session_id": session_id or None,
                                  "input": tool_input}
        if not tool:
            missing = f"{tool_name} needs a non-empty '{'tool' if tool_name == EXECUTE_TOOL else 'tool_name'}'"
            record.update(decision="denied", reason=missing)
            self._stash(fp, record)
            return {"action": "block", "message": f"DENIED: {missing}"}
        ctx = resolve_role(policy)
        record.update(profile=ctx.profile, role=ctx.role, principal=ctx.principal)
        if not ctx.ok:
            record.update(decision="denied", reason=ctx.error)
            self._stash(fp, record)
            return {"action": "block", "message": f"DENIED: {ctx.error}"}
        obo = args.get("on_behalf_of") if tool_name == EXECUTE_TOOL and isinstance(args, Mapping) else None
        acting = acting_for(policy, ctx, tool, tool_input, work_order, obo, guard=self.runtime.guard,
                            via_tool=tool_name if is_gateway_execute(tool_name) else EXECUTE_TOOL)
        if acting.via:
            record.update(role=acting.role, principal=acting.principal, via=acting.via)
        if acting.error:
            record.update(decision="denied", reason=acting.error)
            self._stash(fp, record)
            return {"action": "block", "message": f"DENIED: {acting.error}"}
        decision = acting.decision
        key = Policy.action_key(acting.role, tool, tool_input, work_order)
        record.update(verb=decision.verb, toolkit=decision.toolkit, rule=decision.rule, reason=decision.reason,
                      action_key=key, amount=decision.amount)
        if acting.handoff:
            record.update(decision="handed_back", reason="ship action inside a subagent; handed back to the main session")
            self._stash(fp, record)
            return {"action": "block", "message": acting.handoff}
        if not decision.allowed:
            record["decision"] = "denied"
            self._stash(fp, record)
            return {"action": "block", "message": f"DENIED: {decision.reason}"}
        if decision.requires_approval:
            if self.runtime.in_cron():
                record.update(decision=NEEDS_HUMAN, reason="ship action in a cron run; no human can approve it")
                self._stash(fp, record)
                return {"action": "block", "message": f"{NEEDS_HUMAN}: {tool} is a ship action and this is a cron run; "
                                                      "run it from a session where the founder can approve"}
            record["decision"] = "pending_approval"
            self._stash(fp, record)
            self.issue_ticket(key)
            try:
                self.runtime.waiting.add(key, tool=tool, toolkit=decision.toolkit, role=acting.role,
                                         profile=ctx.profile, via=acting.via, work_order=work_order,
                                         input=tool_input)
            except Exception as exc:  # the floor is a view; it must never break the gate
                logger.warning("arcade-for-hermes: could not mark the action as waiting: %s", exc)
            summary = json.dumps(summarize_input(tool_input), sort_keys=True)
            if len(summary) > 240:
                summary = summary[:240] + "..."
            wo = f" for {work_order}" if work_order else ""
            via = f" via {acting.via}" if acting.via else ""
            return {"action": "approve", "rule_key": key,
                    "message": f"SHIP: {acting.role} ({acting.principal}){via} wants {tool} on {decision.toolkit}{wo}. Input: {summary}"}
        record["decision"] = "allowed"
        self._stash(fp, record)
        self.issue_ticket(key)
        return None

    def post_approval_response(self, pattern_key: str = "", choice: str = "", surface: str = "",
                               session_key: str = "", decided_by: str = "", **kwargs: Any) -> None:
        prefix = "plugin_rule:" + ACTION_KEY_PREFIX
        if not isinstance(pattern_key, str) or not pattern_key.startswith(prefix):
            return
        key = pattern_key[len("plugin_rule:"):]
        if choice in _NOBODY_CHOICES:
            who = "nobody"            # no person answered; Hermes failed closed
        elif decided_by:
            who = decided_by
        else:
            who = "human" if choice and not choice.startswith("smart_") else ""
        with self._lock:
            self._approvals[key] = {"choice": choice or "", "surface": surface or "", "session_key": session_key or "",
                                    "decided_by": who, "ts": time.time()}

    def post_tool_call(self, tool_name: str = "", args: Any = None, result: Any = None, task_id: str = "",
                       status: Optional[str] = None, error_message: Optional[str] = None, **kwargs: Any) -> None:
        try:
            policy = self.runtime.policies.get()
        except PolicyError:
            policy = None
        if policy is None:
            if not is_execute(tool_name):
                return
            key = "tool" if tool_name == EXECUTE_TOOL else "tool_name"
            target: Optional[tuple] = (str((args or {}).get(key) or ""), {}, _work_order(args))
        else:
            target = self.target(policy, tool_name, args)
        if target is None:
            return
        fp = _fingerprint(tool_name, args)
        record = self._pop(fp)
        if record is None:
            # The pre hook did not see this call (another dispatch path). Record what we can.
            tool, tool_input, work_order = target
            ctx = resolve_role(policy) if policy else RoleContext(None, None, None, None, "no policy")
            record = {"hermes_tool": tool_name, "tool": tool, "work_order": work_order, "input": tool_input,
                      "profile": ctx.profile, "role": ctx.role, "principal": ctx.principal,
                      "decision": "unknown", "reason": "no pre_tool_call record for this call"}
            if policy and ctx.ok:
                d = policy.decide(ctx.role, tool, tool_input, work_order)
                record.update(verb=d.verb, toolkit=d.toolkit, rule=d.rule, reason=d.reason,
                              action_key=Policy.action_key(ctx.role, tool, tool_input, work_order))
        key = record.get("action_key")
        approver = None
        if key and record.get("decision") == "pending_approval":
            try:
                self.runtime.waiting.remove(key)
            except Exception as exc:
                logger.warning("arcade-for-hermes: could not clear the waiting mark: %s", exc)
        if key:
            with self._lock:
                approver = self._approvals.pop(key, None)
            if approver:
                approver.pop("ts", None)
        decision = record.get("decision") or "unknown"
        if status == "blocked":
            if decision == "pending_approval":
                if approver and approver.get("choice") in _DENIED_CHOICES:
                    decision = "denied"
                    record["reason"] = f"approval {approver['choice']}"
                elif error_message and "no interactive user" in str(error_message):
                    decision = NEEDS_HUMAN
                    record["reason"] = "no human present to approve a ship action"
                else:
                    decision = "denied"
                    record["reason"] = (error_message or record.get("reason") or "blocked")[:300]
            elif decision == "handed_back":
                pass
            elif decision in ("allowed",):
                decision = "denied"
                record["reason"] = (error_message or "blocked by another hook")[:300]
            with self._lock:
                self._tickets.pop(key, None) if key else None
        elif decision == "pending_approval":
            decision = "approved"
            if approver is None:
                approver = {"choice": "allowlisted", "surface": "", "session_key": "",
                            "decided_by": "prior session/always answer"}
        parsed = _parse_result(result)
        outcome = "ok"
        if isinstance(parsed, Mapping):
            if parsed.get("status") == "authorization_required" or parsed.get("authorization_required"):
                outcome = "authorization_required"
            elif parsed.get("error") or parsed.get("denied"):
                outcome = "error"
        if status == "blocked":
            outcome = "not_run"
        row = {k: v for k, v in record.items() if not k.startswith("_") and k not in ("task_id", "session_id")}
        # A consent link is a sign-in URL; receipts never store those.
        url = extract_url(parsed) if isinstance(parsed, Mapping) and outcome not in ("authorization_required", "not_run") else None
        row.update(decision=decision, outcome=outcome, approver=approver, url=url,
                   task_id=record.get("task_id") or task_id or None, session_id=record.get("session_id"))
        try:
            self.runtime.receipts.append(**row)
        except Exception as exc:  # a receipt failure must never break the agent loop
            logger.warning("arcade-for-hermes: could not write receipt: %s", exc)
        # The model never sees the card: Hermes asks the person and runs the tool. Tell it what happened,
        # so it does not report "no card appeared" for a send the founder approved.
        # Only on success: a note saying an approved action ran is false when the call then failed.
        if decision == "approved" and approver and outcome == "ok":
            choice = approver.get("choice") or "approved"
            note = (f"[Arcade for Hermes] The founder approved this {record.get('verb') or 'ship'} action on the "
                    f"approval card ({choice}). It ran as {record.get('role') or 'this role'}.")
            with self._lock:
                if self._notes.pop(fp, None) is None:     # "" means the transform already told the model
                    self._notes[fp] = note

    def transform_tool_result(self, tool_name: str = "", args: Any = None, result: Any = None, **kwargs: Any):
        """Append the approval note post_tool_call left for this exact call, if any. Fail-open."""
        try:
            fp = _fingerprint(tool_name, args)
            with self._lock:
                note = self._notes.pop(fp, None)
                # Hermes's agent loop runs this hook before its post_tool_call, so the note above is
                # often not written yet: read the approval straight from the pending call.
                record = self._pending.get(fp) or self._pending_like(tool_name, args) or {}
                approver = self._approvals.get(record.get("action_key") or "")
                if note is None and record.get("decision") == "pending_approval" and approver \
                        and approver.get("choice") not in _DENIED_CHOICES and not _failed(_parse_result(result)):
                    note = (f"[Arcade for Hermes] The founder approved this {record.get('verb') or 'ship'} action "
                            f"on the approval card ({approver.get('choice') or 'approved'}). "
                            f"It ran as {record.get('role') or 'this role'}.")
                    self._notes[fp] = ""   # post_tool_call must not queue a second note for this call
            if note and isinstance(result, str):
                return f"{result}\n\n{note}"
        except Exception as exc:
            logger.debug("arcade-for-hermes: approval note skipped: %s", exc)
        return None


def _work_order(args: Any) -> Optional[str]:
    if isinstance(args, Mapping):
        wo = args.get("work_order")
        if isinstance(wo, str) and wo.strip():
            return wo.strip()
    return None
