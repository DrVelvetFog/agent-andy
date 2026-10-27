"""Form 2: "can I detect here?" — a rule lookup that proves its answer.

Andy is asked whether metal detecting is allowed somewhere. He looks the place
up in a vetted sample (data/detect_sample.toml) and either answers with the
rule verdict AND a cited primary source, or stages the question as unverified.
Two axes, kept distinct and both written into the receipt:

  RULE VERDICT   what the rule says: allowed / allowed_with_registration /
                 limited / restricted  (the content).
  EVIDENCE GATE  whether Andy is ENTITLED to report it: a cited primary source
                 answers; no primary source stages. This is the honesty gate.

A staged answer is a SUCCESS, not a failure — it proves Andy held back instead
of guessing. Fail closed: an unreadable sample, an unknown place, or a shaky
source never produces a confident verdict. No inference across places: a place
not in the vetted set is staged, never guessed from a nearby one.

Deterministic and local — no model, no network. The spoken-question front end
(Muse Voice Transcribe -> Muse Spark picks the place) is a later layer; this
module answers a place string directly.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from . import checker

SAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "detect_sample.toml"

ANSWERED, ANSWERED_WITH_CAVEAT, STAGED = "answered", "answered_with_caveat", "staged"

_index: dict[str, dict] | None = None


def _norm(s: str) -> str:
    return " ".join(str(s).lower().split()).strip(" .,?!")


def _load_index() -> dict[str, dict]:
    """Map every alias -> its record. Raises on a missing/broken sample so the
    caller can fail closed."""
    global _index
    if _index is None:
        with SAMPLE_FILE.open("rb") as f:
            data = tomllib.load(f)
        idx: dict[str, dict] = {}
        for rec in data.get("locations", []):
            for name in rec.get("names", []):
                idx[_norm(name)] = rec
        _index = idx
    return _index


def lookup(place: str) -> dict | None:
    """Exact (normalized) alias match only — no fuzzy or nearby inference."""
    return _load_index().get(_norm(place))


def _citation(rec: dict) -> dict | None:
    if not rec.get("source_url"):
        return None
    return {
        "source": rec.get("source_name", ""),
        "url": rec["source_url"],
        "quote": rec.get("source_quote", ""),
    }


def evaluate_query(place: str, strict: bool = False) -> dict:
    """Decide answer-vs-stage for one place. `strict` (for the live final)
    stages a draft-sourced verdict instead of answering it with a caveat."""
    try:
        rec = lookup(place)
    except Exception as e:  # unreadable/broken sample -> fail closed
        return {
            "query": place, "matched": False, "place": None, "rule_verdict": None,
            "evidence_tier": "error", "decision": STAGED, "citation": None,
            "conditions": None, "caveat": None,
            "staging_reason": f"sample unavailable, fail closed: {type(e).__name__}",
        }

    if rec is None:
        return {
            "query": place, "matched": False, "place": None, "rule_verdict": None,
            "evidence_tier": "none", "decision": STAGED, "citation": None,
            "conditions": None, "caveat": None,
            "staging_reason": "Not in the verified sample set — no primary source "
                              "was checked for this place; needs a human.",
        }

    tier = rec.get("evidence")
    out = {
        "query": place, "matched": True, "place": rec.get("place"),
        "rule_verdict": rec.get("verdict"), "evidence_tier": tier,
        "citation": _citation(rec), "conditions": rec.get("conditions"),
        "caveat": rec.get("caveat"), "staging_reason": None, "decision": None,
    }

    if tier == "primary":
        out["decision"] = ANSWERED
    elif tier == "primary_draft":
        if strict:
            out["decision"] = STAGED
            out["staging_reason"] = ("Primary source is a draft and the enacted "
                                     "ordinance is not pinned — staged under strict "
                                     "mode; needs a human.")
        else:
            out["decision"] = ANSWERED_WITH_CAVEAT
    elif tier == "absent":
        out["rule_verdict"] = None  # no verdict is entitled without a primary source
        out["decision"] = STAGED
        out["staging_reason"] = rec.get("staging_reason", "No primary source — needs a human.")
    else:
        out["rule_verdict"] = None
        out["decision"] = STAGED
        out["staging_reason"] = f"Unknown evidence tier '{tier}' — fail closed; needs a human."
    return out


def answer(chain, place: str, strict: bool = False) -> dict:
    """Handle one 'can I detect here?' query as a full, receipted turn.

    Two receipts land: the scope gate (the policy engine ruling that a rule
    lookup is in-scope) and the answer itself (carrying both axes). Only an
    in-scope lookup produces an answer; both outcomes are receipted.
    """
    action = {"type": "tool", "tool": "detect_here",
              "summary": f"look up the detecting rule for {place}"}
    scope = checker.evaluate(action)
    scope_receipt = chain.append({**action, "verdict": scope})

    if scope["verdict"] != checker.ALLOW:
        return {"scope_receipt": scope_receipt, "answer_receipt": None,
                "outcome": None, "decision": STAGED}

    out = evaluate_query(place, strict=strict)
    answer_receipt = chain.append({
        "type": "detect_answer",
        "summary": f"{out['decision']}: {out['place'] or place} — "
                   f"{out['rule_verdict'] or 'no verdict'}",
        "query": out["query"],
        "place": out["place"],
        "rule_verdict": out["rule_verdict"],      # content axis (may be null)
        "evidence_tier": out["evidence_tier"],    # entitlement axis
        "decision": out["decision"],
        "citation": out["citation"],
        "conditions": out["conditions"],
        "caveat": out["caveat"],
        "staging_reason": out["staging_reason"],
    })
    return {"scope_receipt": scope_receipt, "answer_receipt": answer_receipt,
            "outcome": out, "decision": out["decision"]}
