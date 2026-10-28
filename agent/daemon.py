"""Daemon: Andy's one proactive-suggestion surface.

Not a second agent, not a persona, not a voice of its own. The daemon sits on
top of the existing gated loop and does exactly one thing: when a task finishes
having STAGED something — an item Andy held back on instead of answering, like a
place it could not verify — it may surface ONE visible, dismissible suggestion
("hold that item for a human") during that active task.

The rules are hard, and they are enforced here, not just documented:

  * Silent outside an active task. The daemon never speaks on its own; it only
    reacts at the end of a task the owner started.
  * At most once per active task, on the staged-receipt trigger ONLY. No other
    trigger, no other kind of suggestion, no chatter.
  * Never about a person, a text field, or off-task content — even inside an
    active task. If the staged thing trips the never-list, the daemon stays quiet.
  * One dismissal silences it for the rest of the SESSION, and the dismissal is
    itself a receipt, so a reader of the chain sees the daemon was turned off.
  * It NEVER executes. A suggestion is gated by the same deterministic policy
    engine as any action and receipted WITH its verdict, but the daemon only
    surfaces it — the tool is never run from here. Acting on it is the human's
    move. `executed` is always False on a daemon_suggestion receipt.
  * If it speaks, it uses the existing speak() seam (agent/voice.py) — it does
    not get its own voice, name, or avatar.
"""

from __future__ import annotations

from . import checker, detect, policy, voice

TRIGGER = "staged_receipt"

# The daemon never speaks about any of these, even inside an active task. Matched
# case-insensitively against the staged item's label and reason.
NEVER_LIST = (
    "person", "people", "someone", "somebody", "coworker", "colleague",
    "appearance", "how they look", "their name", "name is", "text field",
    "input field", "form field", "password", "credit card", "ssn", "api key",
    "secret", "off-task", "off task", "unrelated to the task",
)


class Daemon:
    """One per session. Holds the two pieces of state the rules need: whether it
    has been dismissed (session-wide), and whether it has already spoken in the
    current task (so it speaks at most once per task)."""

    def __init__(self) -> None:
        self.dismissed = False
        self._spoke_in_task = False

    def new_task(self) -> None:
        """Mark the start of a task so the once-per-task limit resets."""
        self._spoke_in_task = False

    def observe(self, chain, outcome, active_task: bool = True,
                voice_mode: str | bool = "auto") -> dict | None:
        """At the end of a task, maybe surface ONE suggestion. Returns the
        suggestion result when it speaks, else None. It writes receipts only when
        it actually surfaces something — a silent daemon leaves no trace but the
        task's own receipts."""
        staged = _staged_detail(outcome)
        # The declared speaking policy (agent/policy.py: SPEAK_WHEN, DISMISSAL_SCOPE)
        # governs WHEN the daemon may speak unprompted. The daemon honors it; it does
        # not re-decide it. All three conditions must hold — no task, no above-the-bar
        # evidence (a staged item), or a prior dismissal each keep it silent.
        conditions = {
            "task_active": bool(active_task),
            "evidence_above_checker_bar": staged is not None,
            "not_dismissed_this_session": not self.dismissed,
        }
        if not all(conditions[k] for k, required in policy.SPEAK_WHEN.items() if required):
            return None
        if self._spoke_in_task:       # at most once per active task
            return None
        if _on_never_list(staged["label"], staged["reason"]):
            return None               # never about people / text fields / off-task

        # Form the suggestion as an ACTION and gate it with the same engine as any
        # action — then receipt it, NOT run it. The daemon only surfaces.
        suggested = {
            "type": "tool", "tool": "hold_for_review", "daemon": True,
            "summary": f"hold the staged item '{staged['label']}' for human review",
        }
        verdict = checker.evaluate(suggested)
        text = (f"Heads up — I staged {staged['label']} instead of answering it, "
                f"because {staged['reason'] or 'it needs a human'}. "
                f"Want me to hold it for your review? Dismiss to silence me.")

        receipt = chain.append({
            "type": "daemon_suggestion",
            "summary": f"daemon suggestion: hold '{staged['label']}' for review",
            "trigger": TRIGGER,
            "about": staged["label"],
            "above_checker_bar": True,     # a staged item is worth a human's attention
            "dismissible": True,
            "suggested_action": suggested,
            "verdict": verdict,            # gated like any action...
            "executed": False,             # ...but NEVER executed by the daemon
            "spoken": text,
        })
        reply = voice.speak(text, chain, voice=voice_mode)   # the shared speak() seam
        self._spoke_in_task = True
        return {"spoke": True, "about": staged["label"], "text": text,
                "verdict": verdict, "executed": False, "receipt": receipt, "reply": reply}

    def dismiss(self, chain) -> dict:
        """The owner dismisses the daemon. Visible and receipted; it will not
        speak again for the rest of this session."""
        self.dismissed = True
        receipt = chain.append({
            "type": "daemon_dismissed",
            "summary": "daemon dismissed by owner — silent for the rest of the session",
            "silenced_session": True,
        })
        return {"dismissed": True, "receipt": receipt}


def _staged_detail(outcome) -> dict | None:
    """Pull the staged item out of a task outcome, or None if nothing was staged.
    Reads the detect result shape (the one beat's trigger); anything else — an
    answered detect, a witness result, a loop outcome list — yields None."""
    if not isinstance(outcome, dict):
        return None
    if outcome.get("decision") != detect.STAGED:
        return None
    o = outcome.get("outcome") or {}
    label = o.get("place") or o.get("query") or "the staged item"
    reason = o.get("staging_reason") or ""
    return {"label": str(label), "reason": str(reason)}


def _on_never_list(label: str, reason: str) -> bool:
    hay = f"{label} {reason}".lower()
    return any(term in hay for term in NEVER_LIST)
