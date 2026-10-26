"""Brain: Muse Spark via the Meta Model API.

Calls POST {base}/responses with model muse-spark-1.3, non-streaming, reasoning
effort LOW (the default is high and burns output tokens on reasoning we do not
need for planning). Standard library only — zero dependencies. The key comes
from MODEL_API_KEY and is never logged or receipted; receipts record what was
done, never credentials.

`ask` is a raw text call. `propose_plan` is the actor's job in the loop: turn
one owner utterance into a short JSON plan of tool steps. The brain only
PROPOSES — every step it returns still has to clear the checker before it runs.
"""

from __future__ import annotations

import json
import os
import urllib.request

BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"

# The only tools the planner may name. The gate would stop anything else, but
# telling the actor the real menu keeps plans honest and cheap.
TOOLS = {
    "echo": "echo(text): repeat a short message back to the owner.",
    "note": "note(text): save a short note to the owner's local notes file.",
}

_PLANNER_SYSTEM = (
    "You are the planner for Andy, a personal computer agent. Turn the owner's "
    "request into a SHORT plan of concrete tool steps (1-3 steps). "
    "Available tools:\n" + "\n".join(f"  - {d}" for d in TOOLS.values()) + "\n"
    "Respond with ONLY a JSON array. Each element: "
    '{"tool":"<one of: ' + ", ".join(TOOLS) + '>",'
    '"summary":"<short imperative description of this step>",'
    '"args":{"text":"<the text for the tool>"}}. '
    "No prose, no markdown fences — just the JSON array."
)


def _post_responses(input_payload, timeout: float) -> dict:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set")
    body = {
        "model": MODEL,
        "input": input_payload,
        "reasoning": {"effort": "low"},
    }
    req = urllib.request.Request(
        f"{BASE_URL}/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _output_text(data: dict) -> str:
    texts: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "output_text" and isinstance(node.get("text"), str):
                texts.append(node["text"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data.get("output", data))
    return "".join(texts)


def ask(prompt: str, timeout: float = 60.0) -> str:
    """Raw text completion from Spark."""
    data = _post_responses(prompt, timeout)
    return _output_text(data)


def _message(role: str, text: str) -> dict:
    return {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}


def _coerce_plan(raw: str, utterance: str) -> list[dict]:
    """Parse the planner's JSON; keep only well-formed, known-tool steps."""
    text = raw.strip()
    if text.startswith("```"):  # strip a stray code fence, just in case
        text = text.strip("`")
        text = text[text.find("[") : text.rfind("]") + 1] if "[" in text else text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = []
    steps: list[dict] = []
    if isinstance(parsed, list):
        for step in parsed:
            if not isinstance(step, dict):
                continue
            tool = str(step.get("tool", "")).strip()
            if tool not in TOOLS:
                continue
            args = step.get("args") if isinstance(step.get("args"), dict) else {}
            steps.append(
                {
                    "tool": tool,
                    "summary": str(step.get("summary", tool)).strip()[:160] or tool,
                    "args": {"text": str(args.get("text", "")).strip()},
                }
            )
    if not steps:  # never let a turn produce nothing to gate
        steps = [{"tool": "echo", "summary": f"echo the request: {utterance[:80]}",
                  "args": {"text": utterance}}]
    return steps[:3]


def propose_plan(utterance: str, timeout: float = 60.0) -> list[dict]:
    """Ask Spark for a plan. Falls back to a single echo step on any failure,
    so the gated loop always has something to rule on and receipt."""
    try:
        data = _post_responses(
            [_message("system", _PLANNER_SYSTEM), _message("user", utterance)],
            timeout,
        )
        return _coerce_plan(_output_text(data), utterance)
    except Exception:
        return [{"tool": "echo", "summary": f"echo the request: {utterance[:80]}",
                 "args": {"text": utterance}}]
