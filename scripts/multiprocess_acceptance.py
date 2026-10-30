#!/usr/bin/env python3
"""Multi-process lock acceptance — real separate processes, not threads (Mac/Unix).

Signs with a THROWAWAY key (scripts/signing_testkey.py), never Andy's real key.
Workers start together on a shared signal so their appends genuinely collide.

  1. 4 processes x 25 appends to one signed chain: exactly 100 receipts, seq 0-99
     with no gap or duplicate, every process's 25 receipts present once, the chain
     verifies, and the signed tip is VERIFIED against the final chain.
  2. the same, unsigned: 100 receipts, verifies, reads UNSIGNED.
  3. a reader verifying over and over while those writers run never sees a torn
     chain.
  4. a held lock makes a writer fail closed: LockTimeout, and the chain and its
     .sig are byte-for-byte unchanged.
  5. a writer killed (kill -9) while holding the lock doesn't block the next one.
  6. 2 processes x 10 earned-answer approvals at once: all 20 entries kept, each
     with a signature that verifies.
  7. lock files are left in place (never deleted) and git-ignored.
  Control (printed, not a check): the same race with the lock switched off loses or
  duplicates receipts, so check 1 is testing a real race.

Local only: no network, no model.
"""

from __future__ import annotations

import fnmatch
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from signing_testkey import use_test_key  # noqa: E402

use_test_key()

from agent import verify_source as vs  # noqa: E402
from receipts import filelock, signing, verify_chain  # noqa: E402

N_PROC, N_EACH = 4, 25
checks: dict[str, bool] = {}

# One worker program, several modes. argv: root mode path go-file [extra...]
_WORKER = r"""
import json, os, sys, time
from pathlib import Path
root, mode, path, go = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
sys.path.insert(0, str(root))
from receipts import ReceiptChain, filelock, verify_chain
from receipts.chain import chain_lock
while not go.exists():
    time.sleep(0.001)
if mode in ("append", "append-nolock"):
    who, n = sys.argv[5], int(sys.argv[6])
    if mode == "append-nolock":            # the control: no cross-process lock at all
        import contextlib
        filelock.exclusive = lambda *a, **k: contextlib.nullcontext()
    c = ReceiptChain(path)
    for i in range(n):
        c.append({"type": "step", "summary": f"{who}-{i}"})
elif mode == "read":
    bad, n = 0, 0
    stop = Path(sys.argv[5])
    while not path.exists() and not stop.exists():   # verify a chain once it exists;
        time.sleep(0.001)                            # its lock file exists by then too
    while not stop.exists():
        ok, _ = verify_chain(path)
        n += 1
        bad += 0 if ok else 1
    print(json.dumps({"reads": n, "bad": bad}))
elif mode == "hold":
    with chain_lock(path):
        Path(sys.argv[5]).write_text("held")
        time.sleep(float(sys.argv[6]))
elif mode == "append-once":
    filelock.LOCK_TIMEOUT = float(sys.argv[5])
    try:
        ReceiptChain(path).append({"type": "step", "summary": "late writer"})
        print("WROTE")
    except filelock.LockTimeout as e:
        print("TIMEOUT", e)
elif mode == "persist":
    from agent import verify_source as vs
    who, n = sys.argv[5], int(sys.argv[6])
    s = vs.KnowledgeStore(persist_path=path)
    for i in range(n):
        s._persist_put(f"{who}-{i}", {"place": f"{who}-{i}", "verdict": "Allowed"})
"""


def _spawn(mode, path, go, *extra, env=None):
    return subprocess.Popen([sys.executable, "-c", _WORKER, str(ROOT), mode, str(path), str(go), *map(str, extra)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=env or os.environ.copy())


def _race(d: Path, name: str, mode="append", env=None, reader=False):
    """Start N_PROC appenders (and optionally a reader) together; return the chain."""
    path, go, stop = d / name, d / f"{name}.go", d / f"{name}.stop"
    procs = [_spawn(mode, path, go, f"p{k}", N_EACH, env=env) for k in range(N_PROC)]
    rd = _spawn("read", path, go, stop, env=env) if reader else None
    time.sleep(0.3)
    go.write_text("go")
    errs = [p.communicate(timeout=120)[1] for p in procs]
    read = None
    if rd:
        stop.write_text("stop")
        out, _ = rd.communicate(timeout=60)
        read = json.loads(out.strip().splitlines()[-1])
    return path, errs, read


def _lines(path: Path) -> list[dict]:
    out = []
    for l in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(l))
        except ValueError:
            out.append(None)
    return out


def _complete(path: Path) -> bool:
    rs = _lines(path)
    want = {f"p{k}-{i}" for k in range(N_PROC) for i in range(N_EACH)}
    got = [r["action"]["summary"] for r in rs if r]
    return (len(rs) == N_PROC * N_EACH and None not in rs
            and [r["seq"] for r in rs] == list(range(N_PROC * N_EACH))
            and sorted(got) == sorted(want))


def contention(d: Path) -> None:
    path, errs, read = _race(d, "signed.jsonl", reader=True)
    ok, why = verify_chain(path)
    st, _ = signing.chain_signature(path)
    checks[f"1. {N_PROC} processes x {N_EACH} appends, signed: 100 receipts, seq 0-99, none lost, tip VERIFIED"] = (
        not any(errs) and ok and _complete(path) and st == signing.VERIFIED)
    print(f"  signed race: {why}; signature {st}")
    checks["3. a reader verifying throughout never saw a torn chain"] = (
        read is not None and read["reads"] > 0 and read["bad"] == 0)
    print(f"  reader: {read}")

    env = {k: v for k, v in os.environ.items() if not k.startswith("ANDY_CHAIN_SIGNING")}
    path2, errs2, _ = _race(d, "unsigned.jsonl", env=env)
    st2, _ = signing.chain_signature(path2)
    checks[f"2. {N_PROC} processes x {N_EACH} appends, unsigned: 100 receipts, seq 0-99, verifies, UNSIGNED"] = (
        not any(errs2) and verify_chain(path2)[0] and _complete(path2) and st2 == signing.UNSIGNED)


def timeout_and_crash(d: Path) -> None:
    path, go = d / "held.jsonl", d / "held.go"
    from receipts import ReceiptChain
    ReceiptChain(path).append({"type": "step", "summary": "before"})
    before = (path.read_bytes(), signing.sig_path(path).read_bytes())
    ready = d / "held.ready"
    holder = _spawn("hold", path, go, ready, 4)
    go.write_text("go")
    while not ready.exists():
        time.sleep(0.01)
    t0 = time.time()
    out, _ = _spawn("append-once", path, go, 0.5).communicate(timeout=30)
    waited = time.time() - t0
    holder.communicate(timeout=30)
    checks["4. a held lock makes a writer fail closed: LockTimeout, chain and .sig unchanged"] = (
        out.startswith("TIMEOUT") and (path.read_bytes(), signing.sig_path(path).read_bytes()) == before)
    print(f"  timeout case: {out.strip()} (after {waited:.1f}s)")

    ready2 = d / "crash.ready"
    holder = _spawn("hold", path, go, ready2, 60)
    while not ready2.exists():
        time.sleep(0.01)
    os.kill(holder.pid, signal.SIGKILL)
    holder.wait(timeout=10)
    t0 = time.time()
    out, _ = _spawn("append-once", path, go, 5).communicate(timeout=30)
    checks["5. a writer killed with kill -9 while holding the lock doesn't block the next"] = (
        out.startswith("WROTE") and time.time() - t0 < 5 and verify_chain(path)[0]
        and signing.chain_signature(path)[0] == signing.VERIFIED)


def earned(d: Path) -> None:
    path, go = d / "cs.json", d / "cs.go"
    procs = [_spawn("persist", path, go, f"w{k}", 10) for k in range(2)]
    time.sleep(0.3)
    go.write_text("go")
    errs = [p.communicate(timeout=120)[1] for p in procs]
    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    checks["6. 2 processes x 10 earned-answer approvals at once: all 20 kept, each signed"] = (
        not any(errs) and len(entries) == 20
        and all(signing.verify_entry(e)[0] == signing.VERIFIED for e in entries.values()))
    print(f"  earned answers: {len(entries)} entries kept")


def lock_files(d: Path) -> None:
    left = sorted(p.name for p in d.glob("*.lock"))
    ignore = [l.strip() for l in (ROOT / ".gitignore").read_text().splitlines() if l.strip() and not l.startswith("#")]
    ignored = lambda rel: any(fnmatch.fnmatch(rel, pat.lstrip("/")) or fnmatch.fnmatch(Path(rel).name, pat)
                              for pat in ignore)
    checks["7. lock files stay in place and are git-ignored (runs/*.jsonl.lock, data/*.lock)"] = (
        "signed.jsonl.lock" in left and "cs.json.lock" in left
        and ignored("runs/chat-live.jsonl.lock") and ignored("data/confirmed_secondary.json.lock")
        and ignored("examples/live-demo-chain.jsonl.lock"))


def control(d: Path) -> None:
    path, errs, _ = _race(d, "nolock.jsonl", mode="append-nolock")
    rs = _lines(path)
    seqs = [r["seq"] for r in rs if r]
    print(f"  CONTROL (lock off): {len(rs)} lines, {len(set(seqs))} distinct seqs, "
          f"{len(seqs) - len(set(seqs))} duplicate seq(s), chain {verify_chain(path)[1]!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        contention(d)
        timeout_and_crash(d)
        earned(d)
        lock_files(d)
        control(d)
    print()
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if all(checks.values()):
        print("\nMULTI-PROCESS LOCK ACCEPTANCE: PASS")
        return 0
    print("\nMULTI-PROCESS LOCK ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
