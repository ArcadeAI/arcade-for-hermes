"""Shared runtime state: where the policy and the receipts live, resolved once per process.

Both belong to the installation that loaded the plugin (the launch profile), not to whichever
profile a routed child happens to run as: the policy is one firm-wide document and ``/arcade audit``
in the main session lists every role's receipts. Settings come from ``plugins.entries.arcade-for-hermes
.settings`` (``policy_path``, ``receipts_path``) captured at register time.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from .policy import Policy, PolicyError
from .activity import ActivityFeed
from .receipts import ReceiptStore, WaitingBoard

logger = logging.getLogger(__name__)

PLUGIN_ID = "arcade-for-hermes"
PLUGIN_DIR = Path(__file__).resolve().parent
BUNDLED_EXAMPLE = PLUGIN_DIR / "policy.example.yaml"


def launch_home() -> Path:
    """The Hermes home of the launching process (never a routed child's override)."""
    try:
        from hermes_constants import get_process_hermes_home

        return Path(get_process_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


class PolicyProvider:
    """Loads the policy from the first path that exists and reloads it when the file changes."""

    def __init__(self, policy_path: str = "") -> None:
        self._configured = policy_path.strip() if policy_path else ""
        self._lock = threading.Lock()
        self._loaded: Optional[Policy] = None
        self._mtime: Optional[float] = None
        self._path: Optional[Path] = None

    def candidates(self) -> list[Path]:
        paths: list[Path] = []
        if self._configured:
            paths.append(Path(os.path.expanduser(self._configured)))
        paths.append(launch_home() / "arcade" / "policy.yaml")
        paths.append(BUNDLED_EXAMPLE)
        return paths

    def path(self) -> Path:
        for candidate in self.candidates():
            if candidate.is_file():
                return candidate
        return self.candidates()[0]

    @property
    def using_example(self) -> bool:
        return self.path() == BUNDLED_EXAMPLE

    def get(self) -> Policy:
        """The current policy; raises PolicyError when it cannot be loaded (callers fail closed)."""
        path = self.path()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            raise PolicyError(f"policy file not found: {path}") from None
        with self._lock:
            if self._loaded is not None and self._path == path and self._mtime == mtime:
                return self._loaded
            policy = Policy.load(path)
            self._loaded, self._path, self._mtime = policy, path, mtime
            return policy

    def error(self) -> Optional[str]:
        try:
            self.get()
            return None
        except PolicyError as exc:
            return str(exc)


class Runtime:
    def __init__(self, policy_path: str = "", receipts_path: str = "",
                 cron_check: Optional[Callable[[], bool]] = None, verifier_host: str = "",
                 verifier_port: Any = "", verifier_public_url: str = "") -> None:
        self.policies = PolicyProvider(policy_path)
        self._receipts_path = receipts_path.strip() if receipts_path else ""
        self._cron_check = cron_check
        self._receipts: Optional[ReceiptStore] = None
        self.verifier_host = (verifier_host or "").strip() or "127.0.0.1"
        try:
            self.verifier_port = int(verifier_port) if str(verifier_port).strip() else 8765
        except (TypeError, ValueError):
            self.verifier_port = 8765
        self.verifier_public_url = (verifier_public_url or "").strip()
        self._verifier = None

    def verifier(self, policy: Policy, client_factory: Callable[[], Any]):
        """The process-wide custom user verifier for Arcade consent flows, created on first use."""
        from .verifier import Verifier

        principals = {role: policy.principal(role) for role in policy.roles}
        if self._verifier is None:
            self._verifier = Verifier(client_factory, principals, host=self.verifier_host, port=self.verifier_port,
                                      public_url=self.verifier_public_url)
        else:
            self._verifier.principals = principals
        return self._verifier

    @property
    def receipts_path(self) -> Path:
        if self._receipts_path:
            return Path(os.path.expanduser(self._receipts_path))
        return launch_home() / "plugin-data" / PLUGIN_ID / "receipts.jsonl"

    @property
    def receipts(self) -> ReceiptStore:
        if self._receipts is None or self._receipts.path != self.receipts_path:
            self._receipts = ReceiptStore(self.receipts_path)
        return self._receipts

    @property
    def halt(self):
        """The founder's kill switch, next to the receipts."""
        from .guard import HaltSwitch
        return HaltSwitch(self.receipts_path.with_name("halt.json"))

    def guard(self, role: Optional[str]) -> dict[str, Any]:
        """What Policy.decide needs beyond the call itself: the halt reason and today's spend for this role."""
        from .guard import spent_today
        try:
            spent = spent_today(self.receipts, role) if role else 0.0
        except Exception:
            spent = float("inf")   # an unreadable tally fails closed: every limited call is over the limit
        return {"halted": self.halt.reason(), "spent_today": spent}

    @property
    def waiting(self) -> WaitingBoard:
        """Ship actions waiting on the founder, next to the receipts (read by the dashboard floor)."""
        path = self.receipts_path.with_name("waiting.json")
        if getattr(self, "_waiting", None) is None or self._waiting.path != path:
            self._waiting = WaitingBoard(path)
        return self._waiting

    @property
    def activity(self) -> ActivityFeed:
        """Who is thinking and which local tools they use, next to the receipts (read by the floor)."""
        path = self.receipts_path.with_name("activity.jsonl")
        if getattr(self, "_activity", None) is None or self._activity.path != path:
            self._activity = ActivityFeed(path)
        return self._activity

    def in_cron(self) -> bool:
        if self._cron_check is None:
            return False
        try:
            return bool(self._cron_check())
        except Exception:
            return False
