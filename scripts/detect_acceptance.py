#!/usr/bin/env python3
"""Form 2 acceptance — "can I detect here?" with a hybrid, two-tier knowledge base.

TIER 1 (data/detect_sample.toml) is the vetted eight: a match ANSWERS with a cited
primary, or stages. It is never downgraded. TIER 2 (data/site_index.json, built
from the public sitemap) is INDEX ONLY — it carries no verdicts and can only add a
candidate SITE PAGE to a STAGE, so a human can go check the primary.

  1. Tier 1 is unchanged: the six primary-sourced places ANSWER with a cited
     primary; Jekyll (corroborated citation) answers with its caveat in BOTH
     normal and strict mode; Tybee stages; an excluded place stages — 10/10
     decisions as before.
  2. A Tier 1 answer never downgrades to Tier 2 (an answered place gets no candidate).
  3. Tybee now stages WITH a Tier 2 candidate site page, and still no verdict.
  4. A place in the site index but not in Tier 1 stages with a candidate URL and
     the unverified-primary reason — and no verdict wording anywhere.
  5. A place in neither tier stages off-list with no candidate; a fictional place
     stages with no candidate and no invented URL.

No network, no model: Tier 1 and the gate are local; Tier 2 reads the prebuilt
index. A staged outcome is a PASS — it proves the gate held.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import detect, tier2, voice  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "detect-receipts.jsonl"

_V = detect.ANSWERED, detect.ANSWERED_WITH_CAVEAT
_VERDICT_WORDS = ("allowed", "restricted", "limited", "with registration", "with-registration")

# Tier 1 — the vetted eight (10 cases). (query, strict, expected decision, expected verdict)
CASES = [
    ("Myrtle Beach", False, detect.ANSWERED, "allowed"),
    ("Orange Beach", False, detect.ANSWERED, "allowed"),
    ("Lake of the Ozarks State Park", False, detect.ANSWERED, "allowed_with_registration"),
    ("Honeymoon Island State Park", False, detect.ANSWERED, "limited"),
    ("Dauphin Island", False, detect.ANSWERED, "restricted"),
    ("Ulysses S. Grant National Historic Site", False, detect.ANSWERED, "restricted"),
    ("Jekyll Island", False, detect.ANSWERED_WITH_CAVEAT, "restricted"),
    ("Jekyll Island", True, detect.ANSWERED_WITH_CAVEAT, "restricted"),  # corroborated citation: answers in strict too, caveat carried
    ("Tybee Island", False, detect.STAGED, None),           # Tier 1 stage (the thesis beat)
    ("Clearwater Beach", False, detect.STAGED, None),       # not in Tier 1
]

# Tier 2 — (query, expect a candidate?)
TIER2_CASES = [
    ("Tybee Island", True),     # c: Tier 1 stage + a Tier 2 candidate
    ("Daytona Beach", True),    # d: in the site index, not in Tier 1
    ("Virginia Beach", False),  # e: in neither tier
    ("Brigadoon", False),       # f: fictional
]


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)
    chain = ReceiptChain(CHAIN)

    rows = []
    for query, strict, exp_d, exp_v in CASES:
        o = detect.answer(chain, query, strict=strict)["outcome"]
        rows.append((query, strict, exp_d, exp_v, o))
        tag = "STRICT" if strict else ""
        print(f"  {query:42}{tag:7} -> {o['decision']:20} verdict={str(o['rule_verdict']):26} "
              f"[{'cited' if o['citation'] else '—'}]")

    t2 = {}
    print()
    for query, expect_cand in TIER2_CASES:
        o = detect.answer(chain, query)["outcome"]
        t2[query] = o
        cands = o.get("tier2_candidates") or []
        print(f"  {query:28} -> {o['decision']:10} cand={cands[0]['url'] if cands else '—'}")

    meta = tier2.meta()
    index_urls = {e["url"] for e in __import__("json").loads(
        (ROOT / "data" / "site_index.json").read_text(encoding="utf-8"))["entries"]}

    checks = {}
    # ---- Tier 1 (a) ----
    checks["a. Tier 1: 10/10 decisions + verdicts unchanged"] = all(
        o["decision"] == exp_d and o["rule_verdict"] == exp_v for _, _, exp_d, exp_v, o in rows)
    checks["a. answered Tier 1 cases cite a primary (url + quote)"] = all(
        o["citation"] and o["citation"]["url"] and o["citation"]["quote"]
        for *_, o in rows if o["decision"] in _V)
    # ---- never downgrade (b) ----
    checks["b. a Tier 1 answer never downgrades to Tier 2 (no candidate)"] = all(
        not (o.get("tier2_candidates")) for *_, o in rows if o["decision"] in _V)
    # ---- Tybee (c) ----
    tybee = t2["Tybee Island"]
    checks["c. Tybee stages, now WITH a Tier 2 candidate, still no verdict"] = (
        tybee["decision"] == detect.STAGED and tybee["rule_verdict"] is None
        and bool(tybee.get("tier2_candidates")))
    # ---- in-index, not Tier 1 (d) ----
    day = t2["Daytona Beach"]
    day_reply = voice._detect_reply(day)
    day_fields = " ".join(str(day.get(k) or "") for k in
                          ("rule_verdict", "staging_reason", "tier2_reason")).lower()
    checks["d. in-index non-Tier-1 stages with a candidate + unverified reason"] = (
        day["decision"] == detect.STAGED and day["rule_verdict"] is None
        and bool(day.get("tier2_candidates")) and day.get("tier2_reason"))
    checks["d. no verdict wording in the Daytona reply or receipt"] = (
        not any(w in day_reply.lower() for w in _VERDICT_WORDS)
        and not any(w in day_fields for w in _VERDICT_WORDS))
    # ---- neither tier (e) + fictional (f) ----
    checks["e. a place in neither tier stages with no candidate"] = (
        t2["Virginia Beach"]["decision"] == detect.STAGED
        and not t2["Virginia Beach"].get("tier2_candidates"))
    checks["f. a fictional place stages with no candidate (no invented URL)"] = (
        t2["Brigadoon"]["decision"] == detect.STAGED
        and not t2["Brigadoon"].get("tier2_candidates"))
    # ---- Tier 2 is honest index data, never invented ----
    checks["Tier 2 index records source + fetch date + URL count"] = (
        bool(meta["source"]) and bool(meta["fetched"]) and isinstance(meta["url_count"], int))
    checks["every surfaced candidate is a real index URL (never invented)"] = all(
        all(c["url"] in index_urls and c.get("verified") is False
            for c in (o.get("tier2_candidates") or []))
        for o in t2.values())
    # ---- durable artifact ----
    answers = [r for r in chain.receipts() if r["action"].get("type") == "detect_answer"]
    checks["every answer receipt carries both axes (+ tier2 fields)"] = all(
        all(k in r["action"] for k in ("rule_verdict", "evidence_tier", "decision", "tier2_candidates"))
        for r in answers)
    ok, reason = verify_chain(CHAIN)
    checks["chain verifies end to end"] = ok

    print(f"\nTier 2 index: {meta['entry_count']} location entries of {meta['url_count']} "
          f"sitemap URLs, fetched {meta['fetched']}")
    print(f"receipts: {len(chain.receipts())} ({len(answers)} answers); verify: {reason}\n")
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    if all(checks.values()):
        print("\nFORM 2 (detect-here, two-tier) ACCEPTANCE: PASS")
        return 0
    print("\nFORM 2 (detect-here, two-tier) ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
