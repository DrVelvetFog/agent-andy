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

The engine rules on the summary AND on every string in the action's "args" (the
payload a tool will actually act on). The most restrictive match wins: a block in
either blocks, else a stage in either stages. A clean summary cannot carry a
dirty payload past the gate.
"""

from __future__ import annotations

from . import policy

ALLOW, STAGE, BLOCK = "allow", "stage", "block"
TIERS = (ALLOW, STAGE, BLOCK)
CHECKER = "deterministic-policy-engine"


_RANK = {ALLOW: 0, STAGE: 1, BLOCK: 2}


class _MalformedRule(Exception):
    pass


def _v(verdict: str, reason: str, rule: str) -> dict:
    return {"verdict": verdict, "reason": reason, "rule": rule, "checker": CHECKER}


def normalize(text) -> str:
    """Lower-case and collapse whitespace, so a tab or doubled space ("wire\t$5")
    cannot slip between the words of a pattern."""
    return " ".join(str(text).lower().split())


def payload_strings(args) -> list[str]:
    """Every string in a tool's arguments, nested lists/dicts included, in a fixed order."""
    if isinstance(args, str):
        return [args]
    if isinstance(args, dict):
        return [s for k in sorted(args, key=str) for s in payload_strings(args[k])]
    if isinstance(args, (list, tuple)):
        return [s for v in args for s in payload_strings(v)]
    return []


def _first_match(text: str, ruleset: list):
    """The first rule (top to bottom) whose pattern appears in `text`, or None."""
    for rule in ruleset:
        tier = rule.get("tier")
        patterns = rule.get("any", [])
        if tier not in TIERS or not isinstance(patterns, list):
            raise _MalformedRule(str(rule.get("id", "?")))
        if any(str(p).lower() in text for p in patterns):
            return rule
    return None


def evaluate(action: dict) -> dict:
    """Return a verdict dict for one proposed action, from policy.toml."""
    try:
        pol = policy.rules()
        ruleset = pol["rules"]
        default_tier = pol.get("default_tier", BLOCK)
        default_reason = pol.get("default_reason", "no matching rule")
    except Exception as e:  # unreadable/malformed policy -> do not allow
        return _v(BLOCK, f"policy unavailable, fail closed: {type(e).__name__}", "policy-load-error")

    summary = normalize(action.get("summary", ""))
    if not summary:
        return _v(BLOCK, "empty action — nothing to judge, fail closed", "empty-action")

    # The summary first, then every payload string; the most restrictive match wins
    # (ties keep the earlier text, so a summary match is reported over a payload one).
    texts = [summary] + [normalize(t) for t in payload_strings(action.get("args"))]
    best = None
    for text in texts:
        try:
            rule = _first_match(text, ruleset)
        except _MalformedRule as e:
            return _v(BLOCK, f"malformed rule '{e}' — fail closed", "malformed-rule")
        if rule is not None and (best is None or _RANK[rule["tier"]] > _RANK[best["tier"]]):
            best = rule
    if best is not None:
        return _v(best["tier"], str(best.get("reason", "")), str(best.get("id", "?")))

    # A caller may flag an action irreversible even when no pattern matched.
    if action.get("irreversible", False):
        return _v(STAGE, "caller flagged this irreversible — held for a human", "caller-irreversible")

    if default_tier not in TIERS:
        return _v(BLOCK, "invalid default tier in policy — fail closed", "bad-default")
    return _v(default_tier, default_reason, "default")
