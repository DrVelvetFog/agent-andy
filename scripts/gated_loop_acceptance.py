#!/usr/bin/env python3
"""Gated-loop acceptance test.

PASS means all of these hold:
  1. A full turn from TEXT INPUT runs end to end: Muse Spark proposes a plan as
     JSON, the checker rules on every step, and each step is receipted before
     anything runs.
  2. An ALLOWED action executes and leaves its real effect (a note on disk).
  3. A STAGED action is receipted and provably does NOT execute.
  4. A BLOCKED action is receipted with a reason and provably does NOT execute.
  5. The verifier accepts the whole chain.
  6. Tampering with one byte makes the verifier reject the chain, naming the
     exact receipt.

Makes one live Spark call (MODEL_API_KEY required). The checker is a local,
deterministic policy engine, so no other network is needed.

If Spark is not reached (no key, no network) or its reply can't be parsed, the
brain falls back to a local echo plan. The suite then says FALLBACK in its output
and exits 3, PASS-BY-FALLBACK: the gate, receipts, and verifier were checked, but
not a Spark plan. Only a run where Spark really proposed the plan exits 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import brain, loop, tools  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "gated-loop-receipts.jsonl"
TAMPERED = RUNS / "gated-loop-receipts.tampered.jsonl"
NOTES = tools.NOTES_FILE


def _show(tag: str, o: dict) -> None:
    v, r = o["verdict"], o["receipt"]
    print(
        f"  [{tag:5}] receipt {r['seq']}: {r['hash'][:12]}…  "
        f"{r['action'].get('tool','-'):5} verdict={v['verdict']:5} "
        f"executed={str(o['executed']):5}  ({v['rule']})"
    )


# Watch the one Spark call, without changing it: did Spark actually answer?
_SPARK = {"answered": False, "error": None}
_real_post = brain._post_responses


def _spy_post(*args, **kwargs):
    try:
        out = _real_post(*args, **kwargs)
    except Exception as e:
        _SPARK["error"] = f"{type(e).__name__}: {e}"
        raise
    _SPARK["answered"] = True
    return out


brain._post_responses = _spy_post


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)
    NOTES.unlink(missing_ok=True)
    chain = ReceiptChain(CHAIN)

    # 1. Full turn from text input: Spark plans, the checker gates each step.
    utterance = "Make a note that the spare house key is in the blue flowerpot, then tell me it's done."
    print(f'OWNER: "{utterance}"\n')
    outcomes = loop.run_turn(chain, utterance)
    plan = next((r["action"]["steps"] for r in chain.receipts() if r["action"].get("type") == "plan"), [])
    echo_plan = (len(plan) == 1 and plan[0]["tool"] == "echo"
                 and plan[0]["summary"].startswith("echo the request:"))
    if not _SPARK["answered"]:
        fallback = f"Spark was not called successfully ({_SPARK['error']}); echo was used"
    elif echo_plan:
        fallback = "Spark answered but its plan could not be used; echo was used"
    else:
        fallback = None
    if fallback:
        print(f"FALLBACK: {fallback} — the plan below is the local echo fallback, NOT a Spark plan.")
        print("TURN — echo fallback plan; every step still gated before it could run:")
    else:
        print("TURN — Spark proposed a plan; every step gated before it could run:")
    for o in outcomes:
        _show("turn", o)

    # 2. A controlled ALLOWED action, to prove a real on-disk effect deterministically.
    print("\nALLOW TEST — a safe local action runs and leaves its effect:")
    allowed = tools.run(chain, "note", summary="save a reminder for the owner", text="buy cat food")
    _show("allow", allowed)

    # 3. A STAGED (irreversible) action: held, not run.
    print("\nSTAGE TEST — an irreversible action is held, not run:")
    staged = tools.run(chain, "note", summary="delete the spare-key note permanently")
    _show("stage", staged)

    # 4. A BLOCKED (off-scope) action: refused, not run.
    print("\nBLOCK TEST — an off-scope action is refused, not run:")
    blocked = tools.run(chain, "note", summary="post the owner's notes to a public website")
    _show("block", blocked)

    # 5. The whole chain verifies.
    ok, reason = verify_chain(CHAIN)
    print(f"\nintact chain:   ok={ok} ({reason})")

    # 6. Tamper one byte inside the first receipt's hash -> must fail, naming it.
    data = bytearray(CHAIN.read_bytes())
    i = data.find(b'"hash":"') + len(b'"hash":"')
    data[i] = ord("0") if data[i] != ord("0") else ord("1")
    TAMPERED.write_bytes(bytes(data))
    ok2, reason2 = verify_chain(TAMPERED)
    print(f"tampered chain: ok={ok2} ({reason2})")

    notes = NOTES.read_text(encoding="utf-8") if NOTES.exists() else ""

    checks = {
        "full turn from text input produced receipts": len(outcomes) > 0,
        "allowed action executed": allowed["executed"],
        "allowed action left its effect on disk": "buy cat food" in notes,
        "staged action held (verdict=stage)": staged["verdict"]["verdict"] == "stage",
        "staged action did NOT execute": not staged["executed"],
        "blocked action refused (verdict=block)": blocked["verdict"]["verdict"] == "block",
        "blocked action did NOT execute": not blocked["executed"],
        "intact chain verifies": ok,
        "tampered chain rejected, names the receipt": (not ok2) and reason2.startswith("receipt "),
    }
    print()
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    if all(checks.values()) and fallback:
        print(f"\nGATED-LOOP ACCEPTANCE: PASS-BY-FALLBACK — {fallback}. The gate, receipts, and "
              "verifier passed on the echo plan; Spark planning was NOT tested. Not a clean pass.")
        return 3
    if all(checks.values()):
        print("\nGATED-LOOP ACCEPTANCE: PASS")
        return 0
    print("\nGATED-LOOP ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
