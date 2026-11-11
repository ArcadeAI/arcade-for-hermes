"""The floor's simulation, run headless in node: every trip a receipt starts also finishes."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_every_trip_finishes_home_and_a_koopa_fill_rains_coins(tmp_path):
    def r(i, **kw):
        base = {"id": str(i), "ts": f"2026-11-08T06:{i:02d}:00Z", "profile": "default", "role": "cos", "outcome": "ok"}
        return {**base, **kw}
    rows = [
        r(1, decision="approved", tool="koopa_execute", toolkit="koopa", action_key="k1",
          approver={"choice": "once", "decided_by": "human"}),
        r(2, decision="denied", tool="Github.UpdateIssue", toolkit="github", action_key="k2", via="cos", role="reporter",
          approver={"choice": "timeout", "decided_by": "nobody"}, outcome="not_run"),
        r(3, decision="denied", tool="GoogleDocs.InsertText", toolkit="googledocs", profile="skeptic-01", role="skeptic",
          reason="skeptics comment, they don't rewrite", outcome="not_run"),
        r(4, decision="handed_back", tool="Github.UpdateIssue", toolkit="github", profile="reporter-01", role="reporter"),
    ]
    receipts = tmp_path / "receipts.jsonl"
    receipts.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    out = subprocess.run([NODE, str(ROOT / "tests/floor/sim.js"), str(ROOT / "dashboard/dist/index.js"), str(receipts)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])
    assert report["idle"] is True and report["coins"] > 0 and report["agents"] == 5
    assert report["toolbox"] and report["thought"] and report["thoughtCleared"] and report["act"] == 3


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_the_terminal_floor_renders_a_frame_with_crisp_text(tmp_path):
    """dashboard/floor_term.js (the Rex/terminal build) draws the same floor as half-block cells (--cells half)."""
    data = tmp_path / "plugin-data" / "arcade-for-hermes"
    data.mkdir(parents=True)
    (data / "receipts.jsonl").write_text(json.dumps({
        "id": "1", "ts": "2026-11-08T06:13:00Z", "profile": "skeptic-01", "role": "skeptic", "tool": "Github.UpdateIssue",
        "toolkit": "github", "decision": "denied", "outcome": "not_run", "work_order": "BC-T",
        "reason": "skeptic has no ship grant on github", "principal": "someone@example.com"}) + "\n")
    snap = tmp_path / "frame.html"
    out = subprocess.run([NODE, str(ROOT / "dashboard/floor_term.js"), "--replay", "BC-T", "--size", "160x48", "--cells", "half",
                          "--snapshot", str(snap), "--after", "3"],
                         capture_output=True, text=True, timeout=60, env={"HERMES_HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    html = snap.read_text()
    text = re.sub(r"<[^>]+>", "", html)
    assert "FOUNDER" in text and "SKEPTIC HAS NO SHIP GRANT" in text and "▀" in text
    assert "someone@example.com" not in html


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_octant_cells_are_the_default_and_use_only_block_glyphs(tmp_path):
    data = tmp_path / "plugin-data" / "arcade-for-hermes"
    data.mkdir(parents=True)
    (data / "receipts.jsonl").write_text(json.dumps({"id": "1", "ts": "2026-11-08T06:13:00Z", "profile": "default", "role": "cos",
                                                     "tool": "Github.GetIssue", "toolkit": "github", "decision": "allowed"}) + "\n")
    snap = tmp_path / "frame.html"
    out = subprocess.run([NODE, str(ROOT / "dashboard/floor_term.js"), "--size", "132x68", "--snapshot", str(snap), "--after", "1"],
                         capture_output=True, text=True, timeout=60, env={"HERMES_HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    text = re.sub(r"<[^>]+>", "", snap.read_text())
    assert any(0x1CD00 <= ord(c) <= 0x1CDE5 for c in text), "no octant glyphs"
    assert "FOUNDER" in text and "TOOLS" in text


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_thought_clouds_never_overlap_and_speakers_get_one():
    out = subprocess.run([NODE, str(ROOT / "tests/floor/clouds.js"), str(ROOT / "dashboard/dist/index.js")],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    r = {}
    for line in out.stdout.strip().splitlines():
        r.update(json.loads(line))
    assert r["overlaps"] == 0 and r["speakersShown"] == r["speakers"]
    assert r["jitterMoves"] <= 2, "a cloud with unchanged text moved between frames"
