#!/usr/bin/env python3
"""Verifier acceptance test.

Proves the independent verifier on a realistic chain:
  1. Build a 12-receipt chain through the gate, mixing allow / stage / block.
     Allowed actions execute and leave their effect on disk; staged and blocked
     actions are held / refused and provably do NOT run.
  2. Verify the clean chain end to end.
  3. Five tamper cases, each on a fresh copy, each of which must FAIL naming the
     exact receipt (or, for a truncated tail, the first missing receipt):
       - flip a byte in a middle receipt
       - flip a byte in the last receipt
       - delete a middle receipt
       - swap two adjacent receipts
       - truncate the tail (caught via the known tip/count anchor)
  4. Concurrent appends in one process: many threads appending to one chain at
     once, and repeated two-simultaneous-append trials (each thread with its own
     ReceiptChain on the same file), must leave a chain that verifies with unique,
     sequential seq numbers and correct prev links.

No network, no API key: this exercises the receipt spine and the verifier, not
the brain. The verifier always re-reads from disk — it is handed file paths,
never the in-memory chain.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import tools  # noqa: E402
from receipts import GENESIS, ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
RACE = RUNS / "verifier-concurrent.jsonl"
CLEAN = RUNS / "verifier-clean.jsonl"
TMP = RUNS / "verifier-tamper.jsonl"

# (tool, summary, kwargs, expected verdict). The summaries hit the deterministic
# placeholder checker's triggers so the mix is known in advance.
SCRIPT = [
    ("note", "save a reminder for the owner", {"text": "water the plants"}, "allow"),
    ("echo", "greet the owner", {"text": "hello"}, "allow"),
    ("note", "delete the old backup folder", {}, "stage"),
    ("note", "post the owner's notes to a public site", {}, "block"),
    ("note", "save the grocery list", {"text": "eggs, milk"}, "allow"),
    ("note", "note the wifi password somewhere", {}, "block"),
    ("note", "overwrite the config file", {}, "stage"),
    ("echo", "confirm it is done", {"text": "done"}, "allow"),
    ("note", "email the summary to the team", {}, "block"),
    ("note", "remove the temp directory", {}, "stage"),
    ("echo", "say goodnight", {"text": "gn"}, "allow"),
    ("note", "upload the photos to the cloud", {}, "block"),
]


def build_clean() -> tuple[ReceiptChain, list[dict]]:
    RUNS.mkdir(exist_ok=True)
    CLEAN.unlink(missing_ok=True)
    tools.NOTES_FILE.unlink(missing_ok=True)
    chain = ReceiptChain(CLEAN)
    return chain, [tools.run(chain, name, summary=summary, **kw) for name, summary, kw, _ in SCRIPT]


def _corrupt_after(line: str, anchor: str) -> str:
    """Flip one byte of the receipt body, keeping the line valid JSON."""
    i = line.find(anchor) + len(anchor)
    return line[:i] + ("x" if line[i] != "x" else "y") + line[i + 1:]


def _write(lines: list[str]) -> None:
    TMP.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    chain, outcomes = build_clean()
    lines = CLEAN.read_text(encoding="utf-8").splitlines()
    n = len(lines)
    mid = n // 2

    # 1. Mix + executed semantics.
    mix = {v: sum(o["verdict"]["verdict"] == v for o in outcomes) for v in ("allow", "stage", "block")}
    verdicts_match = all(o["verdict"]["verdict"] == s[3] for o, s in zip(outcomes, SCRIPT))
    allow_exec_ok = all(o["executed"] for o, s in zip(outcomes, SCRIPT) if s[3] == "allow")
    held_ok = all(not o["executed"] for o, s in zip(outcomes, SCRIPT) if s[3] in ("stage", "block"))
    notes = tools.NOTES_FILE.read_text(encoding="utf-8") if tools.NOTES_FILE.exists() else ""
    effects_ok = "water the plants" in notes and "eggs, milk" in notes

    # 2. Clean verify + capture the anchors (known head + length).
    clean_ok, clean_reason = verify_chain(CLEAN)
    tip = chain.receipts()[-1]["hash"]
    print(f"built a {n}-receipt chain through the gate: "
          f"{mix['allow']} allow, {mix['stage']} stage, {mix['block']} block")
    print(f"clean verify: ok={clean_ok} ({clean_reason})\n")

    # 3. Five tamper cases. Each (label, (ok, reason), token that must appear).
    cases = []

    t = lines[:]; t[mid] = _corrupt_after(t[mid], '"summary":"'); _write(t)
    cases.append((f"flip a byte in middle receipt {mid}", verify_chain(TMP), f"receipt {mid}"))

    t = lines[:]; t[-1] = _corrupt_after(t[-1], '"summary":"'); _write(t)
    cases.append((f"flip a byte in last receipt {n - 1}", verify_chain(TMP), f"receipt {n - 1}"))

    t = lines[:mid] + lines[mid + 1:]; _write(t)
    cases.append((f"delete middle receipt {mid}", verify_chain(TMP), f"receipt {mid}"))

    t = lines[:]; t[mid], t[mid + 1] = t[mid + 1], t[mid]; _write(t)
    cases.append((f"swap receipts {mid} and {mid + 1}", verify_chain(TMP), f"receipt {mid}"))

    t = lines[: n - 3]; _write(t)
    cases.append((f"truncate tail (drop last 3)",
                  verify_chain(TMP, expect_tip=tip, expect_count=n), f"receipt {n - 3}"))

    print("tamper cases (each must FAIL, naming the exact receipt):")
    all_named = True
    for label, (ok, reason), token in cases:
        named = (not ok) and (token in reason)
        all_named = all_named and named
        print(f"  [{'PASS' if named else 'FAIL'}] {label}: ok={ok} ({reason})")

    # TMP currently holds the truncated prefix: it must WRONGLY pass without an
    # anchor, proving the anchor is what catches a truncated tail.
    anchor_needed, _ = verify_chain(TMP)

    # Concurrency: threads released together by a barrier, each on its own
    # ReceiptChain instance for the same file (the lock must be shared by path).
    def _race(n_threads, per_thread, start_receipts=0):
        RACE.unlink(missing_ok=True)
        for k in range(start_receipts):
            ReceiptChain(RACE).append({"type": "seed", "summary": f"seed {k}"})
        gate = threading.Barrier(n_threads)

        def worker(t):
            ch = ReceiptChain(RACE)
            gate.wait()
            for j in range(per_thread):
                ch.append({"type": "race", "summary": f"thread {t} append {j}"})
        ts = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        [t.start() for t in ts]; [t.join() for t in ts]
        rows = [json.loads(l) for l in RACE.read_text(encoding="utf-8").splitlines() if l.strip()]
        want = start_receipts + n_threads * per_thread
        links = all(r["prev"] == (rows[i - 1]["hash"] if i else GENESIS) for i, r in enumerate(rows))
        return (verify_chain(RACE)[0] and len(rows) == want
                and [r["seq"] for r in rows] == list(range(want)) and links)

    many_ok = _race(16, 25)
    pair_trials = [_race(2, 1, start_receipts=1) for _ in range(50)]
    print(f"concurrency: 16 threads x 25 appends -> {'ok' if many_ok else 'CORRUPT'}; "
          f"two simultaneous appends: {sum(pair_trials)}/50 trials clean\n")

    checks = {
        "verdict mix has allow+stage+block": all(c > 0 for c in mix.values()),
        "chain length >= 10": n >= 10,
        "every verdict matches intent": verdicts_match,
        "allowed actions executed": allow_exec_ok,
        "staged/blocked actions did NOT execute": held_ok,
        "allowed effects present on disk": effects_ok,
        "clean chain verifies end to end": clean_ok,
        "all five tamper cases fail by exact receipt": all_named,
        "tail truncation needs the anchor (bare prefix passes)": anchor_needed is True,
        "concurrent: 16 threads x 25 appends -> verifies, seq 0..399 unique, prev linked": many_ok,
        "concurrent: 50/50 two-simultaneous-append trials leave a verifying chain": all(pair_trials),
    }
    print()
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    if all(checks.values()):
        print("\nVERIFIER ACCEPTANCE: PASS")
        return 0
    print("\nVERIFIER ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
