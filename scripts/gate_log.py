"""The gate, live: one line per governed Arcade call, as it lands in the receipts.

    HERMES_HOME=~/arcade-studio/coo python scripts/gate_log.py [--board SLUG]

Shows who acted, the tool, its verb (look / draft / ship) and what the gate said: allowed, waiting for
you, approved, denied, over a cap, halted. With --board it first prints the company's board, one line
per task. Reads only the receipts file; prints no inputs beyond a short subject, recipient or symbol.
"""

from __future__ import annotations

import json
import re
import shutil
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
RECEIPTS = HOME / "plugin-data" / "arcade-for-hermes" / "receipts.jsonl"
COLOR = sys.stdout.isatty()
C = {"g": "32", "y": "33", "r": "31", "c": "36", "d": "2", "b": "1"}
SHOW = ("notional", "amount", "symbol", "recipient", "subject", "title", "repo", "query")


def paint(text: str, code: str) -> str:
    return f"\033[{C[code]}m{text}\033[0m" if COLOR else text


def outcome(r: dict) -> tuple[str, str]:
    d, o = r.get("decision"), r.get("outcome")
    if d == "approved":
        return ("APPROVED by you" + (" (once)" if (r.get("approver") or {}).get("choice") == "once" else ""), "g")
    if d == "denied":
        reason = str(r.get("reason") or "")
        if (r.get("approver") or {}).get("choice") in ("deny", None) and r.get("approver"):
            return ("DENIED by you", "r")
        if "halt" in reason:
            return ("HALTED", "r")
        if "limit" in reason or "cap" in reason:
            return ("OVER CAP", "r")
        return ("DENIED", "r")
    if d == "handed_back":
        return ("HANDED BACK to the lead", "y")
    if d == "allowed":
        return ("ran" if o in ("ok", None) else f"ran ({o})", "c" if r.get("verb") == "look" else "g")
    return (str(d or "?"), "d")


def fit(text: str, width: int) -> str:
    """Cut a painted line to the pane's width, counting only visible characters."""
    out, seen = [], 0
    for tok in re.split(r"(\033\[[0-9;]*m)", text):
        if tok.startswith("\033["):
            out.append(tok)
            continue
        room = width - 1 - seen
        if room <= 0:
            break
        out.append(tok[:room])
        seen += len(tok[:room])
    return "".join(out) + ("\033[0m" if COLOR else "")


def line(r: dict) -> str:
    ts = str(r.get("ts", ""))[11:16]
    if str(r.get("tool") or "").startswith("arcade."):     # the founder's own switches: halt, resume, mode
        what = str(r.get("tool"))[len("arcade."):].upper()
        return f"{paint(ts, 'd')} {'founder':<15} {paint(what, 'r' if what == 'HALT' else 'y')}  " + paint(str(r.get("reason") or ""), "d")
    role = str(r.get("role") or "?")
    verb = str(r.get("verb") or "?")
    tool = str(r.get("tool") or "?")
    said, code = outcome(r)
    inp = r.get("input") if isinstance(r.get("input"), dict) else {}
    bits = [f"{k}={str(inp[k])[:18]}" for k in SHOW if k in inp][:2]
    if len(tool) > 30:
        tool = tool[:29] + "~"
    out = f"{paint(ts, 'd')} {role[:14]:<14} {verb.upper():<5} {tool:<30} {paint(said, code)}"
    if r.get("outcome") == "error" and r.get("decision") == "approved":
        out += paint(" (tool error)", "y")
    if bits:
        out += paint("  " + " ".join(bits), "d")
    if r.get("decision") == "denied" and r.get("reason") and not r.get("approver"):
        out += "\n" + " " * 6 + paint(str(r["reason"]).replace(" (halted by the founder)", "")[:90], "d")
    return out


def board(slug: str) -> None:
    hermes = os.environ.get("HERMES_BIN", "hermes")
    try:
        text = subprocess.run([hermes, "kanban", "--board", slug, "list"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return
    rows = [l for l in text.splitlines() if l.strip()[:1] in ("✓", "⊘", "▶", "○", "●", "…", "◌") or " t_" in l]
    if rows:
        print(paint(f"BOARD {slug}", "b"))
        for l in rows:
            print("  " + l.strip())
        print()


def main() -> None:
    args = sys.argv[1:]
    if "--board" in args:
        board(args[args.index("--board") + 1])
    print(paint("THE GATE  every Arcade call, as the policy decides it", "b"))
    print(paint("look runs, draft runs, ship waits for you; caps and halt stop it", "d"))
    print()
    pos = 0
    first = True
    while True:
        try:
            with RECEIPTS.open() as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
        except FileNotFoundError:
            chunk = ""
        rows = []
        for raw in chunk.splitlines():
            try:
                rows.append(json.loads(raw))
            except ValueError:
                continue
        width = shutil.get_terminal_size((120, 40)).columns
        # Start clean: only calls made after the pane opens (pass --history to replay the last few).
        for r in (rows[-8:] if "--history" in sys.argv else []) if first else rows:
            for part in line(r).split("\n"):
                print(fit(part, width), flush=True)
        first = False
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
