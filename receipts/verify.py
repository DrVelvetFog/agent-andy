"""Receipt-chain verifier.

Recomputes every hash and link from genesis. Fail closed: anything the
verifier cannot positively confirm — an unreadable file, a malformed line, a
hash that doesn't recompute, a broken link, a sequence gap — is a failure,
never a shrug.
"""

from __future__ import annotations

import json
from pathlib import Path

from .chain import GENESIS, digest


def verify_chain(path: str | Path) -> tuple[bool, str]:
    """Return (ok, reason). ok is True only if every receipt verifies."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return False, f"unreadable: {e}"

    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return False, "empty chain"

    prev = GENESIS
    for i, line in enumerate(lines):
        try:
            receipt = json.loads(line)
        except json.JSONDecodeError:
            return False, f"receipt {i}: not valid JSON"
        if not isinstance(receipt, dict) or "hash" not in receipt:
            return False, f"receipt {i}: missing hash"
        body = {k: v for k, v in receipt.items() if k != "hash"}
        if digest(body) != receipt["hash"]:
            return False, f"receipt {i}: hash does not recompute"
        if receipt.get("prev") != prev:
            return False, f"receipt {i}: broken link to previous receipt"
        if receipt.get("seq") != i:
            return False, f"receipt {i}: sequence mismatch"
        prev = receipt["hash"]

    return True, f"{len(lines)} receipts verified"
