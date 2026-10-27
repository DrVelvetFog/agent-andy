"""Voice-OUT engine: ElevenLabs text-to-speech, called the way the rest of Andy
calls its models — the public REST API over stdlib ``urllib``, no SDK, no deps.

Meta has no text-to-speech endpoint, so Andy's VOICE is the one part of the loop
that is not a Meta model and does not run on this laptop. That is stated plainly,
not hidden: a spoken reply is RENDERED by ElevenLabs from text Andy already
decided and receipted, and the receipt records exactly that (``tts_engine``,
model, voice, a hash of the audio, ``rendered: "external"``). The reasoning, the
checker, the receipts and the verifier stay local; only the finished words are
read aloud by an outside service.

Best-effort by design: if the key is missing or the call fails, ``synthesize``
returns an error and the caller falls back to text — Andy never fakes a voice.

The key lives in ``.env.local`` (gitignored) and is read from the environment;
it is never printed and never written into code.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://api.elevenlabs.io/v1"

# eleven_v4 = the newest, highest-quality model (emotional range) — quality over
# latency, which is what a demo voice wants. v4 takes only stability +
# similarity_boost (no style/speed), which is all we set.
DEFAULT_MODEL = "eleven_v4"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"

# A few natural pre-made voices (ids are public/stable). Default = George.
VOICES = {
    "George": "JBFqnCBsd6RMkjVDRZzb",     # male, narrative
    "Daniel": "onwK4e9ZLuTAKqWW03F9",     # male, authoritative
    "Charlotte": "XB0fDUnXU5powFXDhCwa",  # female, conversational
    "Sarah": "EXAVITQu4vr4xnSDxMaL",      # female, soft
}
DEFAULT_VOICE_ID = VOICES["George"]

VOICE_OUT_DIR = ROOT / "runs" / "voice-out"


def _load_key() -> str | None:
    """ELEVENLABS_API_KEY from the environment, or from .env.local as a fallback
    (so `python3 scripts/...` works without a manual export). Never printed."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key
    envf = ROOT / ".env.local"
    if envf.exists():
        try:
            for line in envf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                name, _, val = line.partition("=")
                if name.strip() == "ELEVENLABS_API_KEY":
                    return val.strip().strip('"').strip("'") or None
        except OSError:
            return None
    return None


def available() -> bool:
    """True if a key is reachable — the caller uses this to pick voice vs text."""
    return _load_key() is not None


def synthesize(text: str, voice_id: str = DEFAULT_VOICE_ID, model_id: str = DEFAULT_MODEL,
               out_path: str | Path | None = None, output_format: str = DEFAULT_OUTPUT_FORMAT,
               timeout: float = 120.0) -> dict:
    """Render `text` to speech and write the audio. Returns a result dict with the
    provenance that lands in the receipt. Never raises — failures come back as
    {"ok": False, "error": ...} so the caller can fall back to text."""
    key = _load_key()
    if not key:
        return {"ok": False, "tts_engine": None, "error": "ELEVENLABS_API_KEY not set"}
    if not text or not text.strip():
        return {"ok": False, "tts_engine": None, "error": "empty text"}

    url = f"{BASE_URL}/text-to-speech/{voice_id}?output_format={output_format}"
    body = json.dumps({
        "text": text,
        "model_id": model_id,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            audio = resp.read()
            char_count = resp.headers.get("x-character-count")
            request_id = resp.headers.get("request-id")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        return {"ok": False, "tts_engine": None, "error": f"HTTP {e.code}: {detail or e.reason}"}
    except (urllib.error.URLError, TimeoutError) as e:
        return {"ok": False, "tts_engine": None, "error": f"{type(e).__name__}: {e}"}

    if out_path is None:
        VOICE_OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        out_path = VOICE_OUT_DIR / f"andy-{stamp}-{hashlib.sha256(audio).hexdigest()[:8]}.mp3"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio)

    rel = out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path
    return {
        "ok": True,
        "tts_engine": "elevenlabs",
        "rendered": "external",          # honest: audio is rendered off this machine
        "model_id": model_id,
        "voice_id": voice_id,
        "audio_path": str(rel),
        "audio_sha256": hashlib.sha256(audio).hexdigest(),
        "bytes": len(audio),
        "char_count": int(char_count) if char_count and char_count.isdigit() else None,
        "request_id": request_id,
    }
