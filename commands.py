"""The /arcade slash command (and `hermes arcade`): status, audit [work_order], connect [toolkit]."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from . import __version__
from .client import ArcadeUnavailable, describe_error, get_client, key_present
from .hooks import NEEDS_HUMAN
from .identity import resolve_role
from .policy import PolicyError
from .runtime import Runtime

logger = logging.getLogger(__name__)

USAGE = ("Usage: /arcade status | /arcade audit [work_order] | /arcade connect [toolkit] | /arcade verifier [status|start|stop]"
         " | /arcade halt [reason] | /arcade resume | /arcade templates | /arcade found <template|draft> [setting]"
         " | /arcade mode [yolo|founder|roles|strict]\n"
         "status: roles, grants, limits, connection and bypass warnings. audit: receipts, newest first. "
         "connect: sign-in links for every role and toolkit (starts the custom user verifier). verifier: its state. "
         "halt: the kill switch, every draft and ship is denied except exits. resume: turns it off. "
         "templates: starter companies. found: start one (policy, a profile per role, the board). "
         "mode: show or move the dial, from yolo (no cards; receipts, limits, kill switch) to strict.")
_TRUTHY = {"1", "true", "yes", "on"}


def _read_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        cfg = load_config_readonly()
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _cfg(cfg: dict[str, Any], dotted: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


class Commands:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def dispatch(self, raw_args: str = "", **kwargs: Any) -> str:
        parts = (raw_args or "").split()
        verb = parts[0].lower() if parts else "status"
        rest = parts[1:]
        try:
            if verb == "status":
                return self.status()
            if verb == "audit":
                return self.audit(rest[0] if rest else None)
            if verb == "connect":
                return self.connect(rest[0].lower() if rest else None)
            if verb == "verifier":
                return self.verifier(rest[0].lower() if rest else "status")
            if verb == "halt":
                return self.halt(" ".join(rest))
            if verb == "resume":
                return self.resume()
            if verb == "templates":
                return self.templates()
            if verb == "found":
                return self.found(rest)
            if verb == "mode":
                return self.mode(rest[0].lower() if rest else None)
            return USAGE
        except Exception as exc:  # a command must never take the session down
            logger.exception("/arcade %s failed", verb)
            return f"/arcade {verb} failed: {type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------ companies
    def _target(self):
        return self.runtime.policies.candidates()[0]

    def templates(self) -> str:
        from . import found as fd
        from .policy import load_yaml

        lines = ["Starter companies (/arcade found <name> [setting]):"]
        for name, path in fd.templates().items():
            spec = load_yaml(path)
            roles = ", ".join(spec.get("roles") or {})
            lines.append(f"  {name}: {spec.get('name')}. {spec.get('pitch', '')} Roles: {roles}.")
        lines.append("Or describe your own in chat: the agent researches it and drafts a company for you to start.")
        return "\n".join(lines)

    def found(self, rest: list) -> str:
        from . import company as co
        from . import found as fd

        if not rest:
            return "Usage: /arcade found <template|path to a draft> [yolo|founder|roles|strict]\n" + self.templates()
        setting = rest[1].lower() if len(rest) > 1 else None
        if setting and setting not in co.SETTINGS:
            return f"setting must be one of {', '.join(co.SETTINGS)}"
        try:
            plan = fd.found(fd.load_spec(rest[0]), setting, policy_path=self._target())
        except co.SpecError as exc:
            return f"Can't start that company: {exc}"
        lines = [f"{plan['company']} is set up at the {plan['setting']} setting. You play the {plan['lead']}.",
                 *[f"  done: {d}" for d in plan["done"]],
                 *[f"  problem: {p}" for p in plan["problems"]],
                 *[f"  warning: {w}" for w in plan.get("warnings", [])],
                 f"  apps: {', '.join(plan['apps'])}"]
        if plan.get("gateways"):
            lines.append(f"Tools come from Arcade's gateway ({', '.join(plan['gateways'])}); every role uses your one sign-in.")
        else:
            lines.append("Next: /arcade connect gives you one sign-in link per role and app.")
        lines.append(f"Restart the Hermes gateway so the new profiles load. Then `hermes kanban --board {plan['slug']} daemon` starts the work.")
        return "\n".join(lines)

    def mode(self, setting: Optional[str] = None) -> str:
        from . import company as co
        from . import found as fd

        if not setting:
            try:
                current = (self.runtime.policies.get().company or {}).get("setting")
            except Exception:
                current = None
            return (f"Setting: {current or 'none (this policy was not made by /arcade found)'}. "
                    "yolo: every tool, no cards; receipts, money limits and the kill switch still hold. "
                    "founder: every tool, ships wait for your card. roles: each role gets only its apps. "
                    "strict: roles, with every tool pinned by name.")
        if setting not in co.SETTINGS:
            return f"setting must be one of {', '.join(co.SETTINGS)}"
        try:
            out = fd.set_setting(setting, policy_path=self._target())
        except co.SpecError as exc:
            return str(exc)
        self._receipt_setting(setting)
        return f"{out['company']} is now at the {setting} setting. The policy reloads on the next call."

    def _receipt_setting(self, setting: str) -> None:
        try:
            self.runtime.receipts.append(tool="arcade.mode", decision=setting, outcome="ok", reason=f"founder set the dial to {setting}")
        except Exception as exc:
            logger.warning("arcade-for-hermes: could not write the mode receipt: %s", exc)

    # ------------------------------------------------------------------ status
    def status(self) -> str:
        lines = [f"Arcade for Hermes v{__version__}"]
        try:
            made = self.runtime.policies.get().company
        except Exception:
            made = {}
        if made:
            lines.append(f"Company: {made.get('name')} at the {made.get('setting')} setting (/arcade mode to move the dial)")
        policies = self.runtime.policies
        err = policies.error()
        if err:
            lines.append(f"Policy: ERROR {err} (every governed call is denied until this is fixed)")
            return "\n".join(lines)
        policy = policies.get()
        note = " (bundled example; copy it to <HERMES_HOME>/arcade/policy.yaml and edit)" if policies.using_example else ""
        lines.append(f"Policy: {policies.path()}{note}")
        ctx = resolve_role(policy)
        if ctx.ok:
            lines.append(f"This session: profile {ctx.profile} -> role {ctx.role} -> Arcade principal {ctx.principal}")
        else:
            lines.append(f"This session: NO ROLE ({ctx.error})")
        lines.append(f"ARCADE_API_KEY: {'present' if key_present() else 'MISSING'} for this profile (value never shown)")
        if policy.shared_principal:
            lines.append(f"WARNING: shared_principal is set: every role acts as {policy.shared_principal}. The policy and receipts "
                         "still separate roles, but Arcade sees one user. Remove it for per-role principals (needs your own OAuth apps).")
        lines.append("")
        halted = self.runtime.halt.state()
        if halted:
            lines.append(f"HALTED since {halted.get('ts') or '?'}: {halted.get('reason')}. Every draft and ship is denied "
                         "except exits. /arcade resume turns it off.")
        else:
            lines.append("Kill switch: off. /arcade halt [reason] stops every draft and ship except exits.")
        lines.append("")
        lines.append("Grants (role: toolkit = verbs; ownership of drafted artifacts is enforced only where a grant declares owns):")
        for row in policy.status_rows():
            cells = []
            for toolkit, verbs in row["grants"].items():
                own = " [owns]" if row["ownership"].get(toolkit) else ""
                cells.append(f"{toolkit} = {' + '.join(verbs)}{own}")
            limits = policy.roles[row["role"]].limits or {}
            cap = ""
            if limits:
                spent = self.runtime.guard(row["role"])["spent_today"]
                cap = " | limits " + ", ".join(f"{k.replace('_', ' ')} {v:,.2f}" for k, v in limits.items()) + f", spent today {spent:,.2f}"
            lines.append(f"  {row['role']} ({row['principal']}): " + ("; ".join(cells) if cells else "no grants") + cap)
        lines.append("")
        cfg = _read_config()
        backend = _cfg(cfg, "delegation.backend", "default")
        if backend == "profile_routes":
            profiles = [p.get("name") for p in (_cfg(cfg, "delegation.backends.profile_routes.profiles", []) or []) if isinstance(p, dict)]
            lines.append(f"Delegation: profile_routes (subagents run as their own profile and role): {', '.join(p for p in profiles if p) or 'no profiles listed'}")
        else:
            lines.append(f"Delegation: backend '{backend}'. Subagents run as THIS session's role. For one role per subagent, install "
                         "the advanced-delegation plugin and set delegation.backend: profile_routes.")
        warnings = []
        if str(_cfg(cfg, "delegation.subagent_auto_approve", False)).lower() in _TRUTHY:
            warnings.append("delegation.subagent_auto_approve is true: ship actions inside subagents are approved with no human. Set it to false.")
        if str(_cfg(cfg, "approvals.mode", "")).lower() == "off":
            warnings.append("approvals.mode is off: the approval gate is bypassed, ship actions run unasked.")
        if str(os.environ.get("HERMES_YOLO_MODE", "")).lower() in _TRUTHY:
            warnings.append("HERMES_YOLO_MODE is set (--yolo): approvals are bypassed for this process.")
        if warnings:
            lines.append("Approval bypasses ON (this plugin never sets these; turn them off before trusting the gate):")
            lines.extend(f"  WARNING: {w}" for w in warnings)
        else:
            lines.append("Approval bypasses: none detected in config or process env. (A /yolo toggle inside a gateway session is not visible to plugins.)")
        lines.append("Note: in the classic `hermes chat` CLI, approvals raised inside a delegated child are auto-denied without a card; "
                     "use `hermes --tui` or a messaging gateway for cards from routed children, or ship from the main session.")
        lines.append("")
        try:
            count = len(self.runtime.receipts.read(limit=100000))
        except Exception:
            count = 0
        lines.append(f"Receipts: {self.runtime.receipts_path} ({count} rows). /arcade audit [work_order] lists them.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ kill switch
    def halt(self, reason: str = "") -> str:
        state = self.runtime.halt.halt(reason or "halted by the founder")
        try:
            self.runtime.receipts.append(tool="arcade.halt", decision="halt", outcome="ok", reason=state["reason"])
        except Exception as exc:
            logger.warning("arcade-for-hermes: could not write the halt receipt: %s", exc)
        return (f"HALTED: {state['reason']}. Every draft and ship action is denied until /arcade resume. "
                "Reads still work, and exits (rules marked exit) still go to your card.")

    def resume(self) -> str:
        was_on = self.runtime.halt.resume()
        try:
            self.runtime.receipts.append(tool="arcade.resume", decision="resume", outcome="ok" if was_on else "noop")
        except Exception as exc:
            logger.warning("arcade-for-hermes: could not write the resume receipt: %s", exc)
        return "Resumed: the policy decides again." if was_on else "Not halted; nothing to resume."

    # ------------------------------------------------------------------ audit
    def audit(self, work_order: Optional[str] = None) -> str:
        # A swarm writes many receipts per work order; show the whole order, cap the global view.
        rows = self.runtime.receipts.read(work_order=work_order, limit=500 if work_order else 50)
        title = f"Receipts for {work_order}" if work_order else "Receipts (newest first, last 50)"
        if not rows:
            return f"{title}: none yet. File: {self.runtime.receipts_path}"
        lines = [title, "ts | role | verb | tool | decision | outcome | approver | work order | url"]
        for r in rows:
            approver = r.get("approver") or {}
            who = approver.get("choice") or ""
            if approver.get("surface"):
                who = f"{who}@{approver['surface']}"
            role = r.get("role", "?")
            profile = r.get("profile")
            if profile and profile not in (role, "default") and not r.get("via"):
                role += f" ({profile})"          # which agent of the swarm, when many share a role
            role += f" via {r['via']}" if r.get("via") else ""
            lines.append(" | ".join(str(x) for x in (
                r.get("ts", ""), role, r.get("verb", "?"), r.get("tool", "?"), r.get("decision", "?"),
                r.get("outcome") or "-", who or "-", r.get("work_order") or "-", r.get("url") or "-")))
            if r.get("decision") in ("denied", NEEDS_HUMAN, "handed_back") and r.get("reason"):
                lines.append(f"    reason: {r['reason']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ connect
    def connect(self, toolkit: Optional[str] = None) -> str:
        try:
            policy = self.runtime.policies.get()
        except PolicyError as exc:
            return f"Policy unavailable: {exc}"
        if self.runtime.in_cron():
            return f"{NEEDS_HUMAN}: connecting apps needs a person in a browser; run /arcade connect from an interactive session."
        toolkits = [toolkit] if toolkit else policy.arcade_toolkits
        unknown = [t for t in toolkits if t not in policy.arcade_toolkits]
        if unknown:
            return f"Unknown toolkit(s) {unknown}; the policy declares {policy.arcade_toolkits}"
        try:
            client = get_client()
        except ArcadeUnavailable as exc:
            return str(exc)
        if policy.shared_principal:
            lines = [f"Connect {policy.shared_principal} (shared_principal: one browser consent per app, all roles use it):"]
        else:
            lines = ["Connect each role's Arcade principal (one browser consent per role per app):"]
            verifier = self.runtime.verifier(policy, get_client)
            try:
                vurl = verifier.start()
                lines.append(f"Custom user verifier running at {vurl} for {verifier.seconds_left() // 60} min. If the Arcade project is set to "
                             "'Custom user verifier', that URL must be its verifier URL (app.arcade.dev, Settings, User verification) and the "
                             "browser must reach it; when Hermes runs elsewhere, run scripts/arcade_verifier.py on the laptop instead.")
            except OSError as exc:
                lines.append(f"Custom user verifier not started ({exc}); if the project needs one, run scripts/arcade_verifier.py.")
        links = 0
        seen: set[tuple[str, str]] = set()
        for role in policy.roles:
            for tk in toolkits:
                if not policy.grants_for(role, tk):
                    continue
                tool = policy.connect.get(tk)
                principal = policy.principal(role)
                if (principal, tk) in seen:
                    continue
                seen.add((principal, tk))
                if not tool:
                    lines.append(f"  {role} / {tk}: no connect tool in policy (add it under connect:)")
                    continue
                try:
                    resp = client.tools.authorize(tool_name=tool, user_id=principal)
                except Exception as exc:
                    lines.append(f"  {role} / {tk}: ERROR {describe_error(exc)['error']}")
                    continue
                if resp.status == "completed":
                    lines.append(f"  {role} / {tk}: connected ({principal})")
                else:
                    links += 1
                    lines.append(f"  {role} / {tk}: {resp.status}, open as {principal}: {resp.url}")
                self.runtime.receipts.append(role=role, principal=principal, tool=tool, toolkit=tk, verb="connect",
                                             decision="connected" if resp.status == "completed" else "auth_link",
                                             outcome=resp.status)
        lines.append(f"{links} link(s) to open. Re-run /arcade connect after consenting; it is safe to repeat.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ verifier
    def verifier(self, action: str = "status") -> str:
        try:
            policy = self.runtime.policies.get()
        except PolicyError as exc:
            return f"Policy unavailable: {exc}"
        verifier = self.runtime.verifier(policy, get_client)
        if action == "stop":
            verifier.stop()
            return "Verifier stopped."
        if action == "start":
            try:
                return f"Verifier running at {verifier.start()} for {verifier.seconds_left() // 60} min."
            except OSError as exc:
                return f"Verifier could not start: {exc}"
        state = f"running at {verifier.url}, {verifier.seconds_left()}s left" if verifier.running else "not running (/arcade connect or /arcade verifier start)"
        done = ", ".join(c["user_id"] for c in verifier.confirmations) or "none"
        errs = "; ".join(verifier.errors[-3:]) or "none"
        return f"Verifier: {state}. Confirmed: {done}. Errors: {errs}."
