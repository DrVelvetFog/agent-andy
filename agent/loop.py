"""The agent loop (Day 1 sketch).

Perceive -> propose -> check -> act -> receipt, in that order, every turn.
The brain (Muse Spark) proposes; the checker (local, different weights) rules;
the receipt chain records both; only then does anything execute. Voice in is
Muse Voice Transcribe; the daemon's unprompted comments obey policy.SPEAK_WHEN
and are receipted like any other action.

Day 1 ships the shape, not the wiring.
"""

from __future__ import annotations

from receipts import ReceiptChain

from . import tools


def run_turn(chain: ReceiptChain, utterance: str) -> list[dict]:
    """Handle one owner utterance. Day 1: a fixed echo plan, fully gated."""
    plan = [{"name": "echo", "summary": f"echo the owner utterance", "text": utterance}]
    outcomes = []
    for step in plan:
        outcomes.append(tools.run(chain, step.pop("name"), **step))
    return outcomes
