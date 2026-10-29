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

Stdlib only. The viewer binds 127.0.0.1 only and takes no outside connections,
but Andy's brain, eyes, voice-in, and voice-out services send data to Meta and
ElevenLabs, as disclosed in the README.

    python3 viewer/andy_viewer.py          # then open http://127.0.0.1:8799
    python3 viewer/andy_viewer.py --port 9000
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from receipts import ReceiptChain, verify_chain  # noqa: E402  (after sys.path insert)
from agent import voice  # noqa: E402  — the real gated chat path (typed + spoken share it)
from agent.verify_source import KnowledgeStore  # noqa: E402  — verify-on-demand session memory

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
CHAT: dict = {"chain_name": "chat-live.jsonl", "chain": None, "daemon": None, "store": None}


def _rotate(path: Path) -> Path | None:
    """Move a non-empty chain aside to a timestamped archive in the same directory
    (chat-live-YYYYMMDD-HHMMSS.jsonl, UTC, then -1, -2, … if taken) and return it.
    The bytes are untouched, so the archive still verifies, and it stays listable
    like any other chain. Never overwrites an archive. A missing or empty file is
    left alone and returns None."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    dest, n = path.with_name(f"{path.stem}-{stamp}{path.suffix}"), 0
    while dest.exists():
        n += 1
        dest = path.with_name(f"{path.stem}-{stamp}-{n}{path.suffix}")
    path.rename(dest)
    return dest


def init_chat(chain_name: str = "chat-live.jsonl", reset: bool = True, persist_path=None) -> None:
    """Start (or reset) the live chat chain and its daemon for this process. The
    KnowledgeStore loads any earned answers from persist_path (the real
    data/confirmed_secondary.json by default; tests pass a temp path). A reset
    ROTATES the previous chain to a timestamped archive — receipts are evidence,
    so a restart never deletes them."""
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / chain_name
    if reset:
        _rotate(path)
    chain = ReceiptChain(path)
    if not chain.receipts():
        chain.append({"type": "session_start",
                      "summary": "chat session started — typed and voice both go through the checker"})
    CHAT.update({"chain_name": chain_name, "chain": chain,
                 "daemon": Daemon() if _DAEMON_AVAILABLE else None,
                 "store": KnowledgeStore(persist_path=persist_path)})


def chat_message(message: str, voice_mode="auto", run_general: bool = True,
                 demo: bool = False, source: str = voice.TYPED) -> dict:
    """Run one message through the real gate and return the reply, the live
    chain, and the verifier's verdict — exactly what the page renders. `demo` is the
    "Try to break it" mode: same checker and receipts, no model spend. `source` is
    "typed" for the chat box, "live-transcribe" for the mic."""
    if CHAT["chain"] is None:
        init_chat()
    if not message or not message.strip():
        return {"error": "empty message"}
    chain = CHAT["chain"]
    res = voice.chat_turn(chain, message, daemon=CHAT["daemon"], store=CHAT["store"],
                          voice=voice_mode, run_general=run_general, demo=demo, source=source)
    reply = res["reply"]
    d = res.get("daemon")
    daemon_out = ({"text": d["text"], "about": d.get("about"),
                   "verdict": d["verdict"]["verdict"]}
                  if d and d.get("spoke") else None)
    ok, reason = verify_chain(chain.path)
    return {
        "intent": res.get("intent"),
        "reply_text": res["reply_text"],
        "source": res["source"],                 # "typed" or "live-transcribe", never blurred
        "audio_path": reply.get("audio_path"),    # the browser plays it, if voiced
        "tts_engine": reply.get("tts_engine"),
        "daemon": daemon_out,                     # only present if the daemon really spoke
        "daemon_available": _DAEMON_AVAILABLE,
        "pending": CHAT["store"].pending_list(),  # verify proposals awaiting an Approve/Decline
        "chain_name": CHAT["chain_name"],
        "receipts": chain.receipts(),
        "verify": {"ok": ok, "reason": reason},
    }


# Mic audio limits. The page sends mono 16-bit PCM WAV at 16 kHz and stops itself at
# 60 s (about 1.9 MB); the server also accepts 24 kHz, the other rate the transcribe
# endpoint takes, and refuses anything bigger or longer.
MAX_WAV_BYTES = 10 * 1024 * 1024
MAX_WAV_SECONDS = 60.5
WAV_RATES = (16000, 24000)


def wav_problem(raw: bytes) -> tuple[int, str] | None:
    """Why this body is not a WAV the transcriber takes, as (status, reason), or
    None. Checked before anything is transcribed or run."""
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return 415, "not a RIFF/WAVE file"
    try:
        with wave.open(io.BytesIO(raw)) as w:
            ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            frames, comp = w.getnframes(), w.getcomptype()
    except (wave.Error, EOFError) as e:
        return 415, f"not a readable PCM WAV ({e})"
    if comp != "NONE":
        return 415, "WAV is compressed; PCM only"
    if ch != 1:
        return 415, f"WAV has {ch} channels; mono only"
    if width != 2:
        return 415, f"WAV is {8 * width}-bit; 16-bit PCM only"
    if rate not in WAV_RATES:
        return 415, f"WAV is {rate} Hz; 16 kHz or 24 kHz only"
    if frames == 0:
        return 415, "WAV has no audio"
    if frames / rate > MAX_WAV_SECONDS:
        return 413, f"WAV is {frames / rate:.1f} s; 60 s at most"
    return None


def voice_message(wav: bytes) -> tuple[int, dict]:
    """One spoken turn from the page's mic: transcribe the WAV with Muse Voice
    Transcribe, then run the transcript through chat_message — the SAME checker-first
    gate and intents as typed chat — receipted as voice_input, source live-transcribe.
    The WAV lives only in a temp file under runs/ (gitignored), deleted right after.
    No key, a failed call, or an empty transcript is an error and runs NO turn —
    never a fake or injected transcript."""
    tmp_dir = RUNS / "voice-in"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=tmp_dir, suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(wav)
        try:
            tr = voice.transcribe_file(tmp)
        except RuntimeError as e:            # e.g. MODEL_API_KEY is not set
            return 503, {"error": f"transcription unavailable: {e} — nothing was run"}
        except Exception as e:
            return 502, {"error": f"transcription failed ({type(e).__name__}: {str(e)[:160]}) — nothing was run"}
    finally:
        Path(tmp).unlink(missing_ok=True)
    text = (tr.get("transcript") or "").strip()
    if not text:
        return 422, {"error": "the transcript was empty — nothing was run"}
    out = chat_message(text, source=voice.LIVE)
    out["transcript"] = text
    return 200, out


def pending_list() -> dict:
    """Current verify proposals awaiting the owner's decision (for the page to
    render Approve/Decline buttons). Empty when nothing is pending."""
    if CHAT["store"] is None:
        init_chat()
    return {"pending": CHAT["store"].pending_list()}


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
        # Every GET route — the page, the chain reads, verify/tamper, pending, audio —
        # is served only to this page: a DNS-rebound name or another site gets 403
        # and no data. Same rule as POST; GETs carry no body, so no content-type check.
        if not self._local_request():
            self._json({"error": "forbidden: request not from this page (Origin/Host)"}, 403)
            return
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
        elif u.path == "/api/pending":
            self._json(pending_list())
        elif u.path == "/audio":
            self._serve_audio((q.get("path") or [""])[0])
        else:
            self._json({"error": "not found"}, 404)

    def _local_request(self) -> bool:
        """Only this page may call the server, GET or POST. If the browser sent an
        Origin, it must be this server's own (http://127.0.0.1:<port> or
        http://localhost:<port>); with no Origin, the Host header must be. Anything
        else — another site's page, or a DNS-rebound name — is refused before any
        handler runs."""
        port = self.server.server_address[1]
        origin = self.headers.get("Origin")
        if origin is not None:
            return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _voice_post(self) -> None:
        """/api/voice: the body is WAV audio, not JSON, so — like /api/daemon-dismiss —
        it is exempt from the JSON content-type rule; it keeps the Origin/Host check,
        and instead must be audio/wav, at most 10 MB, and a mono 16-bit PCM WAV at
        16 or 24 kHz. Every refusal comes before anything is transcribed or run."""
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_WAV_BYTES:
            left = min(length, 4 * MAX_WAV_BYTES)     # drain, bounded, so the client gets the 413
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
            raw = None
        else:
            raw = self.rfile.read(length) if length else b""
        if not self._local_request():
            self._json({"error": "forbidden: request not from this page (Origin/Host)"}, 403)
            return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "audio/wav":
            self._json({"error": "unsupported media type: send audio/wav"}, 415)
            return
        if raw is None:
            self._json({"error": "audio too large: 10 MB at most"}, 413)
            return
        bad = wav_problem(raw)
        if bad:
            self._json({"error": f"not accepted: {bad[1]}"}, bad[0])
            return
        status, body = voice_message(raw)
        self._json(body, status)

    def do_POST(self) -> None:  # noqa: N802 (stdlib naming)
        u = urlparse(self.path)
        if u.path == "/api/voice":
            self._voice_post()
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        # Checked before ANY handler runs: a refused POST leaves no receipt and no state.
        if u.path in ("/api/chat", "/api/daemon-dismiss") and not self._local_request():
            self._json({"error": "forbidden: request not from this page (Origin/Host)"}, 403)
            return
        if u.path == "/api/daemon-dismiss":
            self._json(daemon_dismiss())   # its body is ignored, so no JSON type is required
            return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if u.path == "/api/chat" and ctype != "application/json":
            self._json({"error": "unsupported media type: send application/json"}, 415)
            return
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            body = {}
        if u.path == "/api/chat":
            self._json(chat_message(str(body.get("message", "")),
                                    body.get("voice", "auto"),
                                    bool(body.get("run_general", True)),
                                    bool(body.get("demo", False))))
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
                 reset: bool = True, persist_path=None) -> ThreadingHTTPServer:
    """Create the viewer+chat server, binding 127.0.0.1 only, with a fresh chat
    session. Shared by main() and the acceptance tests (which pass a temp
    persist_path to avoid touching the tracked earned-answers file)."""
    init_chat(chat_chain, reset=reset, persist_path=persist_path)
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
