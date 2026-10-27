"""Voice layer: the spoken entry point to Andy.

Voice-IN is Muse Voice Transcribe (`muse-voice-transcribe-1.0`), a realtime
WebSocket STT on the Meta Model API. A transcript — whether from that live
socket or injected for a test — enters here, is receipted with its SOURCE
(`live-transcribe` vs `transcript-injected`, never blurred), and is routed to
the SAME gated paths a typed request uses: detect (Form 2), witness, or the
Spark gated loop. Voice gets no shortcut past the checker: the action a spoken
request produces is allowed / staged / blocked and receipted exactly like a
typed one.

Voice-OUT: Meta has no text-to-speech endpoint, so Andy's spoken reply is TEXT
today, returned through a `speak()` seam where a real engine can plug in later
without touching the loop. Nothing is installed and no TTS is faked (the engine
choice is still open). A spoken reply, when shown, obeys the locked daemon
speech rule: only during an active task, above the checker bar, one dismissal
silences the session, never about people, text fields, or off-task content.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import detect, loop, witness

LIVE = "live-transcribe"
INJECTED = "transcript-injected"
TRANSCRIBE_MODEL = "muse-voice-transcribe-1.0"

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


def speak(text: str) -> dict:
    """Voice-OUT seam. Today it returns the text to show — no TTS is called and
    none is faked. A real engine plugs in HERE later without touching the loop."""
    return {"text": text, "tts_engine": None, "spoken_aloud": False}


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


def handle(chain, transcript: str, source: str, photos=None, strict: bool = False) -> dict:
    """Route one transcript (live or injected) through the gated paths. The
    transcript's source is receipted so a reader can tell a real transcription
    from an injected one."""
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
        return {"intent": "detect", "source": source, "place": arg,
                "result": res, "reply": speak(_detect_reply(res["outcome"]))}
    if intent == "witness":
        items = photos or _default_photos()
        results = [witness.observe_and_verify(chain, it, cc, p) for it, cc, p in items]
        fin = witness.finalize(chain, results)
        reply = ("Box ready to ship." if fin["ready_to_ship"]
                 else f"Not shipped — unverified: {', '.join(fin['unverified_items'])}.")
        return {"intent": "witness", "source": source, "result": fin, "reply": speak(reply)}

    outcomes = loop.run_turn(chain, transcript)  # the existing Spark plan + gated loop
    return {"intent": "general", "source": source, "result": outcomes, "reply": speak("Done.")}
