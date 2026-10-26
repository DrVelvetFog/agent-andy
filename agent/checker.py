"""Policy checker (Day 1 stub).

The checker stands between the brain and every tool: nothing executes unless
the checker allows it, and the checker's verdict is itself receipted. The
planned implementation runs a local open-weight model (Muse Glimmer) so the
judge is a different brain on different weights than the actor; this Day 1
version enforces the deterministic rules in policy.py only.
"""

from __future__ import annotations

from . import policy

ALLOW, BLOCK, ESCALATE = "allow", "block", "escalate"


def evaluate(action: dict) -> dict:
    """Return a verdict dict for one proposed action. Fail closed."""
    summary = str(action.get("summary", "")).lower()
    if not summary:
        return {"verdict": BLOCK, "rule": "empty action"}
    for rule in policy.NEVER:
        if any(word in summary for word in rule.split() if len(word) > 4):
            return {"verdict": BLOCK, "rule": rule}
    if action.get("irreversible", False):
        return {"verdict": ESCALATE, "rule": "irreversible actions need a human"}
    return {"verdict": ALLOW, "rule": "within policy"}
