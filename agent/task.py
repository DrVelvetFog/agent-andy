"""A safe, multi-step demo task — real work, only with tools already in the repo.

The rehearsed request is "Check Myrtle Beach and Tybee Island for my trip, and save
a note with the results." It expands to ONE plan, receipted before any step runs,
then each step goes through the EXISTING gate: detect (a read) for each place, and
the sandboxed note writer for the result. No new tool, no new planner, no new
checker — this wires a fixed plan through what the repo already has.

The staged step is the point: Tybee stages as unverified, so the note depends on a
staged result and is HELD for the owner (the same pending/approve path as a verify
proposal). Andy will not write a note that presents Tybee as allowed or silently
drops it. On approval the note is written stating both results honestly; on decline
the note step is skipped and receipted as skipped. A blocked extra (e.g. "wire
$5,000") is ruled on by the checker, receipted, and never poisons the safe steps.
"""

from __future__ import annotations

import re

from . import checker, detect

# "check <places> ... save/write a note"
TASK_RE = re.compile(r"\bcheck\b.+\bsave\b.+\bnote\b", re.IGNORECASE)
_PLACES_RE = re.compile(
    r"check\s+(.+?)\s+(?:for my trip|,?\s*and\s+(?:save|write|wire|send|pay|transfer))", re.IGNORECASE)
_PAYMENT_RE = re.compile(r"\b(wire|transfer|pay|send)\b[^.]*?(\$\s?[\d,]+)", re.IGNORECASE)


def is_task(message: str) -> bool:
    return bool(TASK_RE.search(message))


def _parse(message: str):
    m = _PLACES_RE.search(message)
    places = [p.strip() for p in re.split(r"\s+and\s+|,\s*", m.group(1))] if m else []
    places = [p for p in places if p]
    blocked = [f"{verb} {amt}".strip() for verb, amt in _PAYMENT_RE.findall(message)]
    return places, blocked


def _note_text(outcomes: list) -> str:
    lines = ["Trip notes — metal detecting:"]
    for place, o in outcomes:
        if o["decision"] in (detect.ANSWERED, detect.ANSWERED_WITH_CAVEAT):
            cit = o.get("citation") or {}
            lines.append(f"- {place}: ALLOWED ({o.get('rule_verdict')}). "
                         f"Source: {cit.get('source', '')} ({cit.get('url', '')}).")
        else:
            lines.append(f"- {place}: UNVERIFIED — STAGED, not answered. "
                         f"Reason: {o.get('staging_reason', 'needs a human')}")
    return "  ".join(lines)


def run_trip(chain, message: str, store, strict: bool = False) -> dict:
    """Receipt the plan, run each detect step through the gate, block any payment
    step, and hold the note for the owner's approval when a result staged."""
    places, blocked = _parse(message)
    if not places:
        places = ["Myrtle Beach", "Tybee Island"]  # the rehearsed demo

    steps = [{"n": i + 1, "step": "detect", "target": p} for i, p in enumerate(places)]
    for b in blocked:
        steps.append({"n": len(steps) + 1, "step": "blocked_request", "detail": b})
    steps.append({"n": len(steps) + 1, "step": "note", "detail": "write a trip note with the results"})
    chain.append({"type": "task_plan", "summary": f"trip task plan: {len(steps)} steps",
                  "utterance": message, "steps": steps})

    # Steps 1..k: detect each place through the existing gate (a read).
    outcomes, any_staged = [], False
    for p in places:
        o = detect.answer(chain, p, strict=strict, store=store)["outcome"]
        outcomes.append((p, o))
        any_staged = any_staged or o["decision"] == detect.STAGED

    # Blocked extras: ruled on by the checker, receipted, never executed.
    blocked_results = []
    for b in blocked:
        action = {"type": "tool", "tool": "task_step", "summary": b}
        verdict = checker.evaluate(action)
        chain.append({**action, "verdict": verdict, "executed": False, "step": "blocked_request"})
        blocked_results.append((b, verdict["verdict"], verdict["reason"], verdict["rule"]))

    # Note step: held for approval when any result staged; otherwise written.
    note_text = _note_text(outcomes)
    if any_staged:
        store.stage_note(chain, "trip note", note_text)
        note_status = "waiting"
    else:
        from . import tools
        note_status = "written" if tools.run(
            chain, "note", summary="save trip note", text=note_text)["executed"] else "not written"

    return {"intent": "task", "places": places, "outcomes": outcomes,
            "blocked": blocked_results, "note_status": note_status, "note_text": note_text,
            "reply": _reply(outcomes, blocked_results, note_status)}


def _reply(outcomes, blocked_results, note_status) -> str:
    parts, n = ["Here's the plan:"], 0
    for place, o in outcomes:
        n += 1
        if o["decision"] in (detect.ANSWERED, detect.ANSWERED_WITH_CAVEAT):
            parts.append(f"{n}) {place} — allowed (cited).")
        else:
            parts.append(f"{n}) {place} — staged, unverified (not answered).")
    for b, _v, reason, rule in blocked_results:
        n += 1
        parts.append(f"{n}) {b} — BLOCKED ({rule}): {reason}. Not executed.")
    n += 1
    if note_status == "waiting":
        parts.append(f"{n}) Trip note — WAITING for your approval, because a result is staged. Say "
                     "“approve” to write it (it will state Tybee as unverified, not allowed), "
                     "or “decline” to skip it.")
    elif note_status == "written":
        parts.append(f"{n}) Trip note — written to the sandbox.")
    else:
        parts.append(f"{n}) Trip note — not written.")
    return " ".join(parts)
