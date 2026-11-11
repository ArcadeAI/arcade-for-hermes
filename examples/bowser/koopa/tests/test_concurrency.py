"""A swarm proposing at once: separate processes, each with its own copy of the module, like Hermes
loading the plugin once per profile. Every proposal gets its own ID and the files stay valid."""

from __future__ import annotations

import json
import multiprocessing as mp
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _propose(args):
    state, i = args
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"koopa_copy_{i}", ROOT / "koopa.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    desk = mod.Desk(Path(state), ROOT / "fixtures")
    return [desk.propose("BTC/USD", 500 + i, "BC-2026-002")["proposal_id"] for _ in range(3)]


def test_forty_processes_proposing_at_once_never_share_an_id_or_corrupt_the_book(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("koopa_main", ROOT / "koopa.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    state = tmp_path / "state"
    mod.Desk(state, ROOT / "fixtures").reset()
    with mp.get_context("spawn").Pool(16) as pool:
        ids = [pid for batch in pool.map(_propose, [(str(state), i) for i in range(40)]) for pid in batch]
    assert len(ids) == 120 and len(set(ids)) == 120
    proposals = json.loads((state / "proposals.json").read_text())
    assert len(proposals) == 120
    ledger = [json.loads(line) for line in (state / "ledger.jsonl").read_text().splitlines()]
    assert len(ledger) == 120 and {e["proposal_id"] for e in ledger} == set(ids)
    assert not list(state.glob(".*.tmp"))
    shutil.rmtree(state)
