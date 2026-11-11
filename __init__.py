"""Arcade for Hermes: one Arcade principal per agent role, a look/draft/ship policy enforced in
pre_tool_call, Hermes's native approval gate for ship actions, and a receipt for every call.

Registration only. Nothing here opens a socket: the Arcade client is built on the first tool call
(``hermes plugins doctor`` blocks sockets while ``register`` runs) and the API key is read through
``agent.secret_scope`` when a tool actually needs it.
"""

from __future__ import annotations

import logging
from pathlib import Path

__version__ = "0.1.0"

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent


# Not "arcade": Hermes aliases an MCP server's name to its toolset (mcp-<name>), and Arcade's own
# gateway is installed as the MCP server "arcade". Sharing the name hid the gateway's tools.
TOOLSET = "arcade-for-hermes"


def register(ctx) -> None:
    from . import schemas
    from .commands import Commands
    from .hooks import Governor
    from .runtime import Runtime
    from .handlers import Handlers

    def _in_cron() -> bool:
        try:
            return ctx.current_cron_execution() is not None
        except Exception:
            return False

    def _setting(key: str) -> str:
        try:
            value = ctx.get_config(key, default="")
        except Exception:
            value = ""
        return str(value or "")

    runtime = Runtime(policy_path=_setting("policy_path"), receipts_path=_setting("receipts_path"), cron_check=_in_cron,
                      verifier_host=_setting("verifier_host"), verifier_port=_setting("verifier_port"),
                      verifier_public_url=_setting("verifier_public_url"))
    governor = Governor(runtime)
    handlers = Handlers(runtime, governor)
    commands = Commands(runtime)

    # These three call Arcade with this profile's ARCADE_API_KEY. Without a key they would only fail and
    # tempt the model away from Arcade's gateway (mcp__<server>__Arcade_UseTool), which the hooks govern
    # the same way, so they hide until a key is set.
    from .client import key_present as keyed

    ctx.register_tool(name="arcade_search_tools", toolset=TOOLSET, check_fn=keyed, schema=schemas.ARCADE_SEARCH_TOOLS,
                      handler=handlers.search_tools, description="Find Arcade tools and the verb the policy gives them", emoji="🕹")
    ctx.register_tool(name="arcade_authorize", toolset=TOOLSET, check_fn=keyed, schema=schemas.ARCADE_AUTHORIZE,
                      handler=handlers.authorize, description="Sign-in link for this role's Arcade principal", emoji="🔑")
    ctx.register_tool(name="arcade_execute", toolset=TOOLSET, check_fn=keyed, schema=schemas.ARCADE_EXECUTE,
                      handler=handlers.execute, description="Run an Arcade tool as this role, under the policy", emoji="🕹")
    ctx.register_tool(name="arcade_whoami", toolset=TOOLSET, schema=schemas.ARCADE_WHOAMI,
                      handler=handlers.whoami, description="This agent's role, principal and grants", emoji="🪪")

    ctx.register_tool(name="arcade_draft_company", toolset=TOOLSET, schema=schemas.ARCADE_DRAFT_COMPANY,
                      handler=handlers.draft_company, description="Draft a company spec for the founder to start", emoji="🏗")

    ctx.register_hook("pre_tool_call", governor.pre_tool_call)
    ctx.register_hook("post_tool_call", governor.post_tool_call)
    ctx.register_hook("post_approval_response", governor.post_approval_response)
    ctx.register_hook("transform_tool_result", governor.transform_tool_result)
    # the floor's thought bubbles: observers only, they return nothing and swallow their errors
    ctx.register_hook("pre_api_request", governor.on_api_start)
    ctx.register_hook("post_api_request", governor.on_api_end)
    ctx.register_hook("api_request_error", governor.on_api_end)
    ctx.register_hook("on_interim_message", governor.on_interim_message)

    ctx.register_command("arcade", commands.dispatch,
                         description="Arcade for Hermes: found a company, move the dial, status, audit, connect, halt",
                         args_hint="templates|found|mode|status|audit|connect|halt|resume")

    for skill in ("arcade", "found-a-company"):
        skill_md = _PLUGIN_DIR / "skills" / skill / "SKILL.md"
        if skill_md.exists() and hasattr(ctx, "register_skill"):
            try:
                ctx.register_skill(skill, skill_md)
            except Exception as exc:  # an older core without plugin skills still gets the tools
                logger.debug("arcade-for-hermes: skill %s not registered: %s", skill, exc)

    def _cli_setup(subparser) -> None:
        subs = subparser.add_subparsers(dest="arcade_command")
        subs.add_parser("status", help="Roles, grants, connection state and approval-bypass warnings")
        audit = subs.add_parser("audit", help="Receipts, newest first")
        audit.add_argument("work_order", nargs="?", default=None)
        connect = subs.add_parser("connect", help="Sign-in links for every role and toolkit")
        connect.add_argument("toolkit", nargs="?", default=None)
        halt = subs.add_parser("halt", help="Kill switch: deny every draft and ship except exits")
        halt.add_argument("reason", nargs="*", default=[])
        subs.add_parser("resume", help="Turn the kill switch off")
        subs.add_parser("templates", help="Starter companies")
        found = subs.add_parser("found", help="Start a company from a template or a draft: policy, profiles, board")
        found.add_argument("source")
        found.add_argument("setting", nargs="?", default=None, choices=["yolo", "founder", "roles", "strict"])
        mode = subs.add_parser("mode", help="Show or move the dial: yolo, founder, roles, strict")
        mode.add_argument("setting", nargs="?", default=None)
        subparser.set_defaults(func=_cli_handle)

    def _cli_handle(args) -> None:
        sub = getattr(args, "arcade_command", None) or "status"
        extra = (getattr(args, "work_order", None) or getattr(args, "toolkit", None)
                 or " ".join(x for x in (getattr(args, "source", None), getattr(args, "setting", None)) if x)
                 or " ".join(getattr(args, "reason", None) or []))
        print(commands.dispatch(f"{sub} {extra}".strip()))

    try:
        ctx.register_cli_command(name="arcade", help="Arcade for Hermes: templates, found, mode, status, audit, connect, halt, resume",
                                 setup_fn=_cli_setup, handler_fn=_cli_handle)
    except Exception as exc:
        logger.debug("arcade-for-hermes: CLI command not registered: %s", exc)
