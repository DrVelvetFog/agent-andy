"""The agent loop.

Perceive -> propose -> check -> act -> receipt, in that order, every turn.
The brain (Muse Spark) proposes a plan; the checker (a local, deterministic
policy engine in its own trust domain) rules on each step; the receipt chain
records the proposal and every verdict; only an allowed step executes. Nothing
reaches a tool without a receipt in front of it.
"""

from __future__ import annotations

from receipts import ReceiptChain

from . import brain, tools


def run_turn(chain: ReceiptChain, utterance: str) -> list[dict]:
    """Handle one owner utterance as a full gated turn.

    1. perceive + propose: Spark turns the utterance into a short plan.
    2. receipt the proposal, so the actor's intent is on the record before
       any judgment or execution.
    3. for each step: check -> receipt -> act (only if allowed).
    """
    proposal = brain.propose(utterance)
    plan = proposal["steps"]
    chain.append(
        {
            "type": "plan",
            "summary": f"plan for: {utterance[:80]}",
            "utterance": utterance,
            "steps": plan,
            "planner": proposal["planner"],   # muse-spark-1.3, or the local echo fallback and why
        }
    )

    outcomes: list[dict] = []
    for step in plan:
        outcomes.append(
            tools.run(chain, step["tool"], summary=step["summary"], **step.get("args", {}))
        )
    return outcomes
