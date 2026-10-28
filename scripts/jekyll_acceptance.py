#!/usr/bin/env python3
"""Jekyll citation update (Option A) acceptance — Jekyll only.

Tony accepted the enacted citation on 2026-10-28: Jekyll Island Authority Code of
Ordinances, Sec. 10-191(16), Ord. O-2022-1 — corroborated by two readable sources
but NOT yet verified by a direct Municode read (that load was Cloudflare-blocked).
Under Option A, Jekyll answers restricted WITH that corroboration caveat in BOTH
normal and strict mode; it no longer stages in strict. The verdict, conditions, and
the prohibition quote are unchanged. Nothing else in the fixture changes.

  a. Normal mode: "Jekyll Island" answers restricted, with the Sec. 10-191(16),
     Ord. O-2022-1 citation and the corroboration caveat in the reply AND receipt.
  b. Strict mode: "Jekyll Island" also answers restricted, same citation and caveat,
     and does NOT stage.
  c. Tybee Island still stages as unverified, in both modes.
  d. No other location changed verdict, citation, or conditions (the pre-change
     fixture from git HEAD vs the working tree, Jekyll entry excepted); and Jekyll's
     own verdict, conditions, and source_quote are themselves unchanged.
  e. No text in the repo, UI, or README presents the Jekyll citation as a direct
     Municode read (every "direct Municode read" mention is negated), and OCGA
     12-3-10 is not cited for Jekyll anywhere.

Deterministic and local: detect answers from the fixture + gate, no network, no model.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import detect, voice  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "jekyll-accept.jsonl"
FIXTURE = ROOT / "data" / "detect_sample.toml"

CITE_SEC = "Sec. 10-191(16)"
CITE_ORD = "Ord. O-2022-1"
CAVEAT_MARK = "corroborated by the June 21, 2022 Jekyll Island Authority board adoption summary"
OLD_DRAFT_MARK = "first-reading draft"
# Files that make up the repo / UI / README surface (self excluded).
SURFACE = [ROOT / "README.md", FIXTURE, ROOT / "agent" / "detect.py",
           ROOT / "agent" / "voice.py", ROOT / "viewer" / "index.html"]


def _answer(chain, place, strict):
    return detect.answer(chain, place, strict=strict)["outcome"]


def _receipt_for(chain, query, strict):
    """The detect_answer receipt matching this query (latest wins)."""
    hit = None
    for r in chain.receipts():
        a = r["action"]
        if a.get("type") == "detect_answer" and a.get("query") == query:
            hit = a
    return hit or {}


def _locations(toml_text: str) -> dict:
    data = tomllib.loads(toml_text)
    return {rec["place"]: rec for rec in data.get("locations", [])}


def _cite_and_caveat_present(o: dict, reply: str, rc: dict) -> bool:
    cite = (o.get("citation") or {}).get("source", "")
    cav = o.get("caveat") or ""
    in_outcome = (CITE_SEC in cite and CITE_ORD in cite
                  and CAVEAT_MARK in cav and OLD_DRAFT_MARK not in cav)
    in_reply = (CITE_SEC in reply and CAVEAT_MARK in reply)
    rc_cite = (rc.get("citation") or {}).get("source", "")
    rc_cav = rc.get("caveat") or ""
    in_receipt = (CITE_SEC in rc_cite and CITE_ORD in rc_cite and CAVEAT_MARK in rc_cav)
    return in_outcome and in_reply and in_receipt


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)
    chain = ReceiptChain(CHAIN)
    checks = {}

    # a. normal mode
    jn = _answer(chain, "Jekyll Island", strict=False)
    jn_reply = voice._detect_reply(jn)
    jn_rc = _receipt_for(chain, "Jekyll Island", strict=False)
    checks["a. normal: Jekyll answers restricted, citation + caveat in reply AND receipt"] = (
        jn["decision"] == detect.ANSWERED_WITH_CAVEAT and jn["rule_verdict"] == "restricted"
        and _cite_and_caveat_present(jn, jn_reply, jn_rc))

    # b. strict mode — same answer, does NOT stage
    js = _answer(chain, "Jekyll Island", strict=True)
    js_reply = voice._detect_reply(js)
    js_rc = _receipt_for(chain, "Jekyll Island", strict=True)
    checks["b. strict: Jekyll also answers restricted with same citation + caveat"] = (
        js["decision"] == detect.ANSWERED_WITH_CAVEAT and js["rule_verdict"] == "restricted"
        and _cite_and_caveat_present(js, js_reply, js_rc))
    checks["b. strict: Jekyll does NOT stage"] = (js["decision"] != detect.STAGED)

    # c. Tybee still stages in both modes
    tn = _answer(chain, "Tybee Island", strict=False)
    ts = _answer(chain, "Tybee Island", strict=True)
    checks["c. Tybee stages as unverified in both modes"] = (
        tn["decision"] == detect.STAGED and tn["rule_verdict"] is None
        and ts["decision"] == detect.STAGED and ts["rule_verdict"] is None)

    # d. no other location changed; Jekyll's own verdict/conditions/quote unchanged
    before = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:data/detect_sample.toml"],
                            capture_output=True, text=True, check=True).stdout
    before_locs, after_locs = _locations(before), _locations(FIXTURE.read_text(encoding="utf-8"))
    JEK = "Jekyll Island, Georgia"
    others_same = (set(before_locs) == set(after_locs) and all(
        before_locs[p] == after_locs[p] for p in before_locs if p != JEK))
    checks["d. no other location changed verdict/citation/conditions"] = others_same
    jb, ja = before_locs[JEK], after_locs[JEK]
    checks["d. Jekyll verdict + conditions + source_quote unchanged"] = (
        jb["verdict"] == ja["verdict"] == "restricted"
        and jb["conditions"] == ja["conditions"]
        and jb["source_quote"] == ja["source_quote"])
    checks["d. Jekyll citation + caveat + checked date did change"] = (
        jb["source_name"] != ja["source_name"] and jb["source_url"] != ja["source_url"]
        and jb["caveat"] != ja["caveat"] and ja["checked"] == "2026-10-28")

    # e. never presented as a direct Municode read; OCGA 12-3-10 absent
    ocga_hits, bare_read_hits = [], []
    for f in SURFACE:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        low = text.lower()
        if "12-3-10" in low:
            ocga_hits.append(str(f.relative_to(ROOT)))
        # every "direct Municode read" occurrence must be negated nearby ("not ...")
        start = 0
        while True:
            i = low.find("direct municode read", start)
            if i == -1:
                break
            window = low[max(0, i - 60):i]
            if "not" not in window:
                bare_read_hits.append(str(f.relative_to(ROOT)))
            start = i + 1
    checks["e. OCGA 12-3-10 is not cited anywhere on the repo surface"] = (not ocga_hits)
    checks["e. no text presents the citation as a direct Municode read"] = (not bare_read_hits)

    ok, reason = verify_chain(CHAIN)
    checks["chain verifies end to end"] = ok

    print("Jekyll reply (normal):", jn_reply)
    print("Jekyll reply (strict):", js_reply)
    print()
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if ocga_hits:
        print("   OCGA hits:", ocga_hits)
    if bare_read_hits:
        print("   un-negated 'direct Municode read' in:", bare_read_hits)

    if all(checks.values()):
        print("\nJEKYLL CITATION (Option A) ACCEPTANCE: PASS")
        return 0
    print("\nJEKYLL CITATION (Option A) ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
