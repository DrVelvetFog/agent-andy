#!/usr/bin/env python3
"""Verify-on-demand acceptance — Andy earns knowledge, with proof, on approval.

The properties that keep this honest, every one tested:

  1. Extraction is DETERMINISTIC and fail-closed: a templated page yields the
     verdict, a VERBATIM rule quote, the named source and the date; a page whose
     structure is missing yields nothing (no guess).
  2. A quote Andy reports is a verbatim substring of the page it fetched.
  3. Fetch and extract are STAGED for the owner, not acted on: the place does not
     answer until the owner approves it.
  4. On approval the place answers as a CONFIRMED SECONDARY — it names a primary,
     is labeled "I read the site, not the ordinance", and is never Tier-1 grade.
  5. A fetch or extraction that fails leaves the place staged, not promoted.
  6. Every step is a receipt (verify_fetch / verify_extract / verify_promote) and
     the chain verifies.

The core runs hermetically against a fixture page (fetch monkeypatched); one live
fetch of a real page is reported at the end as a bonus.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import detect, verify_source as vs  # noqa: E402
from agent.verify_source import KnowledgeStore  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "verify-receipts.jsonl"

FIXTURE = """<html><body>
<h1>Can You Metal Detect at Testville Beach? Yes</h1>
<div>Testville County &middot; Central &middot; City beach ✅ Allowed Last verified: 2026-09-15</div>
<h2>The rules</h2>
<p>The Testville Beach Code says nothing about metal detecting and permits it on the public beach.</p>
<div>Permit: Not required</div>
<p>Source: Testville County Code of Ordinances, Ch. 20, Sec. 20-6. Verify against the county.</p>
<p>Not legal advice.</p></body></html>"""

GARBAGE = "<html><body><h1>Hello</h1><p>nothing structured here</p></body></html>"
NO_SOURCE = """<html><body><div>✅ Allowed Last verified: 2026-09-15</div>
<h2>The rules</h2><p>It is allowed here.</p><div>Permit: Not required</div></body></html>"""


def _fixture_fetch(html):
    return lambda url, timeout=30.0: {"ok": True, "html": html,
                                      "sha256": hashlib.sha256(html.encode()).hexdigest(),
                                      "bytes": len(html.encode())}


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)
    chain = ReceiptChain(CHAIN)
    checks = {}

    # 1 + 2. Deterministic extraction + verbatim.
    ex = vs.extract(FIXTURE)
    text = vs._text(FIXTURE)
    checks["1. extraction reads verdict/quote/source/date from a templated page"] = (
        ex["ok"] and ex["verdict"] == "Allowed" and ex["verified_date"] == "2026-09-15"
        and "Testville Beach Code" in ex["quote"] and "Testville County Code" in ex["source"])
    checks["2. the reported quote + source are verbatim in the page"] = (
        ex["ok"] and ex["quote"] in text and ex["source"] in text)
    checks["1. a page with no recognizable structure fails closed"] = (not vs.extract(GARBAGE)["ok"])
    checks["1. a page missing the source fails closed (no partial promote)"] = (not vs.extract(NO_SOURCE)["ok"])

    place = "Testville Beach"
    store = KnowledgeStore()

    # 3. Before approval: staged, not answered.
    o0 = detect.answer(chain, place, store=store)["outcome"]
    checks["3. before verifying, the place is STAGED (not answered)"] = (o0["decision"] == detect.STAGED)

    # Propose (fetch + extract) against the fixture — staged for approval.
    saved = vs.fetch
    vs.fetch = _fixture_fetch(FIXTURE)
    try:
        prop = store.propose(chain, place, "https://example.test/testville")
    finally:
        vs.fetch = saved
    checks["3. verify fetch+extract are staged, not an answer yet"] = (
        prop["ok"] and store.get(place) is None)
    o_mid = detect.answer(chain, place, store=store)["outcome"]
    checks["3. a pending (un-approved) proposal does NOT answer"] = (o_mid["decision"] == detect.STAGED)

    # 4. Approve -> confirmed secondary answer.
    conf = store.confirm(chain, place)
    o1 = detect.answer(chain, place, store=store)["outcome"]
    cit = o1.get("citation") or {}
    checks["4. after approval it answers as a confirmed secondary"] = (
        conf["ok"] and o1["decision"] == detect.ANSWERED_WITH_CAVEAT
        and o1["evidence_tier"] == vs.CONFIRMED_SECONDARY)
    checks["4. the answer names a primary, cites the page URL + verbatim quote"] = (
        cit.get("url", "").startswith("http") and cit.get("quote", "") in text
        and "secondary" in (cit.get("source", "") + (o1.get("caveat") or "")).lower())
    checks["4. it is labeled not-the-ordinance, confirm-the-primary (not Tier 1)"] = (
        "primary" in (o1.get("caveat") or "").lower()
        and o1["evidence_tier"] != "primary")

    # 5. A failed extraction never promotes.
    store2 = KnowledgeStore()
    vs.fetch = _fixture_fetch(GARBAGE)
    try:
        bad = store2.propose(chain, "Nowhere Beach", "https://example.test/nowhere")
    finally:
        vs.fetch = saved
    checks["5. a failed extraction stays staged, never promoted"] = (
        (not bad["ok"]) and store2.get("Nowhere Beach") is None)

    # 6. Receipts + chain.
    types = [r["action"]["type"] for r in chain.receipts()]
    checks["6. fetch / extract / promote are each receipted"] = all(
        t in types for t in ("verify_fetch", "verify_extract", "verify_promote"))
    ex_rcpt = next(r["action"] for r in chain.receipts() if r["action"]["type"] == "verify_extract")
    checks["6. the extract receipt is staged-for-approval, not executed"] = (
        ex_rcpt.get("staged_for_approval") is True and ex_rcpt.get("executed") is False
        and ex_rcpt.get("verbatim_in_page") is True)
    ok, reason = verify_chain(CHAIN)
    checks["6. chain verifies end to end"] = ok

    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    # Bonus: a real fetch of a live page (informational — needs network).
    live = vs.fetch("https://wheretodetect.org/metal-detecting/florida/daytona-beach/")
    if live["ok"]:
        lex = vs.extract(live["html"])
        print(f"\n  live check: Daytona Beach -> extract ok={lex['ok']} "
              f"verdict={lex.get('verdict')} (quote verbatim={lex.get('quote','') in vs._text(live['html'])})")
    else:
        print(f"\n  live check skipped (no network): {live['error']}")

    if all(checks.values()):
        print("\nVERIFY-ON-DEMAND ACCEPTANCE: PASS")
        return 0
    print("\nVERIFY-ON-DEMAND ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
