"""The activity feed scrubs what an agent says before a thought cloud can show it, and stays small."""

from __future__ import annotations

from arcade_for_hermes import activity as act
from arcade_for_hermes.activity import ActivityFeed, read_activity, scrub


def test_scrub_keeps_intent_and_drops_links_addresses_numbers_and_tokens():
    s = scrub("Emailing **ops@brisedemer.io** the link https://docs.google.com/d/abc now, call +1 (415) 555-0100, key " + "sk_" + "live_" + "x" * 24)
    assert "brisedemer" not in s and "docs.google" not in s and "555" not in s and "sk_live" not in s
    assert s.startswith("Emailing [address] the link [link] now")
    assert scrub("Checking the book. Then a long list follows: 1, 2, 3.") == "Checking the book."
    assert len(scrub("word " * 100)) <= act.MAX_TEXT


def test_the_feed_is_trimmed_without_renumbering(tmp_path, monkeypatch):
    monkeypatch.setattr(act, "MAX_BYTES", 2_000)
    monkeypatch.setattr(act, "KEEP_LINES", 5)
    feed = ActivityFeed(tmp_path / "activity.jsonl")
    for i in range(60):
        feed.add("say", "cos", "default", text=f"line {i}")
    rows = read_activity(feed.path)
    assert len(rows) < 60 and rows[-1]["text"] == "line 59"
    ns = [r["n"] for r in rows]
    assert ns == sorted(ns) and len(set(ns)) == len(ns)
    assert read_activity(feed.path, after=ns[-1]) == []
