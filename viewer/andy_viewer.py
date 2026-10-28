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

from receipts import ReceiptChain, verify_chain  # noqa: E402  (after sys.path insert)
from agent import voice  # noqa: E402  — the real gated chat path (typed + spoken share it)

# The daemon slot renders real suggestions ONLY if a daemon module exists in this
# checkout. If it does not, the slot stays hidden and silent — never faked.
try:
    from agent.daemon import Daemon  # noqa: E402
    _DAEMON_AVAILABLE = True
except Exception:
    Daemon = None  # type: ignore
    _DAEMON_AVAILABLE = False

RUNS = ROOT / "runs"
PAGE = Path(__file__).resolve().parent / "index.html"

# Live chat session state (one per server process). The chain is a REAL chain
# under runs/, so every receipt the page shows is a read of a real receipt.
CHAT: dict = {"chain_name": "chat-live.jsonl", "chain": None, "daemon": None}


def init_chat(chain_name: str = "chat-live.jsonl", reset: bool = True) -> None:
    """Start (or reset) the live chat chain and its daemon for this process."""
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / chain_name
    if reset:
        path.unlink(missing_ok=True)
    chain = ReceiptChain(path)
    if not chain.receipts():
        chain.append({"type": "session_start",
                      "summary": "chat session started — typed and voice both go through the checker"})
    CHAT.update({"chain_name": chain_name, "chain": chain,
                 "daemon": Daemon() if _DAEMON_AVAILABLE else None})


def chat_message(message: str, voice_mode="auto", run_general: bool = True) -> dict:
    """Run one typed message through the real gate and return the reply, the live
    chain, and the verifier's verdict — exactly what the page renders."""
    if CHAT["chain"] is None:
        init_chat()
    if not message or not message.strip():
        return {"error": "empty message"}
    chain = CHAT["chain"]
    res = voice.chat_turn(chain, message, daemon=CHAT["daemon"],
                          voice=voice_mode, run_general=run_general)
    reply = res["reply"]
    d = res.get("daemon")
    daemon_out = ({"text": d["text"], "about": d.get("about"),
                   "verdict": d["verdict"]["verdict"]}
                  if d and d.get("spoke") else None)
    ok, reason = verify_chain(chain.path)
    return {
        "intent": res.get("intent"),
        "reply_text": res["reply_text"],
        "source": res["source"],                 # "typed" — never a transcription
        "audio_path": reply.get("audio_path"),    # the browser plays it, if voiced
        "tts_engine": reply.get("tts_engine"),
        "daemon": daemon_out,                     # only present if the daemon really spoke
        "daemon_available": _DAEMON_AVAILABLE,
        "chain_name": CHAT["chain_name"],
        "receipts": chain.receipts(),
        "verify": {"ok": ok, "reason": reason},
    }


def daemon_dismiss() -> dict:
    """Dismiss the daemon for the rest of the session. Visible + receipted."""
    if CHAT["chain"] is None:
        init_chat()
    chain = CHAT["chain"]
    if CHAT["daemon"] is None:
        return {"dismissed": False, "reason": "no daemon module in this checkout",
                "chain_name": CHAT["chain_name"], "receipts": chain.receipts()}
    CHAT["daemon"].dismiss(chain)
    ok, reason = verify_chain(chain.path)
    return {"dismissed": True, "chain_name": CHAT["chain_name"],
            "receipts": chain.receipts(), "verify": {"ok": ok, "reason": reason}}


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
        elif u.path == "/audio":
            self._serve_audio((q.get("path") or [""])[0])
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802 (stdlib naming)
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            body = {}
        if u.path == "/api/chat":
            self._json(chat_message(str(body.get("message", "")),
                                    body.get("voice", "auto"),
                                    bool(body.get("run_general", True))))
        elif u.path == "/api/daemon-dismiss":
            self._json(daemon_dismiss())
        else:
            self._json({"error": "not found"}, 404)

    def _serve_audio(self, rel: str) -> None:
        """Serve a rendered voice clip — only files under runs/, mp3 only."""
        if not rel:
            self._json({"error": "no path"}, 400)
            return
        p = (ROOT / rel).resolve()
        try:
            p.relative_to(RUNS.resolve())
        except ValueError:
            self._json({"error": "forbidden"}, 403)
            return
        if not p.exists() or p.suffix != ".mp3":
            self._json({"error": "not found"}, 404)
            return
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args) -> None:  # quiet; this is a demo window
        pass


def build_server(port: int, chat_chain: str = "chat-live.jsonl",
                 reset: bool = True) -> ThreadingHTTPServer:
    """Create the viewer+chat server, binding 127.0.0.1 only, with a fresh chat
    session. Shared by main() and the acceptance test."""
    init_chat(chat_chain, reset=reset)
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent Andy viewer + chat")
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()
    server = build_server(args.port)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Agent Andy on {url}  (Ctrl-C to stop)")
    print(f"  daemon module: {'present' if _DAEMON_AVAILABLE else 'absent (slot stays hidden)'}")
    print("  TYPED-CHAT FALLBACK: if voice or the Meta Model API is down, just type —")
    print("  typed input runs through the exact same checker and receipts as voice.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
