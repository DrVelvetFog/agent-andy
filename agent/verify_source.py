"""Verify-on-demand: Andy earns new knowledge, with proof, on the owner's say-so.

A Tier 2 staged question offers a candidate SITE PAGE. On the owner's request Andy
FETCHES that page (read-only) and extracts — DETERMINISTICALLY, no model, so there
is nowhere for a hallucination to enter — the page's verdict, a VERBATIM rule
quote, the primary source it names, and its "last verified" date. Every quoted
string is checked to appear verbatim in the fetched page; if the page's structure
is not there, extraction FAILS CLOSED (no guess). The result is a PROPOSED answer,
staged for the owner's approval. Only on approval does the place become a usable
answer — a "confirmed secondary" that NAMES a primary (Andy read the site, not the
ordinance itself), clearly labeled, never Tier-1 grade. Every step is a receipt:
verify_fetch (url + a hash of what was fetched), verify_extract (the verbatim
quote), and verify_promote (the owner's approval).
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.request

CONFIRMED_SECONDARY = "confirmed_secondary"

# The verdict word sits right before the "Last verified" line — anchoring to that
# gets THIS page's verdict, not a "more spots nearby" one, with no emoji dependency.
_VERDICT = re.compile(r"(Allowed|Prohibited|Restricted|Limited|Permitted|Not allowed)\s+Last verified", re.I)
_DATE = re.compile(r"Last verified:\s*(\d{4}-\d{2}-\d{2})", re.I)
_RULE = re.compile(r"The rules\s+(.+?)\s+(?:Permit:|Why detect here|\U0001F4DE|More spots near)", re.S | re.I)
_SOURCE = re.compile(r"Source:\s*(.+?)(?:\.\s*Verify|Affiliate disclosure|Not legal advice|$)", re.S | re.I)


def _text(html: str) -> str:
    """Visible text: scripts/styles and tags stripped, whitespace collapsed."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&[a-z]+;", " ", text)
    return " ".join(text.split())


def fetch(url: str, timeout: float = 30.0) -> dict:
    """Read-only GET. Returns the page and a hash of exactly what was fetched, or
    an error — never raises."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agent-andy-verify"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "html": raw.decode("utf-8", "replace"),
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def extract(html: str) -> dict:
    """Deterministic, fail-closed extraction. Returns a verdict, a VERBATIM rule
    quote, the named source, and the verified date — or {ok: False} with a reason.
    Every returned quote is checked to be a verbatim substring of the page text."""
    text = _text(html)
    vm, dm, rm, sm = (_VERDICT.search(text), _DATE.search(text),
                      _RULE.search(text), _SOURCE.search(text))
    verdict = vm.group(1).strip() if vm else None
    quote = " ".join(rm.group(1).split()).strip() if rm else None
    source = " ".join(sm.group(1).split()).strip() if sm else None
    date = dm.group(1) if dm else None

    missing = [n for n, v in (("verdict", verdict), ("rule quote", quote), ("source", source)) if not v]
    if missing:
        return {"ok": False, "error": "page structure not recognized; missing " + ", ".join(missing)}
    # VERBATIM guard: the quote and the source must actually appear in the page.
    for name, val in (("rule quote", quote), ("source", source)):
        if val not in text:
            return {"ok": False, "error": f"{name} not verbatim in page — fail closed"}
    return {"ok": True, "verdict": verdict, "quote": quote, "source": source, "verified_date": date}


def _norm(s) -> str:
    return " ".join(str(s).lower().split()).strip(" .,?!")


def _confirmed_outcome(p: dict) -> dict:
    """The detect-style outcome a confirmed-secondary place answers with — an answer
    WITH A CAVEAT: a secondary source that names a primary, owner-approved."""
    return {
        "query": p["place"], "matched": True, "place": p["place"],
        "rule_verdict": p["verdict"].lower(),
        "evidence_tier": CONFIRMED_SECONDARY,
        "decision": None,  # detect sets ANSWERED_WITH_CAVEAT
        "citation": {"source": "wheretodetect.org (secondary, names a primary): " + p["source"],
                     "url": p["url"], "quote": p["quote"]},
        "conditions": None,
        "caveat": ("Secondary source — Andy read the site page, not the primary ordinance "
                   f"({p['source']}); you approved this. Confirm the primary before relying on it."),
        "staging_reason": None,
        "tier2_candidates": [], "tier2_reason": None,
    }


class KnowledgeStore:
    """Session memory of places the owner has verified and approved, plus the one
    step of state the verify/approve commands need. Nothing here is durable: a new
    session starts empty, and every change is also a receipt on the chain."""

    def __init__(self) -> None:
        self.confirmed: dict = {}        # norm place -> confirmed-secondary outcome
        self.pending: dict = {}          # norm place -> proposal, awaiting the owner's yes
        self.last_candidate = None       # (place, url) from the most recent staged Tier-2 candidate

    def get(self, place: str):
        return self.confirmed.get(_norm(place))

    def note_candidate(self, place: str, url: str) -> None:
        self.last_candidate = (place, url)

    def propose(self, chain, place: str | None = None, url: str | None = None) -> dict:
        """Fetch + extract a candidate page, receipt both steps, and hold a pending
        proposal for the owner's approval. Fails closed — a bad fetch or an
        unrecognized page is staged, never guessed."""
        if not (place and url) and self.last_candidate:
            place, url = self.last_candidate
        if not (place and url):
            return {"ok": False, "error": "no candidate to verify yet — ask about a place first"}

        f = fetch(url)
        chain.append({"type": "verify_fetch",
                      "summary": f"fetched candidate page for {place}",
                      "place": place, "url": url, "fetched_ok": f["ok"],
                      "page_sha256": f.get("sha256"), "bytes": f.get("bytes"),
                      "reason": f.get("error")})
        if not f["ok"]:
            return {"ok": False, "error": f"couldn't fetch the page ({f['error']}) — check by hand"}

        ex = extract(f["html"])
        chain.append({"type": "verify_extract",
                      "summary": f"extracted rule for {place} (deterministic, verbatim-checked)",
                      "place": place, "url": url, "extract_ok": ex["ok"],
                      "verdict": ex.get("verdict"), "quote": ex.get("quote"),
                      "source": ex.get("source"), "verified_date": ex.get("verified_date"),
                      "verbatim_in_page": ex["ok"],  # True only when the quote was found verbatim
                      "staged_for_approval": True, "executed": False, "reason": ex.get("error")})
        if not ex["ok"]:
            return {"ok": False, "error": f"couldn't extract the rule ({ex['error']}) — staged, check by hand"}

        proposal = {"place": place, "url": url, "page_sha256": f["sha256"],
                    "verdict": ex["verdict"], "quote": ex["quote"],
                    "source": ex["source"], "verified_date": ex["verified_date"]}
        self.pending[_norm(place)] = proposal
        return {"ok": True, "proposal": proposal}

    def confirm(self, chain, place: str | None = None) -> dict:
        """On the owner's approval, promote a pending proposal to a confirmed
        secondary answer for the session. Receipted; never auto — approval only."""
        key = _norm(place) if place else (next(iter(self.pending)) if len(self.pending) == 1 else None)
        if key is None or key not in self.pending:
            return {"ok": False, "error": "nothing pending to approve"}
        p = self.pending.pop(key)
        self.confirmed[key] = _confirmed_outcome(p)
        chain.append({"type": "verify_promote",
                      "summary": f"owner approved {p['place']} as a confirmed secondary answer",
                      "place": p["place"], "url": p["url"], "verdict": p["verdict"],
                      "source": p["source"], "page_sha256": p["page_sha256"],
                      "approved_by": "owner",
                      "approved_on": time.strftime("%Y-%m-%d", time.gmtime())})
        return {"ok": True, "place": p["place"]}
