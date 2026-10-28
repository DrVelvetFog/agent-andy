#!/usr/bin/env python3
"""Persistence acceptance — earned answers survive a new session, still below Tier 1.

An approved confirmed-secondary answer is written to a SEPARATE, labeled file
(data/confirmed_secondary.json), loaded on a new session, and answered from the
file with its caveat and approval date — never merged into Tier 1, never re-fetched
automatically. Every property the scope fix must hold, by name:

  a. approve (typed AND via the real server/button path) writes an entry with every
     required field, and data/detect_sample.toml (Tier 1) is byte-identical.
  b. a fresh process (new KnowledgeStore, no re-fetch) answers the same place from
     the persisted entry, with its caveat, approval date, and the verify_promote
     reference in the receipt.
  c. a place in both Tier 1 and the file answers from Tier 1.
  d. decline writes nothing to the file.
  e. a second approval updates one entry, never duplicates.
  f. a malformed file (or an entry missing a field) stages the affected place with
     the unreadable reason, never answers from it, never crashes.
  g. deleting an entry returns that place to staged, with its Tier 2 candidate.

Temp persist files live under runs/ (gitignored); fetch is monkeypatched so the
core is hermetic while the index-only fetch restriction still applies.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "viewer"))

import andy_viewer  # noqa: E402
from agent import detect, verify_source as vs  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
TIER1 = ROOT / "data" / "detect_sample.toml"
DAYTONA = "https://wheretodetect.org/metal-detecting/florida/daytona-beach/"
COCOA = "https://wheretodetect.org/metal-detecting/florida/cocoa-beach/"
FX = ("<html><body><div>X County ✅ Allowed Last verified: 2026-09-15</div>"
      "<h2>The rules</h2><p>Detecting is allowed on the public beach.</p>"
      "<div>Permit: Not required</div>"
      "<p>Source: X County Code of Ordinances, Ch. 20, Sec. 20-6. Verify against the county.</p>"
      "</body></html>")


def _ok_fetch(url, timeout=30.0):
    return {"ok": True, "html": FX, "sha256": hashlib.sha256(FX.encode()).hexdigest(),
            "bytes": len(FX.encode())}


def _boom(*a, **k):
    raise RuntimeError("persisted answers must not re-fetch")


def _entries(path):
    return json.loads(Path(path).read_text(encoding="utf-8")).get("entries", {}) if Path(path).exists() else {}


def _chain(name):
    p = RUNS / name
    p.unlink(missing_ok=True)
    return ReceiptChain(p)


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    saved = vs.fetch
    sample_before = hashlib.sha256(TIER1.read_bytes()).hexdigest()
    checks = {}

    # a. typed approve writes a full entry
    p_typed = RUNS / "persist-typed-cs.json"; p_typed.unlink(missing_ok=True)
    ch = _chain("persist-a.jsonl")
    vs.fetch = _ok_fetch
    try:
        s = vs.KnowledgeStore(persist_path=p_typed)
        s.propose(ch, "Daytona Beach", DAYTONA)
        s.confirm(ch, "Daytona Beach")
    finally:
        vs.fetch = saved
    e_typed = _entries(p_typed)
    checks["a. typed approve writes one entry with every required field"] = (
        len(e_typed) == 1 and all(all(v.get(k) for k in vs._REQUIRED) for v in e_typed.values()))

    # a. button/server approve writes a full entry
    p_btn = RUNS / "persist-btn-cs.json"; p_btn.unlink(missing_ok=True)
    vs.fetch = _ok_fetch
    server = andy_viewer.build_server(8797, chat_chain="persist-btn.jsonl", reset=True, persist_path=p_btn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        def _post(msg):
            req = urllib.request.Request("http://127.0.0.1:8797/api/chat",
                                         data=json.dumps({"message": msg, "voice": False}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        _post("can I detect at Daytona Beach?"); _post("verify it"); _post("approve Daytona Beach")
    finally:
        server.shutdown()
        vs.fetch = saved
    e_btn = _entries(p_btn)
    checks["a. server/button approve writes one entry with every required field"] = (
        len(e_btn) == 1 and all(all(v.get(k) for k in vs._REQUIRED) for v in e_btn.values()))
    checks["a. Tier 1 fixture (detect_sample.toml) is byte-identical"] = (
        hashlib.sha256(TIER1.read_bytes()).hexdigest() == sample_before)

    # b. fresh session, no re-fetch, answers from the persisted entry
    ch = _chain("persist-b.jsonl")
    vs.fetch = _boom
    try:
        s2 = vs.KnowledgeStore(persist_path=p_typed)
        res = detect.answer(ch, "Daytona Beach", store=s2)
    finally:
        vs.fetch = saved
    o = res["outcome"]; rc = res["answer_receipt"]["action"]
    checks["b. a fresh session answers from the persisted entry (no re-fetch)"] = (
        o["decision"] == detect.ANSWERED_WITH_CAVEAT and o["evidence_tier"] == vs.CONFIRMED_SECONDARY
        and "confirm the primary" in o["caveat"].lower() and bool(o.get("approval_date")))
    checks["b. the receipt carries the verify_promote reference + approval date + page hash"] = (
        bool(rc.get("verify_promote_ref")) and bool(rc.get("approval_date")) and bool(rc.get("page_sha256")))

    # c. a Tier 1 place answers from Tier 1, not the persisted file
    p_c = RUNS / "persist-c-cs.json"
    vs._write_persist(p_c, {"note": "t", "entries": {"myrtle beach": {
        "place": "Myrtle Beach", "url": DAYTONA, "page_sha256": "x", "verdict": "Prohibited",
        "quote": "q", "source": "s", "verified_date": "2026-09-15", "approval_date": "2026-10-28",
        "approved_by": "owner", "caveat": "c", "verify_promote_ref": "r"}}})
    ch = _chain("persist-c.jsonl")
    o_c = detect.answer(ch, "Myrtle Beach", store=vs.KnowledgeStore(persist_path=p_c))["outcome"]
    checks["c. a Tier 1 place answers from Tier 1, not the persisted entry"] = (
        o_c["rule_verdict"] == "allowed" and o_c["evidence_tier"] != vs.CONFIRMED_SECONDARY)

    # d. decline writes nothing
    p_d = RUNS / "persist-d-cs.json"; p_d.unlink(missing_ok=True)
    ch = _chain("persist-d.jsonl")
    vs.fetch = _ok_fetch
    try:
        s_d = vs.KnowledgeStore(persist_path=p_d)
        s_d.propose(ch, "Cocoa Beach", COCOA)
        s_d.decline(ch, "Cocoa Beach")
    finally:
        vs.fetch = saved
    checks["d. decline writes nothing to the persisted file"] = (_entries(p_d) == {})

    # e. a second approval updates one entry, never duplicates
    p_e = RUNS / "persist-e-cs.json"; p_e.unlink(missing_ok=True)
    ch = _chain("persist-e.jsonl")
    vs.fetch = _ok_fetch
    try:
        s_e = vs.KnowledgeStore(persist_path=p_e)
        s_e.propose(ch, "Daytona Beach", DAYTONA); s_e.confirm(ch, "Daytona Beach")
        s_e.propose(ch, "Daytona Beach", DAYTONA); s_e.confirm(ch, "Daytona Beach")
    finally:
        vs.fetch = saved
    checks["e. a second approval updates one entry, never duplicates"] = (len(_entries(p_e)) == 1)

    # f. malformed file + entry-missing-field -> staged with the reason, no crash
    p_bad = RUNS / "persist-bad-cs.json"
    p_bad.write_text("not valid json {{{", encoding="utf-8")
    ch = _chain("persist-f.jsonl")
    o_bad = detect.answer(ch, "Daytona Beach", store=vs.KnowledgeStore(persist_path=p_bad))["outcome"]
    checks["f. malformed file: stages with 'earned answers file unreadable', never answers"] = (
        o_bad["decision"] == detect.STAGED and o_bad.get("persist_error") == "earned answers file unreadable")
    p_miss = RUNS / "persist-miss-cs.json"
    vs._write_persist(p_miss, {"note": "t", "entries": {"daytona beach": {"place": "Daytona Beach"}}})
    o_miss = detect.answer(ch, "Daytona Beach", store=vs.KnowledgeStore(persist_path=p_miss))["outcome"]
    checks["f. an entry missing a field: that place stages with the reason"] = (
        o_miss["decision"] == detect.STAGED and bool(o_miss.get("persist_error")))

    # g. deleting an entry returns the place to staged, with its Tier 2 candidate
    s_g1 = vs.KnowledgeStore(persist_path=p_e)
    checks["g. (setup) the persisted place answers before deletion"] = (
        detect.answer(ch, "Daytona Beach", store=s_g1)["outcome"]["decision"] == detect.ANSWERED_WITH_CAVEAT)
    data = json.loads(p_e.read_text(encoding="utf-8")); data["entries"] = {}
    vs._write_persist(p_e, data)
    o_g = detect.answer(ch, "Daytona Beach", store=vs.KnowledgeStore(persist_path=p_e))["outcome"]
    checks["g. deleting the entry returns the place to staged, with its Tier 2 candidate"] = (
        o_g["decision"] == detect.STAGED and bool(o_g.get("tier2_candidates")))

    ok, _ = verify_chain(RUNS / "persist-e.jsonl")
    checks["a receipt chain verifies end to end"] = ok

    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if all(checks.values()):
        print("\nPERSISTENCE ACCEPTANCE: PASS")
        return 0
    print("\nPERSISTENCE ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
