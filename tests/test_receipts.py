"""Offline tests for receipts: one JSON line per call, never a token or a document body."""

from __future__ import annotations

import json
import sys
from pathlib import Path



from arcade_for_hermes.receipts import ReceiptStore, extract_url, summarize_input


def test_append_and_read_newest_first(tmp_path):
    store = ReceiptStore(tmp_path / "receipts.jsonl")
    store.append(role="cio", principal="bowser/cio", tool="Github.ListIssues", verb="look",
                 decision="allowed", work_order="BC-2026-001")
    store.append(role="skeptic", principal="bowser/skeptic", tool="GoogleDocs.InsertTextAtEndOfDocument",
                 verb="draft", decision="denied", reason="skeptics comment, they don't rewrite",
                 work_order="BC-2026-001")
    store.append(role="cos", principal="bowser/cos", tool="koopa_execute", verb="ship",
                 decision="approved", approver={"surface": "tui", "choice": "once"}, work_order="BC-2026-002")
    rows = store.read()
    assert [r["decision"] for r in rows] == ["approved", "denied", "allowed"]
    filtered = store.read(work_order="BC-2026-001")
    assert len(filtered) == 2 and all(r["work_order"] == "BC-2026-001" for r in filtered)
    lines = (tmp_path / "receipts.jsonl").read_text().splitlines()
    assert len(lines) == 3
    first = json.loads(lines[0])
    assert first["ts"] and first["id"] and first["role"] == "cio"


def test_receipts_never_store_secrets_or_bodies(tmp_path):
    store = ReceiptStore(tmp_path / "r.jsonl")
    store.append(role="cio", principal="p", tool="GoogleDocs.CreateDocumentFromText", verb="draft",
                 decision="allowed", input={"title": "Thesis", "text_content": "x" * 5000,
                                            "authorization": "Bearer abcdef", "api_key": "sk-123"})
    row = store.read()[0]
    summary = json.dumps(row["input"])
    assert "x" * 200 not in summary
    assert "sk-123" not in summary and "abcdef" not in summary
    assert row["input"]["title"] == "Thesis"


def test_summarize_input_truncates_and_redacts():
    s = summarize_input({"a": "b" * 300, "token": "secret", "nested": {"password": "p", "n": 1}, "list": list(range(50))})
    assert len(s["a"]) <= 83 and s["a"].endswith("...")
    assert s["token"] == "[redacted]"
    assert s["nested"]["password"] == "[redacted]" and s["nested"]["n"] == 1
    assert s["list"].endswith("items]") or isinstance(s["list"], str)


def test_extract_url_finds_common_keys():
    assert extract_url({"html_url": "https://github.com/x/y/issues/1"}) == "https://github.com/x/y/issues/1"
    assert extract_url({"data": {"documentUrl": "https://docs.google.com/document/d/1"}}) == "https://docs.google.com/document/d/1"
    assert extract_url({"document": {"url": "https://docs.google.com/document/d/2"}}) == "https://docs.google.com/document/d/2"
    assert extract_url({"nothing": 1}) is None
    assert extract_url("not a dict") is None


def test_missing_file_reads_empty(tmp_path):
    assert ReceiptStore(tmp_path / "none.jsonl").read() == []


def test_corrupt_line_is_skipped(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text('{"id": "1", "ts": "2026-01-01T00:00:00Z", "decision": "allowed"}\nnot json\n')
    rows = ReceiptStore(p).read()
    assert len(rows) == 1


def test_the_waiting_board_drops_stale_entries(tmp_path):
    from arcade_for_hermes.receipts import WaitingBoard

    board = WaitingBoard(tmp_path / "waiting.json", max_age=0.0)
    board.add("k1", tool="koopa_execute")
    assert board.read() == []  # older than max_age the moment it lands: a dead gateway leaves no ghost
