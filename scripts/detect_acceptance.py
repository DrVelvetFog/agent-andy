#!/usr/bin/env python3
"""Form 2 acceptance test — "can I detect here?" with proof.

Runs the vetted sample (data/detect_sample.toml) through the lookup + evidence
gate and checks the honesty properties that make this an agent with proof:

  1. The six primary-sourced places ANSWER with a rule verdict AND a cited
     primary source (url + quote) in the receipt.
  2. Jekyll (draft source) answers WITH A CAVEAT by default, and STAGES under
     strict mode — the Nov-9 pin-or-stage switch.
  3. Tybee (no primary found) STAGES as unverified, with a reason, and never
     returns "allowed" — the thesis beat.
  4. A place outside the vetted set STAGES, never guessed from a neighbour.
  5. Every answer receipt carries BOTH axes — the rule verdict (or its absence)
     and the evidence tier / staging reason — and the chain verifies.

No network, no model. A staged outcome is a PASS: it proves the gate fired.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import detect  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "detect-receipts.jsonl"

# (query, strict, expected decision, expected rule_verdict)
CASES = [
    ("Myrtle Beach", False, detect.ANSWERED, "allowed"),
    ("Orange Beach", False, detect.ANSWERED, "allowed"),
    ("Lake of the Ozarks State Park", False, detect.ANSWERED, "allowed_with_registration"),
    ("Honeymoon Island State Park", False, detect.ANSWERED, "limited"),
    ("Dauphin Island", False, detect.ANSWERED, "restricted"),
    ("Ulysses S. Grant National Historic Site", False, detect.ANSWERED, "restricted"),
    ("Jekyll Island", False, detect.ANSWERED_WITH_CAVEAT, "restricted"),
    ("Jekyll Island", True, detect.STAGED, "restricted"),  # strict: staged on evidence, content kept
    ("Tybee Island", False, detect.STAGED, None),       # the thesis beat
    ("Clearwater Beach", False, detect.STAGED, None),   # excluded -> no inference
]


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)
    chain = ReceiptChain(CHAIN)

    rows = []
    for query, strict, exp_decision, exp_verdict in CASES:
        res = detect.answer(chain, query, strict=strict)
        o = res["outcome"]
        rows.append((query, strict, exp_decision, exp_verdict, o))
        tag = "STRICT" if strict else ""
        cite = "cited" if o["citation"] else "—"
        print(f"  {query:42}{tag:7} -> {o['decision']:20} "
              f"verdict={str(o['rule_verdict']):26} [{cite}]")

    # Honesty checks.
    checks = {}
    checks["every decision as expected"] = all(
        o["decision"] == exp_d and o["rule_verdict"] == exp_v
        for _, _, exp_d, exp_v, o in rows
    )
    checks["answered cases carry a primary citation (url+quote)"] = all(
        o["citation"] and o["citation"]["url"] and o["citation"]["quote"]
        for *_ , o in rows if o["decision"] in (detect.ANSWERED, detect.ANSWERED_WITH_CAVEAT)
    )
    checks["staged cases carry a staging reason"] = all(
        bool(o["staging_reason"]) for *_, o in rows if o["decision"] == detect.STAGED
    )
    checks["Jekyll default answers with a caveat"] = any(
        q == "Jekyll Island" and not s and o["decision"] == detect.ANSWERED_WITH_CAVEAT and o["caveat"]
        for q, s, _, _, o in rows
    )
    checks["Jekyll strict stages (pin-or-stage switch)"] = any(
        q == "Jekyll Island" and s and o["decision"] == detect.STAGED
        for q, s, _, _, o in rows
    )
    tybee = next(o for q, *_ , o in rows if q == "Tybee Island")
    checks["Tybee staged, never 'allowed', no verdict"] = (
        tybee["decision"] == detect.STAGED and tybee["rule_verdict"] is None
        and "allowed" not in str(tybee["rule_verdict"]).lower()
    )
    excluded = next(o for q, *_, o in rows if q == "Clearwater Beach")
    checks["excluded place staged (no inference)"] = (
        excluded["decision"] == detect.STAGED and excluded["evidence_tier"] == "none"
    )

    # The durable artifact — the receipt — must carry BOTH axes.
    answers = [r for r in chain.receipts() if r["action"].get("type") == "detect_answer"]
    checks["every answer receipt carries both axes"] = all(
        ("rule_verdict" in r["action"] and "evidence_tier" in r["action"]
         and "decision" in r["action"]
         and (r["action"].get("citation") or r["action"].get("staging_reason")))
        for r in answers
    )
    ok, reason = verify_chain(CHAIN)
    checks["chain verifies end to end"] = ok

    print(f"\nreceipts written: {len(chain.receipts())} ({len(answers)} answers); verify: {reason}\n")
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    if all(checks.values()):
        print("\nFORM 2 (detect-here) ACCEPTANCE: PASS")
        return 0
    print("\nFORM 2 (detect-here) ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
