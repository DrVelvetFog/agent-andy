"""Policy checker — the gate between the brain and every tool.

A DETERMINISTIC POLICY ENGINE, by design: it reads the declarative rules in
policy.toml and rules on each proposed action. No model, no network, no GPU in
the live loop — every verdict is fast, repeatable, and auditable, which is what
we want standing in front of a live demo. It is deliberately NOT a model-based
or open-weight checker, and nothing here should be described as one.

It is also in its own trust domain, separate from the Spark brain: the brain
proposes, this engine disposes, on a separate code path with separate rules,
and the verdict is receipted before anything runs.

Three outcomes, and the engine fails closed — an empty action, a policy file it
cannot read, or a malformed rule is a block, never a silent allow:
  allow - safe local work within the owner's task; the tool runs.
  stage - irreversible or destructive; held for a human, the tool does NOT run.
  block - off-scope (off-machine, about a person, a secret field); refused.

Every verdict carries the reason the policy gave, so it lands in the receipt
and a reader of the chain sees why each step was allowed, held, or refused.
"""

from __future__ import annotations

from . import policy

ALLOW, STAGE, BLOCK = "allow", "stage", "block"
TIERS = (ALLOW, STAGE, BLOCK)
CHECKER = "deterministic-policy-engine"


def _v(verdict: str, reason: str, rule: str) -> dict:
    return {"verdict": verdict, "reason": reason, "rule": rule, "checker": CHECKER}


def evaluate(action: dict) -> dict:
    """Return a verdict dict for one proposed action, from policy.toml."""
    try:
        pol = policy.rules()
        ruleset = pol["rules"]
        default_tier = pol.get("default_tier", BLOCK)
        default_reason = pol.get("default_reason", "no matching rule")
    except Exception as e:  # unreadable/malformed policy -> do not allow
        return _v(BLOCK, f"policy unavailable, fail closed: {type(e).__name__}", "policy-load-error")

    summary = str(action.get("summary", "")).lower()
    if not summary:
        return _v(BLOCK, "empty action — nothing to judge, fail closed", "empty-action")

    for rule in ruleset:
        tier = rule.get("tier")
        patterns = rule.get("any", [])
        if tier not in TIERS or not isinstance(patterns, list):
            return _v(BLOCK, f"malformed rule '{rule.get('id', '?')}' — fail closed", "malformed-rule")
        if any(str(p).lower() in summary for p in patterns):
            return _v(tier, str(rule.get("reason", "")), str(rule.get("id", "?")))

    # A caller may flag an action irreversible even when no pattern matched.
    if action.get("irreversible", False):
        return _v(STAGE, "caller flagged this irreversible — held for a human", "caller-irreversible")

    if default_tier not in TIERS:
        return _v(BLOCK, "invalid default tier in policy — fail closed", "bad-default")
    return _v(default_tier, default_reason, "default")
