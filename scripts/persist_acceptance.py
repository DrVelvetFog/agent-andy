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
  h. D5: a field of the wrong type (a number, list, or dict where a string belongs —
     verdict, source, quote, url, page_sha256) makes that entry invalid: the place
     stages with the unreadable reason, and the store and the viewer still start.
  i. N1 minimum: a hand-written entry does NOT answer when its url is off-site or
     not in the site index (a made-up place), or, for an indexed place, when its
     verdict is outside the extractor's vocabulary, its sha or dates are malformed,
     approved_by is not "owner", its promote ref is not a receipt hash, or its place
     does not lead to its url through the site-index lookup (a label mismatch).
  j. the legit flow still holds: entries written by confirm() pass the checks, the
     shipped (empty) data/confirmed_secondary.json loads empty, a well-formed entry
     for a Tier 1 place still loses to Tier 1, the "<label>, <state>" place form is
     accepted, and a partial-name approval ("Cocoa" -> the Cocoa Beach page) still
     answers after a restart.
  Every earned answer here is signed, entry by entry, with a throwaway test key, as
  the demo signs with Andy's key, so these shape checks run behind a valid
  signature. An unsigned or forged-signature entry stages on its own:
  signing_acceptance.py.

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
from receipts import ReceiptChain, signing, verify_chain  # noqa: E402
from signing_testkey import use_test_key  # noqa: E402

use_test_key()   # a throwaway key: approvals here are signed, as in the demo


def _write_signed(path, data) -> None:
    """Write hand-made entries, each signed on its own, as approve() would sign them."""
    for k, e in data.get("entries", {}).items():
        sig = signing.sign_entry(e) if isinstance(e, dict) else None
        if sig:
            data["entries"][k] = dict(e, signature=sig)
    vs._write_persist(path, data)

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
    _write_signed(p_c, {"note": "t", "entries": {"myrtle beach": {
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
    _write_signed(p_miss, {"note": "t", "entries": {"daytona beach": {"place": "Daytona Beach"}}})
    o_miss = detect.answer(ch, "Daytona Beach", store=vs.KnowledgeStore(persist_path=p_miss))["outcome"]
    checks["f. an entry missing a field: that place stages with the reason"] = (
        o_miss["decision"] == detect.STAGED and bool(o_miss.get("persist_error")))

    # g. deleting an entry returns the place to staged, with its Tier 2 candidate
    s_g1 = vs.KnowledgeStore(persist_path=p_e)
    checks["g. (setup) the persisted place answers before deletion"] = (
        detect.answer(ch, "Daytona Beach", store=s_g1)["outcome"]["decision"] == detect.ANSWERED_WITH_CAVEAT)
    data = json.loads(p_e.read_text(encoding="utf-8")); data["entries"] = {}
    _write_signed(p_e, data)
    o_g = detect.answer(ch, "Daytona Beach", store=vs.KnowledgeStore(persist_path=p_e))["outcome"]
    checks["g. deleting the entry returns the place to staged, with its Tier 2 candidate"] = (
        o_g["decision"] == detect.STAGED and bool(o_g.get("tier2_candidates")))

    # h / i / j — every variant starts from a real confirm()-written entry
    good = next(iter(e_typed.values()))
    TYBEE = "https://wheretodetect.org/metal-detecting/georgia/tybee-island/"
    JEKYLL = "https://wheretodetect.org/metal-detecting/georgia/jekyll-island/"
    p_v = RUNS / "persist-v-cs.json"
    ch = _chain("persist-v.jsonl")

    def _ask(entry, place, key=None):
        _write_signed(p_v, {"note": "t", "entries": {key or vs._norm(place): entry}})
        try:
            store = vs.KnowledgeStore(persist_path=p_v)
        except Exception as ex:                       # D5: this used to crash on load
            return {"crash": f"{type(ex).__name__}: {ex}"}
        return detect.answer(ch, place, store=store)["outcome"]

    def _refused(entry, place, key=None):
        o = _ask(entry, place, key)
        return ("crash" not in o and o["decision"] == detect.STAGED
                and o.get("persist_error") == "earned answers file unreadable"
                and o["evidence_tier"] != vs.CONFIRMED_SECONDARY)

    d5 = {f"{field}={kind}": dict(good, **{field: bad})
          for field in ("verdict", "source", "quote", "url", "page_sha256")
          for kind, bad in (("number", 7), ("list", ["Allowed"]), ("dict", {"v": "Allowed"}))}
    d5_ok = {name: _refused(e, "Daytona Beach") for name, e in d5.items()}
    checks["h. D5: a number/list/dict in verdict, source, quote, url, or page_sha256 is invalid, no crash"] = (
        all(d5_ok.values()) and len(d5_ok) == 15)
    _write_signed(p_v, {"note": "t", "entries": {"daytona beach": dict(good, verdict=7)}})
    try:
        srv = andy_viewer.build_server(8789, chat_chain="persist-v-viewer.jsonl", reset=True, persist_path=p_v)
        srv.server_close()
        viewer_up = True
    except Exception:
        viewer_up = False
    checks["h. D5: the viewer starts with a non-string verdict in the file"] = viewer_up

    fake_hex = "a" * 64
    forged = dict(good, place="Narnia", url="https://wheretodetect.org/metal-detecting/narnia/narnia/")
    n1 = {
        "made-up place, out-of-index url": (forged, "Narnia"),
        "off-site url": (dict(good, url="https://evil.example/daytona-beach/"), "Daytona Beach"),
        "verdict outside the vocabulary": (dict(good, verdict="Totally fine"), "Daytona Beach"),
        "bad sha (short)": (dict(good, page_sha256="abc123"), "Daytona Beach"),
        "bad sha (upper-case)": (dict(good, page_sha256=good["page_sha256"].upper()), "Daytona Beach"),
        "bad date (not a date)": (dict(good, approval_date="Oct 28"), "Daytona Beach"),
        "bad date (impossible)": (dict(good, verified_date="2026-13-45"), "Daytona Beach"),
        "approved_by not owner": (dict(good, approved_by="admin"), "Daytona Beach"),
        "promote ref not a receipt hash": (dict(good, verify_promote_ref="r"), "Daytona Beach"),
        "place/url label mismatch (Tybee on the Daytona page)": (dict(good, place="Tybee Island"), "Tybee Island"),
    }
    n1_ok = {name: _refused(e, place) for name, (e, place) in n1.items()}
    checks["i. N1: a made-up place with an out-of-index url does NOT answer"] = n1_ok["made-up place, out-of-index url"]
    checks["i. N1: an off-site url does NOT answer"] = n1_ok["off-site url"]
    checks["i. N1: bad verdict / sha / date / approved_by / promote ref does NOT answer"] = all(
        n1_ok[k] for k in n1 if k.startswith(("verdict", "bad", "approved", "promote")))
    checks["i. N1: a place/url label mismatch does NOT answer"] = n1_ok["place/url label mismatch (Tybee on the Daytona page)"]

    checks["j. legit: both confirm()-written entries (typed + button) pass the checks"] = all(
        vs._entry_problem(e) is None for e in list(e_typed.values()) + list(e_btn.values()))
    shipped = vs.KnowledgeStore(persist_path=ROOT / "data" / "confirmed_secondary.json")
    checks["j. legit: the shipped data/confirmed_secondary.json loads as empty"] = (
        shipped.confirmed == {} and shipped.persist_error is None and shipped.invalid_places == set())
    jek = dict(good, place="Jekyll Island", url=JEKYLL, verdict="Allowed")
    o_j = _ask(jek, "Jekyll Island")
    checks["j. legit: a well-formed entry for a Tier 1 place still loses to Tier 1"] = (
        vs._entry_problem(jek) is None and "crash" not in o_j and o_j["rule_verdict"] == "restricted"
        and o_j["evidence_tier"] != vs.CONFIRMED_SECONDARY)
    o_st = _ask(dict(good, place="Daytona Beach, Florida"), "Daytona Beach, Florida")
    checks["j. legit: the '<label>, <state>' place form still answers"] = (
        "crash" not in o_st and o_st["decision"] == detect.ANSWERED_WITH_CAVEAT)
    p_pn = RUNS / "persist-pn-cs.json"; p_pn.unlink(missing_ok=True)
    ch_pn = _chain("persist-pn.jsonl")
    vs.fetch = _ok_fetch
    try:
        s_pn = vs.KnowledgeStore(persist_path=p_pn)
        detect.answer(ch_pn, "Cocoa", store=s_pn)          # Tier 2 offers the Cocoa Beach page
        s_pn.propose(ch_pn); s_pn.confirm(ch_pn)
    finally:
        vs.fetch = saved
    o_pn = detect.answer(ch_pn, "Cocoa", store=vs.KnowledgeStore(persist_path=p_pn))["outcome"]
    checks["j. legit: a partial-name approval ('Cocoa' -> Cocoa Beach page) still answers after restart"] = (
        o_pn["decision"] == detect.ANSWERED_WITH_CAVEAT and o_pn["evidence_tier"] == vs.CONFIRMED_SECONDARY)
    p_pn.unlink(missing_ok=True)

    print("  D5 variants:", ", ".join(f"{k}->{'staged' if v else 'ANSWERED/CRASH'}" for k, v in d5_ok.items()))
    print("  N1 variants:")
    for name, (e, _place) in n1.items():
        print(f"    [{'staged' if n1_ok[name] else 'ANSWERED'}] {name}: {vs._entry_problem(e)}")
    residual = dict(good, place="Tybee Island", url=TYBEE, verdict="Allowed", page_sha256=fake_hex,
                    verify_promote_ref=fake_hex)
    o_r = _ask(residual, "Tybee Island")
    print(f"  NOTE (not a check): a well-formed Tybee entry SIGNED with the key -> "
          f"{o_r.get('decision')} '{o_r.get('rule_verdict')}' — the signature is the proof of approval, so "
          "only the key holder can add one; unsigned forgeries stage (signing_acceptance.py).\n")
    p_v.unlink(missing_ok=True)

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
