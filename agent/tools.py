"""Gated tool registry (Day 1 stub).

Every tool call goes through the same gate: the checker rules on the proposed
action first, the verdict and the action are receipted, and only an allowed
action executes. There is no path to a tool that skips the gate.
"""

from __future__ import annotations

from typing import Callable

from . import checker

_REGISTRY: dict[str, Callable[..., object]] = {}


def tool(name: str):
    def register(fn: Callable[..., object]):
        _REGISTRY[name] = fn
        return fn

    return register


def run(chain, name: str, **kwargs) -> dict:
    """Propose, check, receipt, then (only if allowed) execute."""
    action = {"type": "tool", "tool": name, "summary": kwargs.get("summary", name)}
    verdict = checker.evaluate(action)
    receipt = chain.append({**action, "verdict": verdict})
    result: object = None
    if verdict["verdict"] == checker.ALLOW and name in _REGISTRY:
        result = _REGISTRY[name](**kwargs)
    return {"receipt": receipt, "verdict": verdict, "result": result}


@tool("echo")
def _echo(summary: str = "", text: str = "") -> str:
    """Day 1 demonstration tool: does nothing but prove the gate shape."""
    return text
