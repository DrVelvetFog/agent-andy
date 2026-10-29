"""Hash-chained action receipts.

Each receipt is one JSON object on its own line (JSONL). A receipt commits to
the hash of the receipt before it, so changing any byte of any receipt breaks
every hash from that point forward. The hash covers the whole receipt body
(sequence number, timestamp, action, previous hash) under a fixed canonical
JSON encoding, so the same receipt always hashes to the same value on any
machine.

Appends are atomic within one process: a lock per chain file (shared by every
ReceiptChain on that path) is held across the read, the seq/prev computation, and
the write, so two threads can never both claim the same seq and prev.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

GENESIS = "0" * 64

# One lock per chain file, shared by every ReceiptChain on that path in this process.
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


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
        self._lock = _lock_for(self.path)

    def receipts(self) -> list[dict]:
        with self._lock:  # never read a line another thread is mid-way through writing
            if not self.path.exists():
                return []
            out = []
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
            return out

    def append(self, action: dict) -> dict:
        """Record one action. Returns the receipt that was written. Atomic within
        this process: read, seq/prev, and write all happen under the chain's lock."""
        with self._lock:
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
