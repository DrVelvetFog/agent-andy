"""Gated tool registry.

Every tool call goes through the same gate, in this order: the checker rules
on the proposed action, the action and its verdict are receipted, and only an
ALLOWED action executes. A staged or blocked action is still receipted — it
just never runs. There is no path to a tool that skips the gate.

Today's tools are safe, local, and confined to a sandbox directory: no web, no
system commands.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from . import checker

SANDBOX = Path(__file__).resolve().parent.parent / "runs" / "sandbox"
NOTES_FILE = SANDBOX / "notes.txt"

_REGISTRY: dict[str, Callable[..., object]] = {}


def tool(name: str):
    def register(fn: Callable[..., object]):
        _REGISTRY[name] = fn
        return fn

    return register


def run(chain, name: str, summary: str = "", **kwargs) -> dict:
    """Propose -> check -> receipt -> (only if allowed) execute.

    The checker rules on the summary AND the payload (the tool's arguments). The
    receipt proves what was checked without storing it: a sha256 of the normalized
    payload and its length — never the raw text, which could hold a secret."""
    action = {"type": "tool", "tool": name, "summary": summary or name}
    verdict = checker.evaluate({**action, "args": kwargs})
    payload = "\n".join(checker.normalize(t) for t in checker.payload_strings(kwargs))
    receipt = chain.append({**action, "payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                            "payload_len": len(payload), "payload_fields": sorted(kwargs),
                            "verdict": verdict})

    result: object = None
    executed = False
    if verdict["verdict"] == checker.ALLOW:
        fn = _REGISTRY.get(name)
        if fn is not None:
            result = fn(**kwargs)
            executed = True
    return {"receipt": receipt, "verdict": verdict, "executed": executed, "result": result}


@tool("echo")
def _echo(text: str = "", **_) -> str:
    """Repeat a short message back to the owner."""
    return text


@tool("note")
def _note(text: str = "", **_) -> str:
    """Save a short note to the owner's notes file (sandboxed, on-machine, reversible)."""
    SANDBOX.mkdir(parents=True, exist_ok=True)
    with NOTES_FILE.open("a", encoding="utf-8") as f:
        f.write(text.strip() + "\n")
    return f"noted: {text.strip()}"
