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

from . import checker, tier2

SAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "detect_sample.toml"

# Tier 2 (the sitemap-derived index) can only add a candidate to a STAGE. When it
# does, this is the reason that lands in the receipt — plainly NOT a verdict.
TIER2_REASON = ("site-index candidate found; primary source not independently "
                "verified — a human must check the primary before any verdict.")

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


def _split_place_state(place: str) -> tuple[str, str | None]:
    """A trailing ', <state>' is used only to filter Tier 2 candidates; the Tier 1
    lookup still uses the whole string. 'Daytona Beach, Florida' -> ('Daytona Beach',
    'Florida'); 'Tybee Island' -> ('Tybee Island', None)."""
    if "," in place:
        name, _, st = place.partition(",")
        return name.strip(), (st.strip() or None)
    return place, None


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
    elif tier == "corroborated":
        # An enacted citation corroborated by more than one readable source but not
        # yet confirmed by a direct read of the primary. It ANSWERS with its caveat in
        # BOTH normal and strict mode — the caveat, not a stage, carries the limitation.
        # Strict mode only tightens; it never loosens, so a corroborated citation that
        # answers in normal mode must answer in strict mode too.
        out["decision"] = ANSWERED_WITH_CAVEAT
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


def blocked_outcome(place: str, scope: dict | None) -> dict:
    """The STAGED outcome for a lookup the checker did not allow (block or stage).
    Nothing was looked up, so there is no verdict and no citation; the staging
    reason states the checker's verdict, reason, and rule. `scope_verdict` lets a
    reply say it was the checker that held it, not a missing source."""
    v = scope or {"verdict": checker.BLOCK, "reason": "no checker verdict — fail closed",
                  "rule": "missing-verdict"}
    did = {checker.BLOCK: "blocked", checker.STAGE: "held"}.get(v.get("verdict"), "did not allow")
    return {
        "query": place, "matched": False, "place": None, "rule_verdict": None,
        "evidence_tier": "not_looked_up", "decision": STAGED, "citation": None,
        "conditions": None, "caveat": None,
        "staging_reason": (f"The checker {did} this lookup — {v.get('reason')} "
                           f"({v.get('verdict')}, rule: {v.get('rule')}); nothing was looked up."),
        "tier2_candidates": [], "tier2_reason": None, "scope_verdict": v,
    }


def outcome_of(res: dict, place: str) -> dict:
    """The outcome to act on from an answer() result. A lookup the checker did not
    allow already comes back STAGED; if an outcome ever arrives as None, rebuild it
    from the scope receipt's verdict — callers never index into None."""
    if res.get("outcome") is not None:
        return res["outcome"]
    scope = ((res.get("scope_receipt") or {}).get("action") or {}).get("verdict")
    return blocked_outcome(place, scope)


def answer(chain, place: str, strict: bool = False, store=None) -> dict:
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
        # Not looked up — but still a real STAGED outcome, so every caller replies
        # with the checker's verdict instead of crashing on a missing outcome.
        return {"scope_receipt": scope_receipt, "answer_receipt": None,
                "outcome": blocked_outcome(place, scope), "decision": STAGED}

    out = evaluate_query(place, strict=strict)
    out["tier2_candidates"] = []
    out["tier2_reason"] = None

    # Only a STAGE can be changed from here — a Tier 1 answer is never touched.
    if out["decision"] == STAGED:
        # A place the owner VERIFIED and APPROVED earlier this session answers as a
        # confirmed secondary (names a primary), overriding the stage.
        confirmed = store.get(place) if store is not None else None
        if confirmed is not None:
            out = dict(confirmed)
            out["query"] = place
            out["decision"] = ANSWERED_WITH_CAVEAT
        else:
            # If the earned-answers file is unreadable (or this place's entry is
            # broken), say so — a bad file never silently drops to Tier 2.
            if store is not None:
                ur = store.unreadable_reason(place)
                if ur:
                    out["persist_error"] = ur
                    out["staging_reason"] = (out["staging_reason"] or "needs a human") + \
                        " — earned answers file unreadable, so no saved answer was used"
            # Otherwise Tier 2 (the sitemap index) can add a candidate to the stage,
            # and we remember it so "verify it" knows which page to fetch.
            name, st = _split_place_state(place)
            cands = tier2.candidates(name, st)
            if cands:
                out["tier2_candidates"] = cands
                out["tier2_reason"] = TIER2_REASON
                if store is not None:
                    store.note_candidate(place, cands[0]["url"])

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
        "tier2_candidates": out["tier2_candidates"],  # index candidates — NOT verdicts
        "tier2_reason": out["tier2_reason"],
        # Confirmed-secondary provenance (present only on a persisted/approved answer):
        "approval_date": out.get("approval_date"),
        "page_sha256": out.get("page_sha256"),
        "verify_promote_ref": out.get("verify_promote_ref"),
        "persist_error": out.get("persist_error"),
    })
    return {"scope_receipt": scope_receipt, "answer_receipt": answer_receipt,
            "outcome": out, "decision": out["decision"]}
