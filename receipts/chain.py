"""Hash-chained action receipts.

Each receipt is one JSON object on its own line (JSONL). A receipt commits to
the hash of the receipt before it, so changing any byte of any receipt breaks
every hash from that point forward. The hash covers the whole receipt body
(sequence number, timestamp, action, previous hash) under a fixed canonical
JSON encoding, so the same receipt always hashes to the same value on any
machine.

Appends are atomic across threads AND processes (Mac/Unix). chain_lock() is the
one way to hold a chain for writing, and it always takes two locks in the same
order: FIRST the in-process lock for that path (shared by every ReceiptChain on
it, so threads line up), THEN the cross-process flock on <chain>.lock
(filelock.py). Nothing takes them in the other order, so they can't deadlock. The
whole append — read, seq/prev, write, and tip signing — happens under both, so two
processes can never claim the same seq or sign a tip that isn't the final one. If
the file lock isn't free within filelock.LOCK_TIMEOUT, append raises LockTimeout
and writes nothing. Readers take a shared flock (if a writer created the lock
file), so they never see a half-written line. Viewer rotation uses chain_lock too.

After every append, still under the lock, the new tip is signed into <chain>.sig
when Andy's signing key is configured (see signing.py); without it, any stale
signature is removed, so the chain reads UNSIGNED rather than wrongly signed.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
import time
from pathlib import Path

from . import filelock, signing

GENESIS = "0" * 64

# One lock per chain file, shared by every ReceiptChain on that path in this process.
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


@contextlib.contextmanager
def chain_lock(path):
    """Hold a chain for writing: the in-process lock FIRST, then the cross-process
    file lock — the same order everywhere. Raises filelock.LockTimeout, having
    written nothing, if another process holds the chain too long."""
    with _lock_for(Path(path)):
        with filelock.exclusive(path):
            yield


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
        # never read a line another thread or process is mid-way through writing
        with self._lock, filelock.shared_if_present(self.path):
            return self._read()

    def _read(self) -> list[dict]:
        """Parse the file with no locking; callers hold the right lock."""
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def append(self, action: dict) -> dict:
        """Record one action. Returns the receipt that was written. Atomic across
        threads and processes: read, seq/prev, write, and tip signing all happen
        under chain_lock. (It reads with _read, not receipts(): a second, shared
        flock on the same file from inside the exclusive one would deadlock.)"""
        with chain_lock(self.path):
            existing = self._read()
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
            signing.sign_tip(self.path, receipt["seq"] + 1, receipt["hash"])
            return receipt
