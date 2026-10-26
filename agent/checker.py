"""Policy checker — the gate between the brain and every tool.

TODAY THIS IS A DETERMINISTIC PLACEHOLDER. It rules on an action using only the
fixed scope rules in policy.py — no model, no network. It is NOT yet the
open-weight model checker (Muse Glimmer / Spark Open) described in the README
architecture; wiring a genuinely-run, verifiable open-weight judge is a later
step, and the Meta open-weights bonus needs a real verified run, not a claim.
This is labelled a placeholder on purpose so nothing here overstates it.

Three outcomes, and the gate fails closed — an empty or unrecognised action is
never silently allowed:
  allow - safe local work within the owner's task; the tool runs.
  stage - irreversible or destructive; held for a human, the tool does NOT run.
  block - off-scope (off-machine, about a person, a secret field); refused.
"""

from __future__ import annotations

from . import policy

ALLOW, STAGE, BLOCK = "allow", "stage", "block"
CHECKER = "deterministic-scope-placeholder"


def evaluate(action: dict) -> dict:
    """Return a verdict dict for one proposed action."""
    summary = str(action.get("summary", "")).lower()
    if not summary:
        return {"verdict": BLOCK, "rule": "empty action", "checker": CHECKER}
    for trigger in policy.BLOCK_TRIGGERS:
        if trigger in summary:
            return {"verdict": BLOCK, "rule": f"off-scope: matched '{trigger.strip()}'", "checker": CHECKER}
    for trigger in policy.STAGE_TRIGGERS:
        if trigger in summary:
            return {"verdict": STAGE, "rule": f"irreversible: matched '{trigger.strip()}'", "checker": CHECKER}
    if action.get("irreversible", False):
        return {"verdict": STAGE, "rule": "irreversible: flagged by caller", "checker": CHECKER}
    return {"verdict": ALLOW, "rule": "within policy scope", "checker": CHECKER}
