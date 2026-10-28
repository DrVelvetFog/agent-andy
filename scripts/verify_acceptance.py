#!/usr/bin/env python3
"""Verify-on-demand acceptance (hardened) — the self-growing loop, kept honest.

Extraction is exercised across real page SHAPES, not just the demo page, and the
fetch path is restricted to the site index Andy already holds. Every case the
hardening pass must pass, by name:

  a. standard location page -> verdict, verbatim quote, named source, date extract
  b. multiple verdict words  -> the verdict anchored to "Last verified" wins
  c. missing "Last verified" -> fail closed, missing field named, never guessed
  d. missing named source    -> fail closed, never guessed
  e. a law/club/guide page   -> fail closed, never promoted
  f. a fetch failure         -> staged with the fetch error, never promoted
  g. out-of-index URL        -> refused WITHOUT a fetch ("URL not in site index")
  h. confirmed-secondary caveat present in BOTH the reply and the receipt

Core runs hermetically: a real index URL with fetch() monkeypatched to return a
fixture, so the fetch restriction passes while the page content stays fixed. One
live fetch of a real page is reported at the end.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import detect, tier2, verify_source as vs, voice  # noqa: E402
from agent.verify_source import KnowledgeStore  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "verify-receipts.jsonl"
PERS = RUNS / "verify-accept-cs.json"  # temp persist file (gitignored) — not the tracked one
# A real location URL that IS in the index, so the fetch restriction passes.
INDEX_URL = "https://wheretodetect.org/metal-detecting/florida/daytona-beach/"

STANDARD = """<html><body>
<h1>Can You Metal Detect at Testville Beach? Yes</h1>
<div>Testville County &middot; Central &middot; City beach ✅ Allowed Last verified: 2026-09-15</div>
<h2>The rules</h2>
<p>The Testville Beach Code says nothing about metal detecting and permits it on the public beach.</p>
<div>Permit: Not required</div>
<p>More spots near Testville 🔴 Prohibited Testville National Seashore — federal land.</p>
<p>Source: Testville County Code of Ordinances, Ch. 20, Sec. 20-6. Verify against the county.</p>
<p>Not legal advice.</p></body></html>"""

MULTI_VERDICT = """<html><body>
<h1>Can You Metal Detect at Multi Beach?</h1>
<p>Nearby parks are Prohibited and some areas are Restricted, but this beach is different.</p>
<div>Multi County ✅ Allowed Last verified: 2026-08-01</div>
<h2>The rules</h2><p>The Multi County code allows detecting on the public beach.</p>
<div>Permit: Not required</div>
<p>More spots near Multi 🔴 Prohibited Somewhere NPS.</p>
<p>Source: Multi County Code, Ch. 5. Verify against the county.</p></body></html>"""

NO_DATE = """<html><body><div>✅ Allowed</div>
<h2>The rules</h2><p>Detecting is allowed on the public beach.</p><div>Permit: Not required</div>
<p>Source: County Code, Ch. 20.</p></body></html>"""

NO_SOURCE = """<html><body><div>✅ Allowed Last verified: 2026-09-15</div>
<h2>The rules</h2><p>Detecting is allowed on the public beach.</p><div>Permit: Not required</div></body></html>"""

LAW_PAGE = """<html><body>
<h1>Florida Metal Detecting Laws</h1>
<p>Florida state parks generally prohibit metal detecting except in designated swim
areas. County and city rules vary. Always confirm with the managing authority.</p>
<h2>State parks</h2><p>Detecting requires a permit in many parks.</p>
<p>Federal land is governed by ARPA.</p></body></html>"""


def _ok_fetch(html):
    return lambda url, timeout=30.0: {"ok": True, "html": html,
                                      "sha256": hashlib.sha256(html.encode()).hexdigest(),
                                      "bytes": len(html.encode())}


def _fail_fetch(url, timeout=30.0):
    return {"ok": False, "error": "URLError: unreachable (timed out)"}


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)
    PERS.unlink(missing_ok=True)
    chain = ReceiptChain(CHAIN)
    checks = {}
    saved = vs.fetch

    # ---- extraction across page shapes (hermetic, no network) ----
    a = vs.extract(STANDARD)
    ta = vs._text(STANDARD)
    checks["a. standard page: verdict + verbatim quote + named source + date"] = (
        a["ok"] and a["verdict"] == "Allowed" and a["verified_date"] == "2026-09-15"
        and a["quote"] in ta and a["source"] in ta and "Testville Beach Code" in a["quote"])

    b = vs.extract(MULTI_VERDICT)
    checks["b. multiple verdict words: the one at 'Last verified' wins (Allowed)"] = (
        b["ok"] and b["verdict"] == "Allowed")

    c = vs.extract(NO_DATE)
    checks["c. missing 'Last verified': fails closed, names the missing field"] = (
        (not c["ok"]) and "last-verified date" in c["error"])

    d = vs.extract(NO_SOURCE)
    checks["d. missing named source: fails closed"] = (
        (not d["ok"]) and "named source" in d["error"])

    e = vs.extract(LAW_PAGE)
    checks["e. a law/guide page (not a location): fails closed"] = (not e["ok"])

    # ---- f. fetch failure stages, never promotes ----
    store_f = KnowledgeStore(persist_path=str(PERS))
    vs.fetch = _fail_fetch
    try:
        rf = store_f.propose(chain, "Daytona Beach", INDEX_URL)
    finally:
        vs.fetch = saved
    fetch_rcpt = [r["action"] for r in chain.receipts()
                  if r["action"]["type"] == "verify_fetch" and r["action"].get("place") == "Daytona Beach"]
    checks["f. fetch failure: staged with the fetch error, never promoted"] = (
        (not rf["ok"]) and store_f.get("Daytona Beach") is None
        and bool(fetch_rcpt) and fetch_rcpt[-1]["fetched_ok"] is False and fetch_rcpt[-1].get("reason"))

    # ---- g. out-of-index URL refused WITHOUT a fetch ----
    called = {"fetch": False}

    def _tripwire(url, timeout=30.0):
        called["fetch"] = True
        return {"ok": True, "html": STANDARD, "sha256": "x", "bytes": 1}

    store_g = KnowledgeStore(persist_path=str(PERS))
    vs.fetch = _tripwire
    try:
        rg = store_g.propose(chain, "Evil Place", "https://evil.example/x")
    finally:
        vs.fetch = saved
    g_rcpt = [r["action"] for r in chain.receipts()
              if r["action"]["type"] == "verify_fetch" and r["action"].get("place") == "Evil Place"]
    checks["g. out-of-index URL refused WITHOUT a fetch (URL not in site index)"] = (
        (not rg["ok"]) and ("not in site index" in rg["error"])
        and (called["fetch"] is False)
        and bool(g_rcpt) and g_rcpt[-1]["reason"] == "URL not in site index")

    # ---- h. confirmed-secondary caveat in BOTH the reply and the receipt ----
    store_h = KnowledgeStore(persist_path=str(PERS))
    vs.fetch = _ok_fetch(STANDARD)
    try:
        store_h.propose(chain, "Testville Beach", INDEX_URL)
    finally:
        vs.fetch = saved
    before = detect.answer(chain, "Testville Beach", store=store_h)["outcome"]
    store_h.confirm(chain, "Testville Beach")
    after = detect.answer(chain, "Testville Beach", store=store_h)
    o = after["outcome"]
    reply = voice._detect_reply(o)
    rcpt = after["answer_receipt"]["action"]
    caveat = (o.get("caveat") or "").lower()
    needed = ("read the site", "ordinance", "approved", "confirm the primary")
    checks["h. before approval the place is STAGED (not answered)"] = (before["decision"] == detect.STAGED)
    checks["h. after approval: confirmed secondary (answered_with_caveat)"] = (
        o["decision"] == detect.ANSWERED_WITH_CAVEAT and o["evidence_tier"] == vs.CONFIRMED_SECONDARY)
    checks["h. caveat present in the reply (not a bare 'allowed')"] = all(w in reply.lower() for w in needed)
    checks["h. caveat present in the receipt, never Tier 1"] = (
        all(w in (rcpt.get("caveat") or "").lower() for w in needed)
        and rcpt.get("evidence_tier") == vs.CONFIRMED_SECONDARY and rcpt.get("evidence_tier") != "primary")

    # ---- receipts + chain ----
    ok, reason = verify_chain(CHAIN)
    checks["chain verifies end to end"] = ok

    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    live = vs.fetch("https://wheretodetect.org/metal-detecting/florida/daytona-beach/")
    if live["ok"]:
        lex = vs.extract(live["html"])
        print(f"\n  live check: Daytona Beach -> extract ok={lex['ok']} verdict={lex.get('verdict')} "
              f"(quote verbatim={lex.get('quote', '') in vs._text(live['html'])})")
    else:
        print(f"\n  live check skipped (no network): {live['error']}")

    if all(checks.values()):
        print("\nVERIFY-ON-DEMAND (HARDENED) ACCEPTANCE: PASS")
        return 0
    print("\nVERIFY-ON-DEMAND (HARDENED) ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
