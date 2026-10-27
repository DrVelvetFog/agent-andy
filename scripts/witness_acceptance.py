#!/usr/bin/env python3
"""Witness acceptance — verified packing checklist.

Two modes:

  --selftest   Deterministic, no SAM and no photos. Proves the one checker rule
               and fail-closed behaviour: all items verified -> box READY TO
               SHIP; any item unverified -> NOT shipped, with the exact item
               named. Also checks every observation receipt carries the photo
               hash + SAM mask id, and the chain verifies.

  <triples>    Real run. Each arg is item:concept:photo_path (cable FIRST — the
               known weak link). Andy segments each real photo with SAM, fails
               closed on a miss/low confidence, and ships only if all verify.
               Needs MODEL_API_KEY and real photos (e.g. pulled off the Razr).
               Example:
                 python3 scripts/witness_acceptance.py \\
                   cable:cable:runs/witness/cable.jpg \\
                   book:book:runs/witness/book.jpg \\
                   charger:charger:runs/witness/charger.jpg
               Pre-agreed swap if the cable fails SAM: rerun with
                 cable:"power bank":runs/witness/powerbank.jpg
               Pass --verbose to print SAM's raw response for the first item
               (used once to confirm the response shape).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import witness  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"


def _selftest() -> int:
    RUNS.mkdir(exist_ok=True)

    # Case A: all three verified -> ready to ship.
    a = RUNS / "witness-selftest-a.jsonl"
    a.unlink(missing_ok=True)
    chain_a = ReceiptChain(a)
    res_a = [
        witness.record(chain_a, "cable", "cable", "selftest:cable", True, "stub verified", 1, 0.91, "cable#0"),
        witness.record(chain_a, "book", "book", "selftest:book", True, "stub verified", 1, 0.95, "book#0"),
        witness.record(chain_a, "charger", "charger", "selftest:charger", True, "stub verified", 1, 0.88, "charger#0"),
    ]
    fin_a = witness.finalize(chain_a, res_a)

    # Case B: the cable fails -> NOT shipped, cable named.
    b = RUNS / "witness-selftest-b.jsonl"
    b.unlink(missing_ok=True)
    chain_b = ReceiptChain(b)
    res_b = [
        witness.record(chain_b, "cable", "cable", "selftest:cable", False, "SAM found no 'cable' — unverified", 0, None, None),
        witness.record(chain_b, "book", "book", "selftest:book", True, "stub verified", 1, 0.95, "book#0"),
        witness.record(chain_b, "charger", "charger", "selftest:charger", True, "stub verified", 1, 0.88, "charger#0"),
    ]
    fin_b = witness.finalize(chain_b, res_b)

    obs = [r for r in chain_a.receipts() if r["action"].get("type") == "witness_observation"]
    ok_a, _ = verify_chain(a)
    ok_b, _ = verify_chain(b)

    checks = {
        "all verified -> READY TO SHIP": fin_a["ready_to_ship"] and not fin_a["unverified_items"],
        "one miss -> NOT shipped": not fin_b["ready_to_ship"],
        "unverified item named exactly": fin_b["unverified_items"] == ["cable"],
        "every observation receipt carries photo_hash + sam_mask_id keys": all(
            "photo_hash" in r["action"] and "sam_mask_id" in r["action"] for r in obs
        ),
        "both chains verify": ok_a and ok_b,
    }
    print("WITNESS SELFTEST (no SAM, no photos — the checker rule + fail-closed logic):")
    print(f"  case A (all verified): ready_to_ship={fin_a['ready_to_ship']} missing={fin_a['unverified_items']}")
    print(f"  case B (cable fails):  ready_to_ship={fin_b['ready_to_ship']} missing={fin_b['unverified_items']}\n")
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if all(checks.values()):
        print("\nWITNESS SELFTEST: PASS")
        return 0
    print("\nWITNESS SELFTEST: FAIL")
    return 1


def _real(triples: list[str], verbose: bool) -> int:
    RUNS.mkdir(exist_ok=True)
    chain_path = RUNS / "witness-receipts.jsonl"
    chain_path.unlink(missing_ok=True)
    chain = ReceiptChain(chain_path)

    results = []
    for i, triple in enumerate(triples):
        item, concept, path = triple.split(":", 2)
        if verbose and i == 0:
            from agent import eyes
            seg = eyes.segment(path, concept)
            print(f"[verbose] first SAM: detections={seg['detections']} "
                  f"raw_boxes={seg['raw_boxes']} top_area_frac={seg['top_area_frac']}\n")
        r = witness.observe_and_verify(chain, item, concept, path)
        results.append(r)
        mark = "✓" if r["verified"] else "✗"
        print(f"  {mark} {item:10} ({concept}): {r['reason']}")

    fin = witness.finalize(chain, results)
    ok, reason = verify_chain(chain_path)
    print(f"\n  {'READY TO SHIP' if fin['ready_to_ship'] else 'NOT shipped'}"
          + (f" — unverified: {fin['unverified_items']}" if fin['unverified_items'] else ""))
    print(f"  chain: {reason}")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv or not argv:
        return _selftest()
    verbose = "--verbose" in argv
    triples = [a for a in argv if not a.startswith("--")]
    return _real(triples, verbose)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
