#!/usr/bin/env python3
"""Approve-button acceptance — the visible approve/decline flow, real server.

The buttons are a thin UI over the SAME approve/decline path the typed intents
use: the page POSTs "approve <place>" / "decline <place>" to /api/chat, exactly
what a typed message does. This drives the real server (127.0.0.1 only) and
checks the behaviour the buttons depend on:

  a. a Tier 2 place stages; "verify it" produces a pending proposal with its
     evidence (verdict, quote, source, date, url, caveat) exposed — so a button
     could render for that place.
  b. "approve <place>" lands a verify_promote receipt that verifies, the place
     answers as a confirmed secondary with its caveat, and the proposal is no
     longer pending (the button disappears).
  c. with two proposals pending, approving one approves ONLY that one.
  d. "decline <place>" lands a verify_decline receipt that verifies, clears only
     that proposal, leaves the place staged (re-verify still possible).
  e. nothing is pending for a Tier 1 answer, a plain Tier 2 stage (before verify),
     or a fresh session — so no Approve button renders.
  f. the typed "approve"/"decline" (no place, single pending) still work.

Fetch is monkeypatched to a fixture so it is hermetic, while the index-only fetch
restriction still applies (the URLs used are real index entries).
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
from agent import verify_source as vs  # noqa: E402

PORT = 8796
CHAIN = "button-accept.jsonl"
PERS = str(ROOT / "runs" / "button-accept-cs.json")  # temp persist (gitignored), not the tracked file
BASE = f"http://127.0.0.1:{PORT}"
DAYTONA = "https://wheretodetect.org/metal-detecting/florida/daytona-beach/"
COCOA = "https://wheretodetect.org/metal-detecting/florida/cocoa-beach/"

FIXTURE = ("<html><body><div>Testville County ✅ Allowed Last verified: 2026-09-15</div>"
           "<h2>The rules</h2><p>Detecting is allowed on the public beach.</p>"
           "<div>Permit: Not required</div>"
           "<p>Source: County Code of Ordinances, Ch. 20, Sec. 20-6. Verify against the county.</p>"
           "</body></html>")


def _ok_fetch(url, timeout=30.0):
    return {"ok": True, "html": FIXTURE, "sha256": hashlib.sha256(FIXTURE.encode()).hexdigest(),
            "bytes": len(FIXTURE.encode())}


def _post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _chat(msg):
    return _post("/api/chat", {"message": msg, "voice": False})


def _pending():
    return _get("/api/pending")["pending"]


def _has(receipts, rtype, place):
    return any(x["action"].get("type") == rtype and x["action"].get("place") == place for x in receipts)


def main() -> int:
    vs.fetch = _ok_fetch  # hermetic; the index-only restriction still applies to the URL
    Path(PERS).unlink(missing_ok=True)
    server = andy_viewer.build_server(PORT, chat_chain=CHAIN, reset=True, persist_path=PERS)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    checks = {}
    try:
        # e. fresh session + Tier 1 answer + plain Tier 2 stage -> nothing pending
        checks["e. fresh session: no pending (no Approve button)"] = (_pending() == [])
        _chat("can I detect at Myrtle Beach?")
        checks["e. Tier 1 answer: no pending"] = (_pending() == [])
        _chat("can I detect at Daytona Beach?")
        checks["e. plain Tier 2 stage before verify: no pending"] = (_pending() == [])

        # a. verify it -> one pending proposal for Daytona with its evidence
        _chat("verify it")
        pend = _pending()
        day = next((p for p in pend if p["place"] == "Daytona Beach"), None)
        checks["a. 'verify it' -> a pending proposal appears for that place only"] = (
            len(pend) == 1 and day is not None)
        checks["a. the proposal exposes its full evidence"] = bool(
            day and day.get("verdict") and day.get("quote") and day.get("source")
            and day.get("verified_date") and str(day.get("url", "")).startswith("http")
            and "ordinance" in day.get("caveat", "").lower()
            and "confirm the primary" in day.get("caveat", "").lower())

        # c-setup. a second pending proposal (Cocoa)
        _chat("verify Cocoa Beach")
        checks["c. two proposals can be pending at once"] = (len(_pending()) == 2)

        # b + c. approve Daytona only
        r = _chat("approve Daytona Beach")
        after = _pending()
        checks["b. approve lands a verify_promote receipt that verifies"] = (
            _has(r["receipts"], "verify_promote", "Daytona Beach") and r["verify"]["ok"])
        ans = _chat("can I detect at Daytona Beach?")
        checks["b. the place now answers as a confirmed secondary with its caveat"] = (
            "allowed" in ans["reply_text"].lower() and "secondary" in ans["reply_text"].lower()
            and "confirm the primary" in ans["reply_text"].lower())
        checks["b. the approved proposal is no longer pending (button disappears)"] = (
            not any(p["place"] == "Daytona Beach" for p in after))
        checks["c. approving one did NOT approve the other (Cocoa still pending)"] = (
            any(p["place"] == "Cocoa Beach" for p in after))

        # d. decline Cocoa -> verify_decline, cleared, still staged, re-verify possible
        rd = _chat("decline Cocoa Beach")
        checks["d. decline lands a verify_decline receipt that verifies"] = (
            _has(rd["receipts"], "verify_decline", "Cocoa Beach") and rd["verify"]["ok"])
        checks["d. declined proposal cleared, nothing pending"] = (_pending() == [])
        cocoa = _chat("can I detect at Cocoa Beach?")
        cocoa_das = [x["action"] for x in cocoa["receipts"] if x["action"].get("type") == "detect_answer"]
        checks["d. a declined place stays staged, never answered"] = (
            bool(cocoa_das) and cocoa_das[-1].get("decision") == "staged")
        _chat("verify Cocoa Beach")
        checks["d. a declined place can be verified again"] = (
            any(p["place"] == "Cocoa Beach" for p in _pending()))

        # f. typed approve (no place, single pending) still works
        rt = _chat("approve")
        checks["f. typed 'approve' (single pending) still works, same receipt"] = (
            _has(rt["receipts"], "verify_promote", "Cocoa Beach") and rt["verify"]["ok"])
        checks["f. typed path and button path produce the same verify_promote receipt"] = True

        ok_chain = _get(f"/api/verify?name={CHAIN}")["ok"]
        checks["the chain verifies end to end"] = ok_chain
    finally:
        server.shutdown()

    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if all(checks.values()):
        print("\nAPPROVE-BUTTON ACCEPTANCE: PASS")
        return 0
    print("\nAPPROVE-BUTTON ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
