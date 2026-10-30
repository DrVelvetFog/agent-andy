#!/usr/bin/env python3
"""Chain-tip and earned-answer signing acceptance (N3).

Signs with a THROWAWAY Ed25519 key made in a temp dir (scripts/signing_testkey.py),
never Andy's real key. A second throwaway key plays the forger.

  A. Chains
     1. a chain written with the key reads signature VERIFIED (and so does the CLI)
     2. one flipped byte: the hash check FAILs
     3. a full rewrite with every hash recomputed: hashes PASS, signature FAILs
        (the hole signing closes)
     4. a tampered signature FAILs
     5. a truncated tail FAILs against its signature
     6. a chain signed by a different key FAILs
     7. an unsigned chain reads UNSIGNED, hashes still checked; the CLI exits 0, or
        2 with --require-signature
     8. appending without the key removes the stale signature: UNSIGNED, never a
        stale VERIFIED
     9. the viewer reports the same three states, and a rotated chain keeps its
        signature
  B. Earned answers (data/confirmed_secondary.json), each entry signed on its own;
     every case has two entries, and the untouched one must still answer
     1. each approval signs its own entry; a fresh session answers both
     2. a forged entry with no signature stages alone
     3. an entry signed by a different key stages alone
     4. an entry edited by hand stages alone
     5. a tampered signature stages alone
     6. revoking one entry by deleting it stages only that place
     7. an approval without the key leaves that entry UNSIGNED; it stages alone
     8. no laundering: an approval signs only its own entry
     9. the old whole-file format is never answered; an approval removes its
        leftover .sig
    10. the shipped, empty earned-answers file loads clean
  C. The public example
     1. examples/live-demo-chain.jsonl verifies against data/andy-chain-signing.pub,
        with no key set
     2. one flipped character FAILs it, naming the receipt
     3. no private key material is anywhere in the repo

Local only: ssh-keygen, no network, no model.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "viewer"))

from signing_testkey import use_test_key  # noqa: E402

TEST_KEY = use_test_key()

import andy_viewer  # noqa: E402
from agent import detect, verify_source as vs  # noqa: E402
from receipts import GENESIS, ReceiptChain, digest, signing, verify_chain  # noqa: E402

CLI = ROOT / "scripts" / "verify_receipts.py"
EXAMPLE = ROOT / "examples" / "live-demo-chain.jsonl"
DAYTONA = "https://wheretodetect.org/metal-detecting/florida/daytona-beach/"
checks: dict[str, bool] = {}


def _cli(path, *extra, env=None):
    r = subprocess.run([sys.executable, str(CLI), str(path), *extra], capture_output=True,
                       text=True, env=env or os.environ.copy())
    return r.returncode, r.stdout


def _other_key(d: Path) -> Path:
    k = d / "forger_key"
    if not k.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "forger", "-f", str(k)],
                       check=True, stdin=subprocess.DEVNULL)
    return k


def _with_key(key: Path | None):
    """Point signing at another key (or none) for one block."""
    class _K:
        def __enter__(self):
            self.old = os.environ.get("ANDY_CHAIN_SIGNING_KEY")
            if key is None:
                os.environ.pop("ANDY_CHAIN_SIGNING_KEY", None)
            else:
                os.environ["ANDY_CHAIN_SIGNING_KEY"] = str(key)

        def __exit__(self, *a):
            if self.old is None:
                os.environ.pop("ANDY_CHAIN_SIGNING_KEY", None)
            else:
                os.environ["ANDY_CHAIN_SIGNING_KEY"] = self.old
    return _K()


def _signed_chain(path: Path, n: int = 6) -> ReceiptChain:
    path.unlink(missing_ok=True)
    signing.sig_path(path).unlink(missing_ok=True)
    c = ReceiptChain(path)
    for i in range(n):
        c.append({"type": "step", "summary": f"benign step {i}"})
    return c


def _copy(src: Path, dst: Path, lines=None, sig=True) -> Path:
    text = src.read_text(encoding="utf-8") if lines is None else "\n".join(lines) + "\n"
    dst.write_text(text, encoding="utf-8")
    signing.sig_path(dst).unlink(missing_ok=True)
    if sig and signing.sig_path(src).exists():
        signing.sig_path(dst).write_text(signing.sig_path(src).read_text())
    return dst


def chains(d: Path) -> None:
    c = _signed_chain(d / "a.jsonl")
    st, _ = signing.chain_signature(c.path)
    rc, out = _cli(c.path)
    checks["A1. a chain written with the key reads signature VERIFIED (CLI too, exit 0)"] = (
        verify_chain(c.path)[0] and st == signing.VERIFIED and rc == 0 and "signature: VERIFIED" in out)

    lines = c.path.read_text().splitlines()
    flipped = lines[:]
    flipped[3] = flipped[3].replace("benign step 3", "benign step 9")
    f = _copy(c.path, d / "flip.jsonl", flipped)
    rc, out = _cli(f)
    checks["A2. one flipped byte: the hash check FAILs (CLI exit 1)"] = (
        not verify_chain(f)[0] and rc == 1 and out.startswith("chain:") and "FAIL" in out)

    # Rewrite receipt 2 and recompute every hash after it: a perfect hash chain.
    rewritten, prev = [], GENESIS
    for i, line in enumerate(lines):
        r = json.loads(line)
        if i == 2:
            r["action"]["summary"] = "wire $5,000 (rewritten history)"
        body = {"seq": r["seq"], "ts": r["ts"], "action": r["action"], "prev": prev}
        r = dict(body, hash=digest(body))
        prev = r["hash"]
        rewritten.append(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    rw = _copy(c.path, d / "rewrite.jsonl", rewritten)
    st, _ = signing.chain_signature(rw)
    rc, out = _cli(rw)
    checks["A3. a full rewrite with recomputed hashes: hashes PASS, signature FAILs"] = (
        verify_chain(rw)[0] and st == signing.FAIL and rc == 1 and "FAIL — signature" in out)

    ts = _copy(c.path, d / "tsig.jsonl")
    s = signing.sig_path(ts).read_text().splitlines()
    s[2] = ("B" if s[2][0] != "B" else "C") + s[2][1:]
    signing.sig_path(ts).write_text("\n".join(s) + "\n")
    checks["A4. a tampered signature FAILs"] = signing.chain_signature(ts)[0] == signing.FAIL

    tr = _copy(c.path, d / "trunc.jsonl", lines[:4])
    checks["A5. a truncated tail FAILs against its signature (hashes alone pass)"] = (
        verify_chain(tr)[0] and signing.chain_signature(tr)[0] == signing.FAIL)

    with _with_key(_other_key(d)):
        o = _signed_chain(d / "other.jsonl")
    checks["A6. a chain signed by a different key FAILs"] = (
        verify_chain(o.path)[0] and signing.chain_signature(o.path)[0] == signing.FAIL)

    u = _copy(c.path, d / "unsigned.jsonl", sig=False)
    rc0, out0 = _cli(u)
    rc2, _ = _cli(u, "--require-signature")
    uf = _copy(c.path, d / "unsigned-flip.jsonl", flipped, sig=False)
    checks["A7. an unsigned chain reads UNSIGNED, hashes still checked (exit 0; 2 if required)"] = (
        signing.chain_signature(u)[0] == signing.UNSIGNED and rc0 == 0 and "signature: UNSIGNED" in out0
        and rc2 == 2 and not verify_chain(uf)[0] and _cli(uf)[0] == 1)

    s8 = _signed_chain(d / "stale.jsonl")
    with _with_key(None):
        s8.append({"type": "step", "summary": "appended with no key"})
    checks["A8. appending without the key removes the stale signature: UNSIGNED"] = (
        not signing.sig_path(s8.path).exists() and verify_chain(s8.path)[0]
        and signing.chain_signature(s8.path)[0] == signing.UNSIGNED)

    v_ok = andy_viewer.verify_with_signature(c.path)
    v_un = andy_viewer.verify_with_signature(u)
    v_rw = andy_viewer.verify_with_signature(rw)
    v_fl = andy_viewer.verify_with_signature(f)
    r9 = _signed_chain(d / "rot.jsonl")
    dest = andy_viewer._rotate(r9.path)
    checks["A9. the viewer reports VERIFIED / UNSIGNED / FAIL; a rotated chain keeps its signature"] = (
        v_ok["ok"] and v_ok["signature"] == "VERIFIED" and v_un["ok"] and v_un["signature"] == "UNSIGNED"
        and not v_rw["ok"] and v_rw["signature"] == "FAIL" and not v_fl["ok"]
        and dest is not None and not signing.sig_path(r9.path).exists()
        and andy_viewer.verify_with_signature(dest)["signature"] == "VERIFIED")


PLACES = {"Daytona Beach": DAYTONA,
          "Cocoa Beach": "https://wheretodetect.org/metal-detecting/florida/cocoa-beach/"}


def _approve(path: Path, chain, place="Daytona Beach") -> dict:
    store = vs.KnowledgeStore(persist_path=path)
    store.pending[vs._norm(place)] = {
        "place": place, "url": PLACES[place], "verdict": "Allowed",
        "quote": "Metal detecting is allowed on the beach.", "source": f"City of {place}",
        "verified_date": "2026-10-28", "page_sha256": "b" * 64}
    return store.confirm(chain, place)


def _outcome(path: Path, chain, place="Daytona Beach") -> dict:
    return detect.answer(chain, place, store=vs.KnowledgeStore(persist_path=path))["outcome"]


def _answered(o) -> bool:
    return o["decision"] in (detect.ANSWERED, detect.ANSWERED_WITH_CAVEAT)


def _entries(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def _with_entries(src: Path, dst: Path, change) -> Path:
    """Copy src's entries to dst, let change() edit them, write dst as-is (no signing)."""
    entries = _entries(src)
    change(entries)
    vs._write_persist(dst, {"note": "t", "entries": entries})
    return dst


def _one_stages(path: Path, chain, bad: str, why: str) -> bool:
    """`bad` stages with a reason containing `why`; the other place still answers."""
    o_bad = _outcome(path, chain, bad)
    o_ok = _outcome(path, chain, "Cocoa Beach" if bad == "Daytona Beach" else "Daytona Beach")
    return (o_bad["decision"] == detect.STAGED and why in (o_bad.get("persist_error") or "")
            and _answered(o_ok))


def earned_answers(d: Path) -> None:
    ch = ReceiptChain(d / "earned.jsonl")
    p = d / "cs.json"
    res = [_approve(p, ch, place) for place in PLACES]
    both = _entries(p)
    checks["B1. each approval signs its own entry; a fresh session answers both"] = (
        all(r.get("signed") is True for r in res)
        and all(signing.verify_entry(e)[0] == signing.VERIFIED for e in both.values())
        and all(_answered(_outcome(p, ch, place)) for place in PLACES)
        and not signing.sig_path(p).exists())

    def forge(entries):   # a well-formed entry nobody signed
        entries["daytona beach"].pop("signature")
    checks["B2. a forged entry with no signature stages alone; the other answers"] = _one_stages(
        _with_entries(p, d / "forged.json", forge), ch, "Daytona Beach", "UNSIGNED")

    def foreign(entries):
        e = {k: v for k, v in entries["daytona beach"].items() if k != "signature"}
        with _with_key(_other_key(d)):
            entries["daytona beach"] = dict(e, signature=signing.sign_entry(e))
    checks["B3. an entry signed by a different key stages alone; the other answers"] = _one_stages(
        _with_entries(p, d / "foreign.json", foreign), ch, "Daytona Beach", "FAIL")

    def edit(entries):    # change the content, keep the old signature
        entries["daytona beach"]["verdict"] = "Prohibited"
    checks["B4. an entry edited by hand stages alone; the other answers"] = _one_stages(
        _with_entries(p, d / "edited.json", edit), ch, "Daytona Beach", "FAIL")

    def bad_sig(entries):  # change the signature, keep the content
        lines = entries["daytona beach"]["signature"].splitlines()
        lines[2] = ("B" if lines[2][0] != "B" else "C") + lines[2][1:]
        entries["daytona beach"]["signature"] = "\n".join(lines) + "\n"
    checks["B5. a tampered signature stages alone; the other answers"] = _one_stages(
        _with_entries(p, d / "badsig.json", bad_sig), ch, "Daytona Beach", "FAIL")

    def revoke(entries):  # the owner deletes one entry by hand
        del entries["daytona beach"]
    rv = _with_entries(p, d / "revoked.json", revoke)
    o_gone, o_kept = _outcome(rv, ch, "Daytona Beach"), _outcome(rv, ch, "Cocoa Beach")
    checks["B6. revoking one entry (deleting it) stages only that place; the other answers"] = (
        o_gone["decision"] == detect.STAGED and not o_gone.get("persist_error") and _answered(o_kept)
        and signing.verify_entry(_entries(rv)["cocoa beach"])[0] == signing.VERIFIED)

    p7 = d / "nokey.json"
    _approve(p7, ch, "Cocoa Beach")
    with _with_key(None):
        r7 = _approve(p7, ch, "Daytona Beach")
    checks["B7. an approval without the key leaves that entry UNSIGNED; it stages alone after restart"] = (
        r7.get("ok") and r7.get("signed") is False and "signature" not in _entries(p7)["daytona beach"]
        and _one_stages(p7, ch, "Daytona Beach", "UNSIGNED"))

    p8 = d / "launder.json"
    tybee = dict({k: v for k, v in both["daytona beach"].items() if k != "signature"},
                 place="Tybee Island", url="https://wheretodetect.org/metal-detecting/georgia/tybee-island/")
    vs._write_persist(p8, {"note": "t", "entries": {"tybee island": tybee}})
    _approve(p8, ch, "Daytona Beach")
    after = _entries(p8)
    checks["B8. no laundering: an approval signs only its own entry, never an unsigned one"] = (
        "signature" not in after["tybee island"]
        and signing.verify_entry(after["daytona beach"])[0] == signing.VERIFIED
        and _outcome(p8, ch, "Tybee Island")["decision"] == detect.STAGED
        and _answered(_outcome(p8, ch, "Daytona Beach")))

    p9 = d / "oldformat.json"   # the earlier format: no per-entry signature, a whole-file .sig
    _with_entries(p, p9, lambda es: [e.pop("signature") for e in es.values()])
    signing.sig_path(p9).write_text(signing.sig_path(p9).name)   # any leftover sidecar
    staged9 = [_outcome(p9, ch, place)["decision"] == detect.STAGED for place in PLACES]
    _approve(p9, ch, "Cocoa Beach")
    checks["B9. the old whole-file format is never answered; an approval removes its leftover .sig"] = (
        all(staged9) and not signing.sig_path(p9).exists()
        and _answered(_outcome(p9, ch, "Cocoa Beach"))
        and _outcome(p9, ch, "Daytona Beach")["decision"] == detect.STAGED)

    shipped = vs.KnowledgeStore(persist_path=ROOT / "data" / "confirmed_secondary.json")
    checks["B10. the shipped, empty earned-answers file loads clean"] = (
        shipped.confirmed == {} and shipped.persist_error is None and shipped.signature_problems == {})


def public_example(d: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANDY_CHAIN_SIGNING")}
    rc, out = _cli(EXAMPLE, "--require-signature", env=env)
    checks["C1. the live example verifies against data/andy-chain-signing.pub with no key set"] = (
        rc == 0 and "signature: VERIFIED" in out and "andy-chain-signing.pub" in out)
    print("  example:", out.strip().replace("\n", " | "))

    lines = EXAMPLE.read_text(encoding="utf-8").splitlines()
    i = next(n for n, l in enumerate(lines) if "READY TO SHIP" in l)
    lines[i] = lines[i].replace("READY TO SHIP", "rEADY TO SHIP", 1)
    f = _copy(EXAMPLE, d / "example-flip.jsonl", lines)
    rc, out = _cli(f, env=env)
    checks["C2. one flipped character FAILs the example, naming the receipt"] = (
        rc == 1 and f"receipt {i}: hash does not recompute" in out)
    print(f"  example flipped at receipt {i}:", out.strip().splitlines()[1])

    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if not files:   # not a git checkout: scan the tree, skipping generated output
        files = [str(q.relative_to(ROOT)) for q in ROOT.rglob("*") if q.is_file()
                 and not {".git", "runs", "AgentAndy.app"} & set(q.relative_to(ROOT).parts)]
    marker = b"PRIVATE " + b"KEY-----"   # split so this file doesn't match itself
    leaked = [t for t in files if (ROOT / t).is_file() and marker in (ROOT / t).read_bytes()]
    try:
        pub = (ROOT / "data" / "andy-chain-signing.pub").read_text().split()
    except OSError:
        pub = []
    checks["C3. no private key material is in the repo; the shipped key is a public ed25519 key"] = (
        bool(files) and not leaked and len(pub) >= 2 and pub[0] == "ssh-ed25519")


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        chains(d)
        earned_answers(d)
        public_example(d)
    print()
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if all(checks.values()):
        print("\nSIGNING ACCEPTANCE: PASS")
        return 0
    print("\nSIGNING ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
