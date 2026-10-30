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

from receipts import signing

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


# The one site verify-on-demand reads from. A redirect may move within it, never off it.
SITE = "https://wheretodetect.org/"


class _LeftSite(Exception):
    """A redirect pointed outside the allowed site; it was not followed."""


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Record every redirect hop in order, and refuse — without requesting it — a
    hop that leaves `allowed`."""

    def __init__(self, hops: list, allowed: str | None):
        super().__init__()
        self.hops, self.allowed = hops, allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops.append(newurl)
        if self.allowed and not newurl.startswith(self.allowed):
            raise _LeftSite(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, timeout: float = 30.0, allowed_prefix: str | None = SITE) -> dict:
    """Read-only GET. Returns the page and a hash of exactly what was fetched, the
    final url it was read from, and the redirect chain (requested url, each hop,
    final url) — or an error, with the chain so far. Never raises. A redirect that
    leaves `allowed_prefix` is not followed."""
    hops = [url]
    try:
        opener = urllib.request.build_opener(_Redirects(hops, allowed_prefix))
        req = urllib.request.Request(url, headers={"User-Agent": "agent-andy-verify"})
        with opener.open(req, timeout=timeout) as r:
            raw, final = r.read(), r.geturl()
    except _LeftSite as e:
        return {"ok": False, "error": f"redirect leaves {allowed_prefix} (to {e}) — not followed",
                "final_url": str(e), "redirect_chain": hops, "left_site": True}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "final_url": hops[-1], "redirect_chain": hops}
    if final != hops[-1]:
        return {"ok": False, "error": "redirect chain could not be determined",
                "final_url": final, "redirect_chain": hops}
    return {"ok": True, "html": raw.decode("utf-8", "replace"),
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "final_url": final, "redirect_chain": hops}


def _several_pages(place: str, url: str) -> list:
    """The page labels to choose between when `place` matches several site pages
    only partially; empty when `url` is an exact label match or the only match."""
    name, _, st = place.partition(",")
    n = len(tier2.index_urls())
    cands = tier2.candidates(name.strip(), st.strip() or None, limit=n) + tier2.candidates(place, limit=n)
    if any(c["url"] == url and _norm(c["label"]) in {_norm(name), _norm(place)} for c in cands):
        return []
    labels = list(dict.fromkeys(c["label"] for c in cands))
    return labels if len(labels) > 1 else []


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


# The verdict words the extractor (_VERDICT) can produce, lower-cased.
_VERDICT_WORDS = ("allowed", "permitted", "prohibited", "restricted", "limited", "not allowed")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _is_day(v: str) -> bool:
    if not _DAY.fullmatch(v):
        return False
    try:
        time.strptime(v, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _entry_problem(entry) -> str | None:
    """Why a persisted entry may NOT be answered from, or None if it may.

    MINIMUM checks only: every required field is a non-empty string, and the entry
    has the shape confirm() writes — a verdict the extractor can produce, an indexed
    wheretodetect.org page that the site-index lookup gives for that place (the same
    lookup that offered it for approval), a sha256 page hash, real dates,
    approved_by "owner", and a receipt-hash-shaped verify_promote_ref. This
    shape check does not prove the approval happened; the file's signature does
    (see _load_persist), so a well-formed forged entry in an unsigned or re-signed
    file is not answered."""
    if not isinstance(entry, dict):
        return "entry is not an object"
    for f in _REQUIRED:
        if not isinstance(entry.get(f), str) or not entry[f].strip():
            return f"{f} is missing or not a non-empty string"
    if entry["verdict"].strip().lower() not in _VERDICT_WORDS:
        return "verdict is not one the extractor produces"
    if not entry["url"].startswith("https://wheretodetect.org/"):
        return "url is not a wheretodetect.org page"
    if entry["url"] not in tier2.index_urls():
        return "url is not in the site index"
    # The place must lead to this url through the site-index lookup that proposed it
    # (detect splits off a ", <state>"; "verify <place>" does not) — a label match,
    # exact or partial, exactly as the candidate was found.
    place, n = entry["place"], len(tier2.index_urls())
    name, _, st = place.partition(",")
    found = {c["url"] for c in tier2.candidates(name.strip(), st.strip() or None, limit=n)}
    found |= {c["url"] for c in tier2.candidates(place, limit=n)}
    if entry["url"] not in found:
        return "place does not match the site-index label for its url"
    if not _HEX64.fullmatch(entry["page_sha256"]):
        return "page_sha256 is not 64 lowercase hex characters"
    if not (_is_day(entry["verified_date"]) and _is_day(entry["approval_date"])):
        return "verified_date / approval_date is not a YYYY-MM-DD date"
    if entry["approved_by"] != "owner":
        return "approved_by is not 'owner'"
    if not _HEX64.fullmatch(entry["verify_promote_ref"]):
        return "verify_promote_ref is not a receipt hash"
    return None


def _signature_problem(path: Path) -> str | None:
    """Why the earned-answers file's signature doesn't vouch for it, or None if it
    VERIFIES against Andy's public key."""
    state, reason = signing.verify_file(path)
    if state == signing.VERIFIED:
        return None
    if state == signing.UNSIGNED:
        return f"earned answers are UNSIGNED ({reason})"
    return f"earned answers signature FAIL ({reason})"


def _load_persist(path: Path):
    """Load the earned-answers file. Returns (confirmed, invalid_keys, error,
    signature_problem). Fail closed: a missing file is simply empty; a malformed
    file, or an entry that fails _entry_problem, is NOT answered from — the caller
    stages with the reason. A file with entries must also carry a signature that
    VERIFIES against Andy's public key; if not, every entry in it stages."""
    if not path.exists():
        return {}, set(), None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, set(), "earned answers file unreadable", None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return {}, set(), "earned answers file unreadable", None
    confirmed, invalid = {}, set()
    problem = _signature_problem(path) if data["entries"] else None
    if problem:
        for key, entry in data["entries"].items():
            invalid.add(_norm(key))
            if isinstance(entry, dict) and isinstance(entry.get("place"), str):
                invalid.add(_norm(entry["place"]))
        return {}, invalid, None, problem
    for key, entry in data["entries"].items():
        if _entry_problem(entry) is not None:
            invalid.add(_norm(key))
            if isinstance(entry, dict) and isinstance(entry.get("place"), str):
                invalid.add(_norm(entry["place"]))   # stage the place it names, too
            continue
        confirmed[_norm(entry["place"])] = _confirmed_outcome(entry)
    return confirmed, invalid, None, None


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
        loaded, invalid, err, sig_problem = _load_persist(self.persist_path)
        self.confirmed.update(loaded)    # earned answers carried over from a previous session
        self.invalid_places = invalid    # entries present but malformed, or in an unsigned file
        self.persist_error = err         # the whole file is malformed / unreadable
        self.signature_problem = sig_problem  # the file has entries but no signature that verifies

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
            return self.signature_problem or "earned answers file unreadable"
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
        unrecognized page is staged, never guessed. The requested url must be in the
        site index, and so must the FINAL url after redirects; a redirect that leaves
        wheretodetect.org is not followed. When the place matches several pages only
        partially, nothing is fetched until the owner names one. The receipt and the
        proposal carry the requested url, the final url, and the redirect chain."""
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

        # Several pages match only partially: the owner picks one; nothing is fetched.
        choices = _several_pages(place, url)
        if choices:
            chain.append({"type": "verify_fetch",
                          "summary": f"several site pages match {place} — owner to pick one, nothing fetched",
                          "place": place, "url": url, "fetched_ok": False,
                          "page_sha256": None, "bytes": None, "candidates": choices,
                          "reason": "several site pages match; owner must pick one"})
            return {"ok": False, "error": (f"several site pages match “{place}”: {', '.join(choices)} — "
                                           "say “verify <page name>” to pick one; nothing was fetched")}

        f = fetch(url)
        final = f.get("final_url", url)
        hops = f.get("redirect_chain") or [url]
        reason = f.get("error")
        if f["ok"] and any(not h.startswith(SITE) for h in hops):
            reason = "a redirect left wheretodetect.org — fail closed"
        elif f["ok"] and final not in tier2.index_urls():
            reason = "the final url after redirects is not in the site index — fail closed"
        accepted = f["ok"] and reason is None
        chain.append({"type": "verify_fetch",
                      "summary": (f"fetched candidate page for {place}" if accepted
                                  else f"refused the fetched page for {place}" if f["ok"]
                                  else f"could not fetch the candidate page for {place}"),
                      "place": place, "url": url, "requested_url": url, "final_url": final,
                      "redirect_chain": hops, "fetched_ok": accepted, "read": f["ok"],
                      "page_sha256": f.get("sha256"), "bytes": f.get("bytes"),   # of the FINAL page
                      "reason": reason})
        if not f["ok"]:
            return {"ok": False, "error": f"couldn't fetch the page ({f['error']}) — check by hand"}
        if not accepted:
            return {"ok": False, "error": f"{reason} — staged, check by hand"}

        ex = extract(f["html"])
        chain.append({"type": "verify_extract",
                      "summary": f"extracted rule for {place} (deterministic, verbatim-checked)",
                      "place": place, "url": final, "extract_ok": ex["ok"],
                      "verdict": ex.get("verdict"), "quote": ex.get("quote"),
                      "source": ex.get("source"), "verified_date": ex.get("verified_date"),
                      "verbatim_in_page": ex["ok"],  # True only when the quote was found verbatim
                      "staged_for_approval": True, "executed": False, "reason": ex.get("error")})
        if not ex["ok"]:
            return {"ok": False, "error": f"couldn't extract the rule ({ex['error']}) — staged, check by hand"}

        proposal = {"place": place, "url": final, "requested_url": url, "redirect_chain": hops,
                    "page_sha256": f["sha256"], "verdict": ex["verdict"], "quote": ex["quote"],
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
        signed = self._persist_put(key, entry)
        return {"ok": True, "place": p["place"], "signed": signed}

    def _persist_put(self, key: str, entry: dict) -> None:
        """Write/update ONE entry in the earned-answers file, atomically, then sign the
        file with Andy's key. Called only from confirm(), after the verify_promote
        receipt — fetch/extract/decline never write here. Existing entries are carried
        over ONLY if the file's signature verifies, so signing never launders an entry
        nobody signed. Without the key the file is written UNSIGNED, and its entries
        stage after a restart. Returns whether the file is now signed."""
        data = {"note": _PERSIST_NOTE, "entries": {}}
        if self.persist_path.exists() and _signature_problem(self.persist_path) is None:
            try:
                cur = json.loads(self.persist_path.read_text(encoding="utf-8"))
                if isinstance(cur, dict) and isinstance(cur.get("entries"), dict):
                    data["entries"] = dict(cur["entries"])
            except Exception:
                pass  # a previously-bad file is replaced by a clean one on this write
        data["entries"][key] = entry
        _write_persist(self.persist_path, data)
        self.persist_error = None  # the file is good again after a successful write
        signed = signing.sign_file(self.persist_path)
        self.signature_problem = None if signed else _signature_problem(self.persist_path)
        return signed

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
        return {"ok": True, "place": p["place"], "kind": "note", "note_written": res["executed"],
                "note_text": p["note_text"]}
