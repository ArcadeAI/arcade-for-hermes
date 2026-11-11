"""Who a governed call acts as, and when a subagent must hand a ship action back.

Hermes v0.23.0 runs every model-dispatched ``delegate_task`` in the background, and a background
child's approval callback auto-denies with no card (``tools/delegate_tool.py``,
``tools/delegate_tool_config.py``). So a ship action raised inside a routed child can never reach the
founder. Instead of letting it die silently, the plugin blocks it in the child with a HANDOFF
message, and the main session re-issues it with ``on_behalf_of: <role>``. The main session's call
goes through the normal approval gate, the card names both roles, the policy checks the delegated
role's grant, and the call runs as that role's principal.

``on_behalf_of`` is accepted only in the main session and only for ship actions, which always wait
for a human, so it can never widen what runs without approval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .identity import RoleContext
from .policy import Decision, Policy

HANDOFF = "HANDOFF"


@dataclass(frozen=True)
class Acting:
    role: Optional[str]
    principal: Optional[str]
    via: Optional[str]                 # main-session role that re-issued a handed-back action
    decision: Optional[Decision]
    error: Optional[str] = None        # refuse the call with this reason
    handoff: Optional[str] = None      # refuse the call and hand it back with this message

    @property
    def runnable(self) -> bool:
        return self.error is None and self.handoff is None and self.decision is not None and self.decision.allowed


def acting_for(policy: Policy, ctx: RoleContext, tool: str, tool_input: Mapping[str, Any],
               work_order: Optional[str], on_behalf_of: Any = None, guard: Any = None,
               via_tool: str = "arcade_execute") -> Acting:
    """``guard(role)`` returns decide's state kwargs (halted, spent_today) for the role that would act.

    ``via_tool`` is the Hermes tool the call came through. A gateway tool (``mcp__<server>__Arcade_UseTool``)
    has a fixed schema with no ``on_behalf_of``, so a handed-back gateway ship is re-issued as the main
    session's own call: same tool and inputs, decided under the main session's role, and it still waits
    for the founder's card."""
    state = (lambda role: guard(role) if guard else {})
    obo = on_behalf_of.strip() if isinstance(on_behalf_of, str) else ""
    if obo:
        if ctx.routed:
            return Acting(ctx.role, ctx.principal, None, None,
                          error="on_behalf_of is only accepted in the main session, not inside a subagent")
        if obo not in policy.roles:
            return Acting(ctx.role, ctx.principal, None, None, error=f"on_behalf_of: {obo!r} is not a role in the policy")
        decision = policy.decide(obo, tool, tool_input, work_order, **state(obo))
        if decision.allowed and decision.verb != "ship":
            return Acting(obo, policy.principal(obo), ctx.role, decision,
                          error="on_behalf_of is only for ship actions a subagent handed back; "
                                f"run this {decision.verb} call inside the {obo} subagent instead")
        return Acting(obo, policy.principal(obo), ctx.role, decision)
    decision = policy.decide(ctx.role, tool, tool_input, work_order, **state(ctx.role))
    if decision.requires_approval and ctx.routed:
        head = (f"{HANDOFF}: {ctx.role} may ship {tool}, but a subagent cannot reach the founder's approval card. "
                "Nothing ran. Stop here and report this line to the main session, which must call ")
        if via_tool == "arcade_execute":
            retry = {"tool": tool, "input": dict(tool_input), "on_behalf_of": ctx.role}
            if work_order:
                retry["work_order"] = work_order
            return Acting(ctx.role, ctx.principal, None, decision, handoff=(
                f"{head}arcade_execute with exactly: {json.dumps(retry, sort_keys=True)}"))
        retry = {"tool_name": tool, "inputs": dict(tool_input)}
        return Acting(ctx.role, ctx.principal, None, decision, handoff=(
            f"{head}{via_tool} with exactly: {json.dumps(retry, sort_keys=True)} "
            "(it is decided under the main session's role and waits for the founder's card)"))
    return Acting(ctx.role, ctx.principal, None, decision)
