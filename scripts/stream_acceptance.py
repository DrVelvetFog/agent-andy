#!/usr/bin/env python3
"""Streaming-voice acceptance — a streamed reply is played as it renders AND receipted.

A local fake of the ElevenLabs /stream endpoint (no key, no network) feeds PCM in
slow chunks. Checks:
  a. speak(stream=True) returns at once with a stream id; the reply's
     voice_output receipt is written now, marked streaming, not voiced.
  b. stream_chunks() yields the PCM while it renders, byte for byte.
  c. when the render ends, a voice_stream receipt points back at the reply,
     with a WAV on disk whose sha256 matches the receipt.
  d. a failed render writes a voice_stream receipt saying so — text only.
  e. through the viewer: a typed Tybee turn returns a stream id before the
     voice is done, /api/voice-stream serves the same PCM, /audio serves the
     WAV, the daemon stays unvoiced, and the chain verifies.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "viewer"))

from agent import tts, voice  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

PCM = bytes((i * 7) % 256 for i in range(24000))   # half a second of fake 16-bit audio
CHUNKS, DELAY = 6, 0.15


class FakeElevenLabs(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        if "/fail/" in self.path:
            self.send_response(500); self.end_headers(); self.wfile.write(b"boom"); return
        self.send_response(200)
        self.send_header("Content-Type", "audio/pcm")
        self.end_headers()
        step = len(PCM) // CHUNKS
        for i in range(CHUNKS):
            self.wfile.write(PCM[i * step: (i + 1) * step if i < CHUNKS - 1 else len(PCM)])
            self.wfile.flush()
            time.sleep(DELAY)

    def log_message(self, *_a):
        pass


def _actions(chain):
    return [r["action"] for r in chain.receipts()]


def main() -> int:
    fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeElevenLabs)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp())
    os.environ["ELEVENLABS_API_KEY"] = "fake-test-key"    # sent only to the local fake
    tts.BASE_URL = f"http://127.0.0.1:{fake.server_address[1]}/v1"
    tts.VOICE_OUT_DIR = tmp / "voice-out"
    checks = {}

    # a-c: one streamed reply
    chain = ReceiptChain(tmp / "stream.jsonl")
    t0 = time.time()
    res = voice.speak("The full reply, shown on screen.", chain, voice=True,
                      spoken="The short version.", stream=True)
    returned_in = time.time() - t0
    first = _actions(chain)[-1]
    checks["a) returns at once, receipt says streaming, not voiced"] = (
        bool(res.get("stream_id")) and returned_in < DELAY and first["type"] == "voice_output"
        and first["streaming"] is True and first["voiced"] is False
        and first["text"] == "The full reply, shown on screen." and first["spoken_text"] == "The short version.")
    got = b"".join(voice.stream_chunks(res["stream_id"]))
    checks["b) stream_chunks yields the rendered PCM byte for byte"] = got == PCM
    voice.wait_stream(res["stream_id"])
    done = _actions(chain)[-1]
    wav_path = Path(done.get("audio_path") or "")
    wav_path = wav_path if wav_path.is_absolute() else ROOT / wav_path
    wav_ok = False
    if wav_path.exists():
        with wave.open(str(wav_path)) as w:
            wav_ok = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.readframes(w.getnframes())) \
                == (1, 2, tts.STREAM_RATE, PCM)
    checks["c) voice_stream receipt points back, WAV hash matches"] = (
        done["type"] == "voice_stream" and done["voiced"] is True
        and done["of_seq"] == chain.receipts()[-2]["seq"] and wav_ok
        and hashlib.sha256(wav_path.read_bytes()).hexdigest() == done["audio_sha256"]
        and verify_chain(chain.path)[0])

    # d: a failed render
    chain_f = ReceiptChain(tmp / "fail.jsonl")
    res_f = voice.speak("Reply.", chain_f, voice=True, stream=True, voice_id="fail")
    voice.wait_stream(res_f["stream_id"])
    failed = _actions(chain_f)[-1]
    checks["d) a failed render is receipted as text only"] = (
        failed["type"] == "voice_stream" and failed["voiced"] is False
        and failed["reason"].startswith("text only — voice stream failed")
        and b"".join(voice.stream_chunks(res_f["stream_id"])) == b"")

    # e: through the viewer (which serves audio only from under runs/, as in the app)
    import andy_viewer  # noqa: E402
    tts.VOICE_OUT_DIR = ROOT / "runs" / "voice-out"
    server = andy_viewer.build_server(0, chat_chain="stream-accept.jsonl", persist_path=tmp / "confirmed.json")
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    req = urllib.request.Request(base + "/api/chat", data=json.dumps({"message": "Can I detect at Tybee Island?"}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read())
    chat_in = time.time() - t0
    with urllib.request.urlopen(base + "/api/voice-stream?id=" + out["stream_id"], timeout=30) as r:
        streamed, rate = r.read(), r.headers.get("X-Sample-Rate")
    voice.wait_stream(out["stream_id"])
    acts = _actions(andy_viewer.CHAT["chain"])
    reply = next(a for a in acts if a["type"] == "voice_output" and a["kind"] == "reply")
    vs = next(a for a in acts if a["type"] == "voice_stream")
    daemon_voice = next(a for a in acts if a["type"] == "voice_output" and a["kind"] == "daemon")
    with urllib.request.urlopen(base + "/audio?path=" + urllib.request.quote(vs["audio_path"]), timeout=30) as r:
        served, ctype = r.read(), r.headers.get("Content-Type")
    checks["e) viewer: stream id before the voice ends, same PCM, WAV served, daemon unvoiced, chain verifies"] = (
        chat_in < CHUNKS * DELAY and streamed == PCM and rate == str(tts.STREAM_RATE)
        and reply["streaming"] and reply["spoken_text"] and vs["voiced"] and ctype == "audio/wav"
        and hashlib.sha256(served).hexdigest() == vs["audio_sha256"]
        and daemon_voice["voiced"] is False and verify_chain(andy_viewer.CHAT["chain"].path)[0])
    server.shutdown(); fake.shutdown()

    print(f"\nchat turn returned in {chat_in:.2f}s; the fake render takes {CHUNKS * DELAY:.2f}s\n")
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if all(checks.values()):
        print("\nSTREAM ACCEPTANCE: PASS")
        return 0
    print("\nSTREAM ACCEPTANCE: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
