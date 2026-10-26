#!/usr/bin/env python3
"""Day 1 acceptance test.

PASS means both of these hold:
  1. A stub loop writes 3 actions -> 3 receipts, and the verifier accepts the chain.
  2. Tampering with a single byte of any receipt makes the verifier reject the chain.

No network, no models, no dependencies — this proves the receipt spine before
anything intelligent is attached to it.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "day1-receipts.jsonl"
TAMPERED = RUNS / "day1-receipts.tampered.jsonl"

FAKE_ACTIONS = [
    {"type": "tool", "tool": "echo", "summary": "fake action one: greet the owner"},
    {"type": "observe", "summary": "fake action two: look at the desk"},
    {"type": "comment", "summary": "fake action three: daemon remark, dismissible"},
]


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)

    chain = ReceiptChain(CHAIN)
    for action in FAKE_ACTIONS:
        r = chain.append(action)
        print(f"receipt {r['seq']}: {r['hash'][:16]}…  <- {action['summary']}")

    ok, reason = verify_chain(CHAIN)
    print(f"\nintact chain:   ok={ok} ({reason})")
    if not ok:
        print("FAIL: a freshly written chain must verify")
        return 1

    # Flip one byte: swap the case of the first letter of "fake" in receipt 1.
    data = bytearray(CHAIN.read_bytes())
    idx = data.find(b"fake", data.find(b"fake") + 1)  # second occurrence -> receipt 1
    data[idx] = ord("F")
    TAMPERED.write_bytes(bytes(data))

    ok2, reason2 = verify_chain(TAMPERED)
    print(f"tampered chain: ok={ok2} ({reason2})")
    if ok2:
        print("FAIL: a tampered chain must NOT verify")
        return 1

    print("\nDAY 1 ACCEPTANCE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
