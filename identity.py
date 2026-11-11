"""Who is calling: the Hermes profile, the role it plays, and the Arcade principal.

The role comes from the running Hermes profile, derived from ``hermes_constants.get_hermes_home()``.
Inside a routed ``delegate_task`` child (advanced-delegation, ``profile_routes``) that home is the
child profile's, so a child reads its own role. When the profile cannot be determined, or the policy
does not map it to a role, the result carries an error and every caller fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .policy import Policy


@dataclass(frozen=True)
class RoleContext:
    profile: Optional[str]
    role: Optional[str]
    principal: Optional[str]
    home: Optional[str]
    error: Optional[str] = None
    routed: bool = False          # running inside a delegated child under another profile's home

    @property
    def ok(self) -> bool:
        return self.role is not None and self.principal is not None and self.error is None

    def as_dict(self) -> dict:
        return {"profile": self.profile, "role": self.role, "principal": self.principal,
                "hermes_home": self.home, "error": self.error, "subagent": self.routed}


def current_profile() -> tuple[Optional[str], Optional[str]]:
    """``(profile_name, hermes_home)`` for the active context, or ``(None, home)`` when unknown."""
    try:
        from hermes_constants import get_hermes_home, profile_name_for_home
    except ImportError:
        return None, None
    try:
        home = get_hermes_home()
    except Exception:
        return None, None
    try:
        return profile_name_for_home(home), str(home)
    except Exception:
        return None, str(home)


def _is_routed(home: Optional[str]) -> bool:
    """True inside a routed child: the active home is not the launching process's home.

    The same test core uses in ``delegated_profile_scope``. A context-local override alone is not
    enough: the TUI and gateway run the main session under an override of the launch home too.
    """
    if not home:
        return False
    try:
        from hermes_constants import get_routing_process_hermes_home, hermes_home_key
        return hermes_home_key(home) != hermes_home_key(get_routing_process_hermes_home())
    except Exception:
        return False


def resolve_role(policy: Policy) -> RoleContext:
    profile, home = current_profile()
    if not profile:
        return RoleContext(profile, None, None, home,
                           f"cannot determine the Hermes profile for home {home!r}; failing closed")
    role = policy.role_for_profile(profile)
    if role is None:
        return RoleContext(profile, None, None, home,
                           f"profile {profile!r} is not mapped to a role in the policy (profile_roles); failing closed")
    return RoleContext(profile, role, policy.principal(role), home, routed=_is_routed(home))
