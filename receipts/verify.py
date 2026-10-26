"""Receipt-chain verifier.

INDEPENDENT BY CONSTRUCTION: it re-reads the receipts from disk and recomputes
every hash and link from genesis itself. It never trusts the writer's
in-memory state, a cached "verified" flag, or anything but the bytes on disk —
hand it a path, and it does the whole computation again.

Fail closed: anything the verifier cannot positively confirm — an unreadable
file, a malformed line, a hash that doesn't recompute, a broken link, a
sequence gap — is a failure, never a shrug. Any failure means the WHOLE chain
is unverified.

A pure hash chain cannot, on its own, detect that the TAIL was truncated: a
shorter prefix still links cleanly from genesis. To catch that, pass the known
tip hash and/or the known receipt count; the verifier then rejects a chain
whose head or length no longer matches what you anchored to. These anchors are
optional and change nothing about the receipt format — without them the
verifier behaves exactly as it did on Day 1.
"""

from __future__ import annotations

import json
from pathlib import Path

from .chain import GENESIS, digest


def verify_chain(path, expect_tip: str | None = None, expect_count: int | None = None):
    """Return (ok, reason). ok is True only if every receipt verifies AND any
    anchor supplied (tip hash, receipt count) matches the chain on disk."""
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

    # The internal chain is sound. The optional external anchors catch a tail
    # truncation, which a valid prefix would otherwise pass silently.
    if expect_count is not None and len(lines) != expect_count:
        if len(lines) < expect_count:
            return False, (
                f"chain truncated: expected {expect_count} receipts, found "
                f"{len(lines)}; receipt {len(lines)} onward is missing"
            )
        return False, (
            f"chain longer than anchored: expected {expect_count} receipts, "
            f"found {len(lines)}"
        )
    if expect_tip is not None and prev != expect_tip:
        return False, (
            f"chain tip mismatch: expected tip {expect_tip[:12]}…, found "
            f"{prev[:12]}…; the tail was truncated or altered"
        )

    return True, f"{len(lines)} receipts verified"
