"""Voice layer: the spoken entry point to Andy.

Voice-IN is Muse Voice Transcribe (`muse-voice-transcribe-1.0`), a realtime
WebSocket STT on the Meta Model API. A transcript — whether from that live
socket or injected for a test — enters here, is receipted with its SOURCE
(`live-transcribe` vs `transcript-injected`, never blurred), and is routed to
the SAME gated paths a typed request uses: detect (Form 2), witness, or the
Spark gated loop. Voice gets no shortcut past the checker: the action a spoken
request produces is allowed / staged / blocked and receipted exactly like a
typed one.

Voice-OUT: Meta has no text-to-speech endpoint, so the voice is the one part of
the loop that is not a Meta model and does not run on this laptop — Andy's words
are RENDERED by ElevenLabs (`agent/tts.py`) from text it already decided and
receipted. That is stated, not hidden: a `voice_output` receipt records the
engine, model, voice, a hash of the audio, and `rendered: "external"`, so the
chain shows exactly where the voice came from. Output is text AND voice together
by default; if the key is missing or the call fails, Andy falls back to text and
never fakes a voice. A spoken reply obeys the locked daemon speech rule: only
during an active task, above the checker bar, one dismissal silences the
session, never about people, text fields, or off-task content.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import uuid
from pathlib import Path

from . import detect, loop, tts, witness

LIVE = "live-transcribe"
INJECTED = "transcript-injected"
TRANSCRIBE_MODEL = "muse-voice-transcribe-1.0"
BASE_URL = "https://api.meta.ai/v1"


def transcribe_file(wav_path: str, mode: str = "PUSH_TO_TALK", timeout: float = 180.0) -> dict:
    """Real voice-in: POST a recording to Muse Voice Transcribe's file endpoint
    (/v1/asr/transcribe) and return its transcript. The audio must be a RIFF/WAVE
    container, mono, 16-bit PCM at 16 or 24 kHz. Stdlib multipart, no deps."""
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set")
    audio = Path(wav_path).read_bytes()
    boundary = "----andy" + uuid.uuid4().hex
    req_json = json.dumps({"mode": mode, "model": TRANSCRIBE_MODEL, "audioEncoding": "WAV"})
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\n'
        f'Content-Type: application/json\r\n\r\n{req_json}\r\n'.encode("utf-8"),
        f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; '
        f'filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode("utf-8"),
        audio,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ])
    req = urllib.request.Request(
        f"{BASE_URL}/asr/transcribe",
        data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {"transcript": (data.get("transcript") or "").strip(),
            "duration_ms": data.get("audioDurationMs"), "raw": data}

_WITNESS_DIR = Path(__file__).resolve().parent.parent / "runs" / "witness"

# "can I detect at <place>?" and friends -> ("detect", place)
_DETECT_RE = re.compile(
    r"(?:can|could|may|am)\s+i\s+(?:legally\s+)?(?:metal[-\s]?)?detect(?:ing)?\b.*?\b(?:at|in|on|near)\s+(.+)",
    re.IGNORECASE,
)
# packing-list intent -> ("witness", None)
_WITNESS_RE = re.compile(r"\b(witness|packing list|packing-list|pack(?:ed)?\s+(?:my|the)\s+box)\b", re.IGNORECASE)


def route(transcript: str) -> tuple[str, str | None]:
    """Deterministic intent routing for the two known commands; everything else
    falls through to the Spark gated loop."""
    t = transcript.strip()
    m = _DETECT_RE.search(t)
    if m:
        return "detect", m.group(1).strip().rstrip("?.! ")
    if _WITNESS_RE.search(t):
        return "witness", None
    return "general", t


def speak(text: str, chain=None, voice: str | bool = "auto", play: bool = False,
          voice_id: str | None = None, model_id: str | None = None) -> dict:
    """Voice-OUT: show the text AND render it to speech with ElevenLabs. Text is
    always returned; the voice is best-effort — if the key is missing or the call
    fails, Andy falls back to text and says so, never faking a voice. When a chain
    is given, a `voice_output` receipt records the engine and a hash of the audio,
    so the spoken reply carries its own provenance. `voice="auto"` voices only when
    a key is reachable; `play=True` also plays it aloud (off in tests)."""
    want_voice = tts.available() if voice == "auto" else bool(voice)
    result = {"text": text, "tts_engine": None, "voiced": False, "spoken_aloud": False}

    if want_voice:
        synth = tts.synthesize(text, voice_id=voice_id or tts.DEFAULT_VOICE_ID,
                               model_id=model_id or tts.DEFAULT_MODEL)
        if synth.get("ok"):
            result.update({
                "tts_engine": "elevenlabs", "voiced": True,
                "audio_path": synth["audio_path"], "audio_sha256": synth["audio_sha256"],
                "voice_id": synth["voice_id"], "model_id": synth["model_id"],
                "char_count": synth.get("char_count"),
            })
            if play:
                result["spoken_aloud"] = _play(synth["audio_path"])
        else:
            result["tts_error"] = synth.get("error")

    if chain is not None:
        chain.append({
            "type": "voice_output",
            "summary": f"spoke: {text[:70]}",
            "text": text,
            "tts_engine": result["tts_engine"],
            "tts_model": result.get("model_id"),
            "voice_id": result.get("voice_id"),
            "audio_sha256": result.get("audio_sha256"),
            "audio_path": result.get("audio_path"),
            "char_count": result.get("char_count"),
            "rendered": "external" if result["tts_engine"] else None,
            "voiced": result["voiced"],
            "spoken_aloud": result["spoken_aloud"],
            "reason": (result.get("tts_error")
                       or ("rendered by ElevenLabs from text Andy already decided and receipted"
                           if result["voiced"] else "text only — no voice engine reachable")),
        })
    return result


def _play(rel_path: str) -> bool:
    """Play a rendered clip aloud via macOS `afplay`. Local playback only; returns
    False (never raises) if it isn't available, so a missing player can't break a run."""
    import shutil
    import subprocess
    player = shutil.which("afplay")
    if not player:
        return False
    path = rel_path if Path(rel_path).is_absolute() else str(Path(__file__).resolve().parent.parent / rel_path)
    try:
        subprocess.run([player, path], check=True, timeout=120)
        return True
    except Exception:
        return False


def _default_photos() -> list[tuple[str, str, str]]:
    """The packing set, cable first, from the local Razr pull (gitignored)."""
    return [
        ("cable", "cable", str(_WITNESS_DIR / "cable.jpg")),
        ("book", "book", str(_WITNESS_DIR / "book.jpg")),
        ("charger", "charger", str(_WITNESS_DIR / "charger.jpg")),
    ]


def _detect_reply(o: dict) -> str:
    if o["decision"] in (detect.ANSWERED, detect.ANSWERED_WITH_CAVEAT):
        parts = [f"At {o['place']}: {o['rule_verdict']}."]
        if o.get("conditions"):
            parts.append(o["conditions"])
        src = (o.get("citation") or {}).get("source")
        if src:
            parts.append(f"Source: {src}.")
        if o.get("caveat"):
            parts.append(f"Caveat: {o['caveat']}")
        return " ".join(parts)
    return f"I'm staging that one as unverified — {o['staging_reason']}"


def handle(chain, transcript: str, source: str, photos=None, strict: bool = False,
           voice: str | bool = "auto", daemon=None) -> dict:
    """Route one transcript (live or injected) through the gated paths. The
    transcript's source is receipted so a reader can tell a real transcription
    from an injected one. `voice` is passed to speak() — pass voice=False in
    offline tests so routing/gating runs without calling the TTS API. `daemon`,
    when given, is a Daemon that may surface ONE suggestion after a task that
    staged something; it is None by default, so without one the loop is unchanged."""
    if daemon is not None:
        daemon.new_task()
    chain.append({
        "type": "voice_input",
        "summary": f"heard ({source}): {transcript[:80]}",
        "transcript": transcript,
        "source": source,
        "transcribe_model": TRANSCRIBE_MODEL if source == LIVE else None,
    })

    intent, arg = route(transcript)
    if intent == "detect":
        res = detect.answer(chain, arg, strict=strict)
        reply = speak(_detect_reply(res["outcome"]), chain, voice=voice)
        result = {"intent": "detect", "source": source, "place": arg,
                  "result": res, "reply": reply}
        if daemon is not None:   # one staged-receipt suggestion, at most, this task
            result["daemon"] = daemon.observe(chain, res, voice_mode=voice)
        return result
    if intent == "witness":
        items = photos or _default_photos()
        results = [witness.observe_and_verify(chain, it, cc, p) for it, cc, p in items]
        fin = witness.finalize(chain, results)
        reply = ("Box ready to ship." if fin["ready_to_ship"]
                 else f"Not shipped — unverified: {', '.join(fin['unverified_items'])}.")
        return {"intent": "witness", "source": source, "result": fin, "reply": speak(reply, chain, voice=voice)}

    outcomes = loop.run_turn(chain, transcript)  # the existing Spark plan + gated loop
    return {"intent": "general", "source": source, "result": outcomes,
            "reply": speak("Done.", chain, voice=voice)}
