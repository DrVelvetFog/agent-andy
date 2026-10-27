"""Eyes: SAM 3.1 via the Meta Model API.

Segments a real photo for one named object (one noun phrase per call, per the
SAM recipe) and reports what it found. Stdlib only.

SAM returns its detections as tokens inside the response's output_text, e.g.
`<|box;x1=366;y1=323;x2=2802;y2=2862;w=4096;h=3072|><|mask;...|>` — one box +
mask per detected instance. There is no probability score, so `segment`
reports the detection count and how much of the frame the largest mask covers,
and the caller treats a real-sized mask as "seen" and anything smaller or
absent as unverified. A tiny stray box (an edge artifact) is filtered by size,
so a miss stays a miss. Generated images are never used here.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from pathlib import Path

BASE_URL = "https://api.meta.ai/v1"
MODEL = "sam-3.1"

_BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


def segment(image_path: str, concept: str, min_area_frac: float = 0.01, timeout: float = 120.0) -> dict:
    """Call SAM for one concept on one photo. Returns a compact summary:
    {concept, detections, raw_boxes, top_area_frac, top_score}. Raises on a
    transport/HTTP failure so the caller can fail closed."""
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set")
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    body = {
        "model": MODEL,
        "input": [{
            "type": "message", "role": "user", "content": [
                {"type": "input_text", "text": concept},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"},
            ],
        }],
    }
    req = urllib.request.Request(
        f"{BASE_URL}/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return _summarize(data, concept, min_area_frac)


def _output_text(data: dict) -> str:
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "output_text" and isinstance(node.get("text"), str):
                out.append(node["text"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data.get("output", data))
    return "".join(out)


def _summarize(data: dict, concept: str, min_area_frac: float) -> dict:
    """Parse SAM's box tokens. A detection counts only if its box covers at
    least `min_area_frac` of the frame, so a stray edge artifact is not a hit."""
    fracs: list[float] = []
    for m in _BOX_RE.finditer(_output_text(data)):
        x1, y1, x2, y2, w, h = map(int, m.groups())
        area = max(0, x2 - x1) * max(0, y2 - y1)
        fracs.append(area / max(1, w * h))
    significant = [f for f in fracs if f >= min_area_frac]
    return {
        "concept": concept,
        "detections": len(significant),
        "raw_boxes": len(fracs),
        "top_area_frac": round(max(significant), 4) if significant else (round(max(fracs), 4) if fracs else 0.0),
        "top_score": None,  # SAM returns masks, not probabilities
        "raw": data,
    }
