#!/usr/bin/env python3
"""CLI: independently verify a hash-chained receipt log.

Re-reads the receipts from disk and recomputes every hash itself — it trusts
nothing but the bytes in the file. Prints the chain length, a plain PASS/FAIL,
and on failure exactly which receipt failed and why. Fail-closed: any failure
means the whole chain is unverified.

    python3 scripts/verify_receipts.py runs/gated-loop-receipts.jsonl
    python3 scripts/verify_receipts.py CHAIN --expect-count 12 --expect-tip <hash>

Pass --expect-count / --expect-tip (the chain's known length and head) to also
catch a truncated tail, which a bare hash chain cannot detect on its own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from receipts import verify_chain  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Independently verify a receipt chain.")
    ap.add_argument("path", help="path to the receipt JSONL file")
    ap.add_argument("--expect-count", type=int, default=None,
                    help="known receipt count (detects a truncated tail)")
    ap.add_argument("--expect-tip", default=None,
                    help="known tip hash (detects a truncated or altered tail)")
    args = ap.parse_args()

    try:
        count = len([l for l in Path(args.path).read_text(encoding="utf-8").splitlines() if l.strip()])
        print(f"chain: {count} receipts on disk")
    except OSError as e:
        print(f"chain: unreadable ({e})")

    ok, reason = verify_chain(args.path, expect_tip=args.expect_tip, expect_count=args.expect_count)
    if ok:
        print(f"PASS — {reason}. Recompute it yourself to confirm; nothing here is cached.")
        return 0
    print(f"FAIL — {reason}.")
    print("Fail-closed: the WHOLE chain is unverified.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
