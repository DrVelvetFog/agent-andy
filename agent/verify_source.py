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
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from . import tier2

CONFIRMED_SECONDARY = "confirmed_secondary"

# Earned answers persist HERE — a separate, labeled file, never merged into Tier 1
# (data/detect_sample.toml). Tracked in the repo (not runs/, which is gitignored),
# so an owner-approved answer survives a new session. Secondary answers only, below
# Tier 1, never a primary citation.
PERSIST_FILE = Path(__file__).resolve().parent.parent / "data" / "confirmed_secondary.json"

# Every field an entry MUST carry to be written or loaded as an answer.
_REQUIRED = ("place", "url", "page_sha256", "verdict", "quote", "source",
             "verified_date", "approval_date", "approved_by", "caveat", "verify_promote_ref")

_PERSIST_NOTE = ("Secondary answers only. Andy read the SITE PAGE, not the ordinance. Each was "
                 "owner-approved on its approval_date. None of these is Tier 1 grade or a primary "
                 "citation. Delete an entry to revoke that answer — the place then stages again.")

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

    missing = [n for n, v in (("verdict", verdict), ("rule quote", quote),
                              ("named source", source), ("last-verified date", date)) if not v]
    if missing:
        return {"ok": False, "error": "page structure not recognized; missing " + ", ".join(missing)}
    # VERBATIM guard: the quote and the source must actually appear in the page.
    for name, val in (("rule quote", quote), ("source", source)):
        if val not in text:
            return {"ok": False, "error": f"{name} not verbatim in page — fail closed"}
    return {"ok": True, "verdict": verdict, "quote": quote, "source": source, "verified_date": date}


def _norm(s) -> str:
    return " ".join(str(s).lower().split()).strip(" .,?!")


def _pending_caveat(source: str) -> str:
    """The caveat shown on a PENDING proposal (pre-approval), so the owner sees
    exactly what approving would mean."""
    return (f"Secondary source — Andy read the site page, not the primary ordinance ({source}); "
            "confirm the primary before relying on it.")


def _caveat_full(source: str, approval_date: str) -> str:
    """The confirmed-secondary caveat, carrying the approval date, shown on the answer."""
    return (f"Secondary source — Andy read the site page, not the primary ordinance ({source}); "
            f"you approved this on {approval_date}. Confirm the primary before relying on it.")


def _entry_from_proposal(p: dict, approval_date: str, promote_ref: str) -> dict:
    """The persisted entry for an approved proposal — every required field present."""
    return {
        "place": p["place"], "url": p["url"], "page_sha256": p["page_sha256"],
        "verdict": p["verdict"], "quote": p["quote"], "source": p["source"],
        "verified_date": p["verified_date"], "approval_date": approval_date,
        "approved_by": "owner", "caveat": _caveat_full(p["source"], approval_date),
        "verify_promote_ref": promote_ref,
    }


def _confirmed_outcome(entry: dict) -> dict:
    """The detect-style outcome a confirmed-secondary place answers with — an answer
    WITH A CAVEAT: a secondary source that names a primary, owner-approved, carrying
    its approval date and page hash for the receipt. Never Tier-1 grade."""
    return {
        "query": entry["place"], "matched": True, "place": entry["place"],
        "rule_verdict": entry["verdict"].lower(),
        "evidence_tier": CONFIRMED_SECONDARY,
        "decision": None,  # detect sets ANSWERED_WITH_CAVEAT
        "citation": {"source": "wheretodetect.org (secondary, names a primary): " + entry["source"],
                     "url": entry["url"], "quote": entry["quote"]},
        "conditions": None,
        "caveat": entry["caveat"],
        "approval_date": entry["approval_date"],
        "page_sha256": entry["page_sha256"],
        "verify_promote_ref": entry["verify_promote_ref"],
        "staging_reason": None,
        "tier2_candidates": [], "tier2_reason": None,
    }


def _write_persist(path: Path, data: dict) -> None:
    """Atomic write: a temp file in the SAME directory, then rename — never a partial
    JSON on crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_persist(path: Path):
    """Load the earned-answers file. Returns (confirmed, invalid_keys, error). Fail
    closed: a missing file is simply empty; a malformed file, or an entry missing a
    required field, is NOT answered from — the caller stages with the reason."""
    if not path.exists():
        return {}, set(), None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, set(), "earned answers file unreadable"
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return {}, set(), "earned answers file unreadable"
    confirmed, invalid = {}, set()
    for key, entry in data["entries"].items():
        if not isinstance(entry, dict) or any(not entry.get(f) for f in _REQUIRED):
            invalid.add(_norm(key))
            continue
        confirmed[_norm(entry["place"])] = _confirmed_outcome(entry)
    return confirmed, invalid, None


class KnowledgeStore:
    """The owner's verified-and-approved answers, plus the one step of state the
    verify/approve commands need. Earned answers PERSIST across sessions in a
    separate file (data/confirmed_secondary.json), loaded on construction; they are
    secondary answers only, never Tier 1. Every change is also a receipt on the
    chain, and only approve writes to the file, after its receipt lands."""

    def __init__(self, persist_path=None) -> None:
        self.persist_path = Path(persist_path) if persist_path else PERSIST_FILE
        self.confirmed: dict = {}        # norm place -> confirmed-secondary outcome
        self.pending: dict = {}          # norm place -> proposal, awaiting the owner's yes
        self.last_candidate = None       # (place, url) from the most recent staged Tier-2 candidate
        loaded, invalid, err = _load_persist(self.persist_path)
        self.confirmed.update(loaded)    # earned answers carried over from a previous session
        self.invalid_places = invalid    # entries present but missing a required field
        self.persist_error = err         # the whole file is malformed / unreadable

    def get(self, place: str):
        return self.confirmed.get(_norm(place))

    def unreadable_reason(self, place: str):
        """Why a place can't be answered from the earned-answers file, if it can't:
        the whole file is unreadable, or this place's entry is missing a field. The
        caller states this when it stages, so a bad file never silently drops to
        Tier 2 without the reason."""
        if self.persist_error:
            return self.persist_error
        if _norm(place) in self.invalid_places:
            return "earned answers file unreadable"
        return None

    def note_candidate(self, place: str, url: str) -> None:
        self.last_candidate = (place, url)

    def pending_list(self) -> list[dict]:
        """Everything awaiting the owner's decision, each with its evidence — so the
        UI can show it before any Approve button, never a blind approval. Two kinds:
        a verify proposal (a secondary answer) and a task note (a write held because
        it depends on a staged result)."""
        out = []
        for p in self.pending.values():
            if p.get("kind") == "note":
                out.append({"kind": "note", "place": p["place"], "note_text": p["note_text"]})
            else:
                out.append({"kind": "verify", "place": p["place"], "url": p["url"],
                            "verdict": p["verdict"], "quote": p["quote"], "source": p["source"],
                            "verified_date": p["verified_date"], "caveat": _pending_caveat(p["source"])})
        return out

    def stage_note(self, chain, place: str, note_text: str) -> dict:
        """Hold a note for the owner's approval because it depends on a staged result.
        The note is NOT written until approved — it rides the SAME pending/approve
        path as a verify proposal, so the same buttons and intents work."""
        self.pending[_norm(place)] = {"kind": "note", "place": place, "note_text": note_text}
        chain.append({"type": "task_step", "step": "note", "status": "waiting",
                      "summary": f"note '{place}' waiting for owner approval (depends on a staged result)",
                      "place": place, "executed": False})
        return {"ok": True, "place": place}

    def decline(self, chain, place: str | None = None) -> dict:
        """The owner declines a pending proposal. Receipted; clears ONLY that
        proposal and leaves the place staged, never answered. It can be verified
        again later with a fresh fetch."""
        key = _norm(place) if place else (next(iter(self.pending)) if len(self.pending) == 1 else None)
        if key is None or key not in self.pending:
            return {"ok": False, "error": "nothing pending to decline"}
        if self.pending[key].get("kind") == "note":
            p = self.pending.pop(key)
            chain.append({"type": "task_declined", "step": "note",
                          "summary": f"owner declined the {p['place']} — step skipped, not written",
                          "place": p["place"], "declined_by": "owner",
                          "declined_on": time.strftime("%Y-%m-%d", time.gmtime())})
            return {"ok": True, "place": p["place"], "kind": "note", "skipped": True}
        p = self.pending.pop(key)
        chain.append({"type": "verify_decline",
                      "summary": f"owner declined {p['place']} — still staged, not answered",
                      "place": p["place"], "url": p["url"], "verdict": p["verdict"],
                      "source": p["source"], "declined_by": "owner",
                      "declined_on": time.strftime("%Y-%m-%d", time.gmtime())})
        return {"ok": True, "place": p["place"]}

    def propose(self, chain, place: str | None = None, url: str | None = None) -> dict:
        """Fetch + extract a candidate page, receipt both steps, and hold a pending
        proposal for the owner's approval. Fails closed — a bad fetch or an
        unrecognized page is staged, never guessed."""
        if not (place and url) and self.last_candidate:
            place, url = self.last_candidate
        if not (place and url):
            return {"ok": False, "error": "no candidate to verify yet — ask about a place first"}

        # Fetch restriction: Andy only ever fetches a URL that is already in the site
        # index it holds. Anything else — from any path — is refused WITHOUT a fetch.
        if url not in tier2.index_urls():
            chain.append({"type": "verify_fetch",
                          "summary": f"refused to fetch an out-of-index URL for {place}",
                          "place": place, "url": url, "fetched_ok": False,
                          "page_sha256": None, "bytes": None,
                          "reason": "URL not in site index"})
            return {"ok": False, "error": "URL not in site index — Andy only fetches pages in its site index"}

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
        secondary answer AND persist it. Order is fixed: the verify_promote receipt
        lands FIRST, then the entry is written atomically, keyed by place so a second
        approval updates in place and never duplicates. Never auto — approval only."""
        key = _norm(place) if place else (next(iter(self.pending)) if len(self.pending) == 1 else None)
        if key is None or key not in self.pending:
            return {"ok": False, "error": "nothing pending to approve"}
        if self.pending[key].get("kind") == "note":
            return self._confirm_note(chain, key)
        p = self.pending.pop(key)
        approval_date = time.strftime("%Y-%m-%d", time.gmtime())
        receipt = chain.append({"type": "verify_promote",
                                "summary": f"owner approved {p['place']} as a confirmed secondary answer",
                                "place": p["place"], "url": p["url"], "verdict": p["verdict"],
                                "source": p["source"], "page_sha256": p["page_sha256"],
                                "approved_by": "owner", "approved_on": approval_date})
        entry = _entry_from_proposal(p, approval_date, receipt["hash"])  # ref = the receipt's hash
        self.confirmed[key] = _confirmed_outcome(entry)
        self.invalid_places.discard(key)
        self._persist_put(key, entry)
        return {"ok": True, "place": p["place"]}

    def _persist_put(self, key: str, entry: dict) -> None:
        """Write/update ONE entry in the earned-answers file, atomically. Called only
        from confirm(), after the verify_promote receipt — fetch/extract/decline never
        write here."""
        data = {"note": _PERSIST_NOTE, "entries": {}}
        if self.persist_path.exists():
            try:
                cur = json.loads(self.persist_path.read_text(encoding="utf-8"))
                if isinstance(cur, dict) and isinstance(cur.get("entries"), dict):
                    data["entries"] = dict(cur["entries"])
            except Exception:
                pass  # a previously-bad file is replaced by a clean one on this write
        data["entries"][key] = entry
        _write_persist(self.persist_path, data)
        self.persist_error = None  # the file is good again after a successful write

    def _confirm_note(self, chain, key: str) -> dict:
        """Owner approved a held note: an approval receipt lands first, then the note
        is written through the EXISTING note tool (sandboxed) — no new tool."""
        from . import tools
        p = self.pending.pop(key)
        chain.append({"type": "task_approved", "step": "note",
                      "summary": f"owner approved writing the {p['place']}",
                      "place": p["place"], "approved_by": "owner",
                      "approved_on": time.strftime("%Y-%m-%d", time.gmtime())})
        res = tools.run(chain, "note", summary=f"save the {p['place']} to the sandbox", text=p["note_text"])
        return {"ok": True, "place": p["place"], "kind": "note", "note_written": res["executed"]}
