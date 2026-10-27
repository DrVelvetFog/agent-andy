#!/usr/bin/env python3
"""Receipt-chain viewer — a thin local window onto the real receipts.

This is a demo window, not a new trust surface. It reads the actual JSONL
chains the acceptance scripts write under ``runs/`` and renders them as a
timeline you can watch, color-coded by the checker's verdict (allow / stage /
block). Two buttons carry the whole thesis:

* **Verify** calls the project's own ``receipts/verify.py`` — the same
  independent verifier the acceptance tests use — and shows its verdict. No
  logic is re-implemented here; the page reports what the real verifier says.
* **Flip one byte** changes a single character of one receipt in a throwaway
  COPY (the real chain on disk is never touched) and shows verification fail,
  by receipt number — the tamper-evidence, made visible.

Stdlib only, binds to 127.0.0.1 only. Nothing leaves the laptop.

    python3 viewer/andy_viewer.py          # then open http://127.0.0.1:8799
    python3 viewer/andy_viewer.py --port 9000
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from receipts import verify_chain  # noqa: E402  (after sys.path insert)

RUNS = ROOT / "runs"
PAGE = Path(__file__).resolve().parent / "index.html"


def list_chains() -> list[dict]:
    """Every *.jsonl chain in runs/, newest first, with its receipt count."""
    if not RUNS.exists():
        return []
    out = []
    for p in sorted(RUNS.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True):
        # Skip the deliberately-broken fixtures the acceptance tests leave behind
        # (*.tampered.jsonl, verifier-tamper.jsonl) — this window shows real runs.
        if "tamper" in p.name:
            continue
        try:
            count = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            continue
        out.append({"name": p.name, "count": count})
    return out


def read_chain(name: str) -> list[dict]:
    path = _safe_path(name)
    if path is None or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _safe_path(name: str) -> Path | None:
    """Resolve a chain name to a path INSIDE runs/, or None. No path traversal."""
    if not name:
        return None
    p = (RUNS / name).resolve()
    try:
        p.relative_to(RUNS.resolve())
    except ValueError:
        return None
    return p


def tamper(name: str) -> dict:
    """Flip one character of one receipt body in a throwaway copy, then verify it.

    The flip lands inside a string value (the summary where there is one), so the
    line stays valid JSON and the failure is the hash no longer recomputing — not
    a parse error. The real file is never written to.
    """
    path = _safe_path(name)
    if path is None or not path.exists():
        return {"ok": False, "reason": "no such chain", "receipt_index": -1}
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        return {"ok": False, "reason": "empty chain", "receipt_index": -1}

    # Prefer a receipt past genesis so the broken link cascades visibly.
    idx = 1 if len(lines) > 1 else 0
    line = lines[idx]
    marker = '"summary":"'
    start = line.find(marker)
    start = start + len(marker) if start >= 0 else 0
    # Find the first letter at/after start to flip to a different letter.
    j = start
    while j < len(line) and not line[j].isalpha():
        j += 1
    if j >= len(line):
        return {"ok": False, "reason": "could not find a byte to flip", "receipt_index": -1}
    before = line[j]
    after = "X" if before.lower() != "x" else "Y"
    if before.islower():
        after = after.lower()
    lines[idx] = line[:j] + after + line[j + 1:]

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
        tmp.write("\n".join(lines) + "\n")
        tmp_path = tmp.name
    try:
        ok, reason = verify_chain(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return {"ok": ok, "reason": reason, "receipt_index": idx,
            "before": before, "after": after, "field": "summary"}


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code: int = 200) -> None:
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/chains":
            self._json({"chains": list_chains()})
        elif u.path == "/api/chain":
            name = (q.get("name") or [""])[0]
            self._json({"name": name, "receipts": read_chain(name)})
        elif u.path == "/api/verify":
            name = (q.get("name") or [""])[0]
            path = _safe_path(name)
            if path is None:
                self._json({"ok": False, "reason": "no such chain"})
            else:
                ok, reason = verify_chain(path)
                self._json({"ok": ok, "reason": reason})
        elif u.path == "/api/tamper":
            self._json(tamper((q.get("name") or [""])[0]))
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *_args) -> None:  # quiet; this is a demo window
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent Andy receipt-chain viewer")
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Agent Andy viewer on {url}  (Ctrl-C to stop)")
    if not list_chains():
        print("  note: runs/ has no chains yet — run e.g. python3 scripts/day1_acceptance.py")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
