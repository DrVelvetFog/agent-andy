#!/usr/bin/env python3
"""Daemon acceptance — the one proactive beat, and the hard rules around it.

The daemon may surface exactly one suggestion after a task STAGES something, and
only then. Every rule below is a property we refuse to break for the demo:

  a. silent outside an active task,
  b. speaks at most once during an active task, on the staged-receipt trigger
     only (an answered task gets no suggestion),
  c. one dismissal silences it for the rest of the session, visibly (receipted),
  d. never about people, text fields, or off-task content,
  e. a suggestion is receipted AND gated by the policy engine, never executed.

Deterministic and local: the daemon is driven with real detect-shaped outcomes
and `voice=False`, so nothing here calls the network. The chain still verifies.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import checker, detect, voice  # noqa: E402
from agent.daemon import Daemon  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "daemon-receipts.jsonl"


def staged(place="Tybee Island", reason="no primary source was found; needs a human"):
    return {"decision": detect.STAGED, "outcome": {"place": place, "staging_reason": reason}}


def answered(place="Myrtle Beach"):
    return {"decision": detect.ANSWERED, "outcome": {"place": place, "rule_verdict": "allowed"}}


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)
    chain = ReceiptChain(CHAIN)
    checks: dict[str, bool] = {}

    # a. Silent outside an active task.
    d = Daemon(); d.new_task()
    checks["a. silent outside an active task"] = (
        d.observe(chain, staged(), active_task=False, voice_mode=False) is None)

    # b. Speaks on the staged trigger only, at most once per task.
    d = Daemon(); d.new_task()
    no_speak_answered = d.observe(chain, answered(), active_task=True, voice_mode=False) is None
    first = d.observe(chain, staged(), active_task=True, voice_mode=False)
    second = d.observe(chain, staged(), active_task=True, voice_mode=False)  # same task again
    checks["b. answered task gets no suggestion"] = no_speak_answered
    checks["b. staged task surfaces exactly one suggestion"] = (
        bool(first and first.get("spoke")) and second is None)

    # New task: it may speak again (until dismissed).
    d.new_task()
    again = d.observe(chain, staged("Daytona Beach"), active_task=True, voice_mode=False)
    checks["b. a new task may surface one again"] = bool(again and again.get("spoke"))

    # e. The suggestion is receipted, gated, and never executed.
    sug = next(r["action"] for r in chain.receipts()
               if r["action"]["type"] == "daemon_suggestion")
    checks["e. suggestion carries a policy verdict (gated)"] = (
        sug.get("verdict", {}).get("verdict") in checker.TIERS)
    checks["e. suggestion is NOT executed"] = (sug.get("executed") is False)
    checks["e. suggestion names its trigger + stays dismissible"] = (
        sug.get("trigger") == "staged_receipt" and sug.get("dismissible") is True
        and "suggested_action" in sug)

    # c. One dismissal silences the session, and the dismissal is visible.
    d.dismiss(chain)
    d.new_task()
    after = d.observe(chain, staged(), active_task=True, voice_mode=False)
    dismiss_receipt = any(r["action"]["type"] == "daemon_dismissed"
                          and r["action"].get("silenced_session") for r in chain.receipts())
    checks["c. dismissal is receipted (visible on the chain)"] = dismiss_receipt
    checks["c. silent for the rest of the session after one dismissal"] = (after is None)

    # d. Never about people, text fields, or off-task content.
    never = {
        "a person's appearance": staged("the coworker's appearance", "x"),
        "a text field": staged("a password text field", "x"),
        "off-task content": staged("something unrelated to the task", "off-task"),
    }
    d2 = Daemon()
    d2_silent = True
    for _, oc in never.items():
        d2.new_task()
        if d2.observe(chain, oc, active_task=True, voice_mode=False) is not None:
            d2_silent = False
    checks["d. never speaks about people / text fields / off-task"] = d2_silent

    # Integration: wired into voice.handle(), it fires on a staged transcript and
    # not on an answered one — through the same gated path, with voice off.
    d3 = Daemon()
    myrtle = voice.handle(chain, "can I detect at Myrtle Beach?", voice.INJECTED,
                          voice=False, daemon=d3)
    tybee = voice.handle(chain, "can I detect at Tybee Island?", voice.INJECTED,
                         voice=False, daemon=d3)
    checks["integration: no suggestion on an answered request"] = (myrtle.get("daemon") is None)
    checks["integration: one suggestion on a staged request"] = (
        bool(tybee.get("daemon") and tybee["daemon"].get("spoke")))

    ok, reason = verify_chain(CHAIN)
    checks["chain verifies end to end"] = ok

    types = [r["action"]["type"] for r in chain.receipts()]
    print(f"receipts written: {len(types)}  "
          f"(suggestions: {types.count('daemon_suggestion')}, "
          f"dismissals: {types.count('daemon_dismissed')}); verify: {reason}\n")
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    if all(checks.values()):
        print("\nDAEMON ACCEPTANCE: PASS")
        return 0
    print("\nDAEMON ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
