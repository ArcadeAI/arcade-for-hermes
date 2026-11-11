"""A routed child is detected by comparing homes, the way Hermes core does; an override alone is not enough."""

from __future__ import annotations

import sys
import types
from pathlib import Path

from arcade_for_hermes.identity import _is_routed


def _fake_constants(monkeypatch, launch: Path):
    mod = types.ModuleType("hermes_constants")
    mod.get_routing_process_hermes_home = lambda: launch
    mod.hermes_home_key = lambda p: str(Path(p).resolve())
    monkeypatch.setitem(sys.modules, "hermes_constants", mod)


def test_main_session_under_an_override_of_the_launch_home_is_not_routed(tmp_path, monkeypatch):
    _fake_constants(monkeypatch, tmp_path)
    assert _is_routed(str(tmp_path)) is False


def test_child_profile_home_is_routed(tmp_path, monkeypatch):
    _fake_constants(monkeypatch, tmp_path)
    assert _is_routed(str(tmp_path / "profiles" / "reporter")) is True


def test_unknown_home_fails_toward_main(monkeypatch):
    assert _is_routed(None) is False
