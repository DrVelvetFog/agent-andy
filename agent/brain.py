"""Brain: Muse Spark via the Meta Model API (Day 1 stub).

Calls POST {base}/responses with model muse-spark-1.3, non-streaming. Uses
only the standard library so Day 1 has zero dependencies. The key comes from
the MODEL_API_KEY environment variable and is never logged or receipted —
receipts record what was done, never credentials.
"""

from __future__ import annotations

import json
import os
import urllib.request

BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"


def ask(prompt: str, timeout: float = 60.0) -> str:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set")
    req = urllib.request.Request(
        f"{BASE_URL}/responses",
        data=json.dumps({"model": MODEL, "input": prompt}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # Collect output_text fragments from the Responses API shape.
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
