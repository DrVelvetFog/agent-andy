"""Hash-chained action receipts.

Each receipt is one JSON object on its own line (JSONL). A receipt commits to
the hash of the receipt before it, so changing any byte of any receipt breaks
every hash from that point forward. The hash covers the whole receipt body
(sequence number, timestamp, action, previous hash) under a fixed canonical
JSON encoding, so the same receipt always hashes to the same value on any
machine.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

GENESIS = "0" * 64


def canonical(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


class ReceiptChain:
    """Append-only receipt log backed by a JSONL file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def receipts(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def append(self, action: dict) -> dict:
        """Record one action. Returns the receipt that was written."""
        existing = self.receipts()
        body = {
            "seq": len(existing),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": action,
            "prev": existing[-1]["hash"] if existing else GENESIS,
        }
        receipt = dict(body, hash=digest(body))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(canonical(receipt).decode("utf-8") + "\n")
        return receipt
