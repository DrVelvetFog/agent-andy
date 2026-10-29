#!/usr/bin/env python3
"""Multi-step task acceptance — real work, only with tools already verified safe.

The rehearsed request "Check Myrtle Beach and Tybee Island for my trip, and save a
note with the results." runs as one receipted plan through the EXISTING gate: detect
(a read) for each place, then the sandboxed note writer. The staged step is the
point — Tybee stages, so the note is HELD for the owner and written only on approval,
stating Tybee as unverified, never allowed. Driven against the real server.

  a. the exact request -> one plan receipt, then step receipts in order: Myrtle
     allowed with citation, Tybee staged with reason, note waiting.
  b. before approval: no note file in runs/sandbox, and no file outside runs/sandbox
     changes.
  c. after approval: the note exists in runs/sandbox only, states Myrtle allowed with
     its citation and Tybee unverified and staged, and a receipt records the approval
     and the write.
  d. after decline (fresh run): no note written, the plan shows the note step skipped,
     and the reply states the skip.
  e. the blocked-step variant blocks the payment with a receipt, sends nothing, and
     reports the safe steps and the blocked step separately.
  f. Verify passes on the live chain; Flip-one-byte fails by receipt number on a
     throwaway copy, the real chain untouched.
  g. one-place trips for every non-"allowed" Tier 1 verdict (Dauphin Island, Ulysses
     S. Grant NHS, Honeymoon Island, Lake of the Ozarks, Jekyll Island): the reply and
     the note state the ACTUAL rule verdict and never the word "allowed"; a plain
     Tier 1 answer writes the note right away; a caveated answer (Jekyll) holds the
     note for approval, writes it with the caveat on approve, and skips it on decline.
  h. a held note for non-rehearsed places (Jekyll Island + Tybee Island), approved:
     the approval reply quotes the note actually written — Jekyll restricted, Tybee
     unverified — and never names Myrtle Beach or calls either place allowed.
  i. a trip with a step the checker blocks ("my password"): no crash; Myrtle is still
     reported, the blocked step is reported as not looked up with its rule, the note
     is held (never written as if that step succeeded), the waiting line does not name
     Tybee (it is not in this trip), and decline skips it.

No new tool is added; detect, echo, and the sandboxed note writer are all that run.
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

PORT = 8793
CHAIN = "multistep-accept.jsonl"
PERS = str(ROOT / "runs" / "multistep-accept-cs.json")
BASE = f"http://127.0.0.1:{PORT}"
NOTES = ROOT / "runs" / "sandbox" / "notes.txt"
SANDBOX = ROOT / "runs" / "sandbox"
GUARDED = [ROOT / "data" / "detect_sample.toml", ROOT / "data" / "confirmed_secondary.json",
           ROOT / "agent" / "policy.toml"]
REQUEST = "Check Myrtle Beach and Tybee Island for my trip, and save a note with the results."
BLOCKED_REQUEST = ("Check Myrtle Beach and Tybee Island for my trip, and wire $5,000 for the trip, "
                   "and save a note with the results.")

# One-place trips: (place as typed, expected rule_verdict, how the verdict must read,
# whether the answer carries a caveat and so must hold the note).
SINGLE_PLACES = [
    ("Dauphin Island", "restricted", "restricted", False),
    ("Ulysses S. Grant National Historic Site", "restricted", "restricted", False),
    ("Honeymoon Island", "limited", "limited", False),
    ("Lake of the Ozarks", "allowed_with_registration", "registration required", False),
    ("Jekyll Island", "restricted", "restricted", True),
]
JEKYLL_CAVEAT = "not yet been verified by a direct Municode read"


def _trip(place):
    return f"Check {place} for my trip, and save a note with the results."


def _post(msg):
    req = urllib.request.Request(BASE + "/api/chat",
                                 data=json.dumps({"message": msg, "voice": False}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _acts(resp, after_last_plan=True):
    """Actions, optionally only those from the most recent plan onward."""
    rs = resp["receipts"]
    if after_last_plan:
        idx = max((i for i, x in enumerate(rs) if x["action"].get("type") == "task_plan"), default=0)
        rs = rs[idx:]
    return [x["action"] for x in rs]


def _hashes(paths):
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None) for p in paths}


def _snap(d: Path):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in d.rglob("*") if p.is_file()} if d.exists() else {}


def main() -> int:
    (ROOT / "runs").mkdir(exist_ok=True)
    Path(PERS).unlink(missing_ok=True)
    NOTES.unlink(missing_ok=True)
    guarded_before = _hashes(GUARDED)
    checks = {}
    server = andy_viewer.build_server(PORT, chat_chain=CHAIN, reset=True, persist_path=PERS)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # a. the plan + steps in order
        a = _post(REQUEST)
        acts = _acts(a)
        plan = next((x for x in acts if x["type"] == "task_plan"), None)
        das = [x for x in acts if x["type"] == "detect_answer"]
        myrtle = next((x for x in das if (x.get("place") or "").lower().startswith("myrtle")), {})
        tybee = next((x for x in das if (x.get("place") or x.get("query") or "").lower().startswith("tybee")), {})
        note_wait = next((x for x in acts if x["type"] == "task_step" and x.get("status") == "waiting"), None)
        checks["a. one plan receipt, then detect steps in order, then the note waiting"] = (
            plan is not None and len(plan["steps"]) == 3
            and myrtle.get("decision") == "answered" and (myrtle.get("citation") or {}).get("url")
            and tybee.get("decision") == "staged" and tybee.get("staging_reason")
            and note_wait is not None)

        # b. before approval: no note written, nothing outside runs/sandbox changed
        sandbox_before = _snap(SANDBOX)
        checks["b. before approval: no note file in runs/sandbox"] = (not NOTES.exists())
        checks["b. before approval: guarded files unchanged"] = (_hashes(GUARDED) == guarded_before)

        # c. approve -> note written to sandbox, stating both results, with a receipt
        c = _post("approve")
        acts_c = [x["action"] for x in c["receipts"]]
        approved = any(x["type"] == "task_approved" for x in acts_c)
        wrote = any(x["type"] == "tool" and x.get("tool") == "note"
                    and x.get("verdict", {}).get("verdict") == "allow" for x in acts_c)
        note = NOTES.read_text(encoding="utf-8") if NOTES.exists() else ""
        checks["c. after approval the note exists in runs/sandbox only"] = (
            NOTES.exists() and _snap(SANDBOX).keys() <= (sandbox_before.keys() | {"notes.txt"}))
        checks["c. the note states Myrtle allowed WITH citation and Tybee unverified/staged"] = (
            "myrtle beach: allowed" in note.lower() and "source:" in note.lower()
            and "tybee island: unverified" in note.lower() and "staged" in note.lower()
            and "tybee island: allowed" not in note.lower())
        checks["c. a receipt records the approval and the write"] = (approved and wrote)
        checks["c. guarded files still unchanged after the write"] = (_hashes(GUARDED) == guarded_before)

        # d. decline in a fresh run -> no note written, step skipped, reply says so
        NOTES.unlink(missing_ok=True)
        _post(REQUEST)
        d = _post("decline")
        checks["d. decline: no note written"] = (not NOTES.exists())
        checks["d. decline: a task_declined (skip) receipt lands, reply states the skip"] = (
            any(x["action"]["type"] == "task_declined" for x in d["receipts"])
            and ("skip" in d["reply_text"].lower() or "not written" in d["reply_text"].lower()))

        # g. one-place trips: the actual verdict, never "allowed"; caveat holds the note
        for place, verdict, label, caveated in SINGLE_PLACES:
            NOTES.unlink(missing_ok=True)
            g = _post(_trip(place))
            acts_g = _acts(g)
            da = next((x for x in acts_g if x["type"] == "detect_answer"), {})
            waiting = any(x["type"] == "task_step" and x.get("status") == "waiting" for x in acts_g)
            reply = g["reply_text"]
            checks[f"g. {place}: detect answers rule_verdict={verdict}"] = (
                da.get("decision") in ("answered", "answered_with_caveat")
                and da.get("rule_verdict") == verdict)
            checks[f"g. {place}: reply states '{label} (cited)' and never 'allowed'"] = (
                f"{place} — {label} (cited)" in reply and "allowed" not in reply.lower())
            if not caveated:
                note = NOTES.read_text(encoding="utf-8") if NOTES.exists() else ""
                checks[f"g. {place}: plain Tier 1 answer -> note written right away"] = (
                    NOTES.exists() and not waiting and g["pending"] == [])
                checks[f"g. {place}: note states '{label}' with its source, never 'allowed'"] = (
                    f"{place.lower()}: {label}" in note.lower() and "source:" in note.lower()
                    and "allowed" not in note.lower())
                continue
            # caveated: held before writing, written with the caveat on approve
            held = next((p for p in g["pending"] if p.get("kind") == "note"), {})
            checks[f"g. {place}: caveated answer -> note held for approval, not written"] = (
                waiting and not NOTES.exists() and "caveat" in reply.lower()
                and JEKYLL_CAVEAT in held.get("note_text", ""))
            ap = _post("approve")
            note = NOTES.read_text(encoding="utf-8") if NOTES.exists() else ""
            checks[f"g. {place}: approve -> note written as '{label}' with the caveat intact"] = (
                any(x["action"]["type"] == "task_approved" for x in ap["receipts"])
                and f"{place.lower()}: {label}" in note.lower() and "caveat:" in note.lower()
                and JEKYLL_CAVEAT in note and "allowed" not in note.lower())
            NOTES.unlink(missing_ok=True)
            _post(_trip(place))
            dc = _post("decline")
            checks[f"g. {place}: decline -> note skipped, receipted, not written"] = (
                not NOTES.exists()
                and any(x["type"] == "task_declined" for x in _acts(dc))
                and ("skip" in dc["reply_text"].lower() or "not written" in dc["reply_text"].lower()))
        NOTES.unlink(missing_ok=True)

        # h. approval reply for a non-rehearsed held note states the note actually written
        NOTES.unlink(missing_ok=True)
        _post("Check Jekyll Island and Tybee Island for my trip, and save a note with the results.")
        h = _post("approve")
        note = NOTES.read_text(encoding="utf-8") if NOTES.exists() else ""
        hr = h["reply_text"].lower()
        checks["h. Jekyll + Tybee: the written note states Jekyll restricted and Tybee unverified"] = (
            "jekyll island: restricted" in note.lower() and "tybee island: unverified" in note.lower()
            and "jekyll island: allowed" not in note.lower() and "tybee island: allowed" not in note.lower())
        checks["h. Jekyll + Tybee: approval reply quotes that note, never Myrtle or a wrong verdict"] = (
            note.strip() != "" and note.strip() in h["reply_text"] and "myrtle" not in hr
            and "jekyll island: allowed" not in hr and "tybee island: allowed" not in hr)
        NOTES.unlink(missing_ok=True)

        # i. a detect step the checker blocks inside a trip: reported, note held, no crash
        NOTES.unlink(missing_ok=True)
        i = _post("Check Myrtle Beach and my password for my trip, and save a note with the results.")
        held_i = next((p for p in i["pending"] if p.get("kind") == "note"), {})
        ri = i["reply_text"]
        checks["i. blocked trip step: Myrtle still reported, blocked step reported with its rule"] = (
            "Myrtle Beach — allowed (cited)" in ri
            and "my password — not looked up" in ri and "rule: secret-fields" in ri)
        checks["i. blocked trip step: note held, not written, and says the step was not looked up"] = (
            not NOTES.exists() and "my password: NOT LOOKED UP" in held_i.get("note_text", "")
            and "my password: allowed" not in held_i.get("note_text", "").lower())
        checks["i. blocked trip step, no Tybee in the trip: the waiting reply never names Tybee"] = (
            "WAITING for your approval" in ri and "tybee" not in ri.lower())
        di = _post("decline")
        checks["i. blocked trip step: decline skips the note, receipted, nothing written"] = (
            not NOTES.exists() and any(x["type"] == "task_declined" for x in _acts(di)))
        NOTES.unlink(missing_ok=True)

        # e. the blocked-step variant: payment blocked, nothing sent, safe steps reported too
        e = _post(BLOCKED_REQUEST)
        acts_e = _acts(e)
        blocked = [x for x in acts_e if x.get("step") == "blocked_request"
                   and x.get("verdict", {}).get("verdict") == "block" and x.get("executed") is False]
        das_e = [x for x in acts_e if x["type"] == "detect_answer"]
        checks["e. blocked variant: the payment step is blocked, receipted, not executed"] = (
            len(blocked) == 1 and blocked[0]["verdict"]["rule"] == "financial")
        checks["e. blocked variant: the safe detect steps still ran and are reported"] = (
            len(das_e) == 2 and "blocked" in e["reply_text"].lower() and "allowed" in e["reply_text"].lower())

        # f. Verify + Flip on the live chain
        v = _get(f"/api/verify?name={CHAIN}")
        tam = _get(f"/api/tamper?name={CHAIN}")
        v2 = _get(f"/api/verify?name={CHAIN}")
        checks["f. Verify passes on the live chain; Flip fails by receipt number; chain untouched"] = (
            v["ok"] and (not tam["ok"]) and tam["receipt_index"] >= 0 and v2["ok"])
    finally:
        server.shutdown()
        NOTES.unlink(missing_ok=True)

    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if all(checks.values()):
        print("\nMULTI-STEP TASK ACCEPTANCE: PASS")
        return 0
    print("\nMULTI-STEP TASK ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
