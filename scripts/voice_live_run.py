#!/usr/bin/env python3
"""Voice LIVE run — real muse-voice-transcribe-1.0 on recorded audio.

Transcribes three recorded WAV clips with Muse Voice Transcribe's file endpoint,
then routes each REAL transcript through the gated voice entry point. Unlike
scripts/voice_acceptance.py (labeled transcript INJECTION), this is genuine
voice-in: the transcript comes from the model, and every receipt is stamped
source=live-transcribe with the model name.

Needs MODEL_API_KEY and the clips in runs/voice/ (mono 16-bit PCM WAV at 16 kHz).
The witness path also runs SAM on the Razr photos in runs/witness/. With no clips
at all nothing is transcribed, so the run FAILS saying so — it never passes empty.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import detect, voice  # noqa: E402
from receipts import ReceiptChain, verify_chain  # noqa: E402

RUNS = ROOT / "runs"
CHAIN = RUNS / "voice-live-receipts.jsonl"
VOICE = RUNS / "voice"
CLIPS = ["myrtle.wav", "tybee.wav", "witness.wav"]


def main() -> int:
    RUNS.mkdir(exist_ok=True)
    CHAIN.unlink(missing_ok=True)
    chain = ReceiptChain(CHAIN)
    print(f"VOICE-IN: LIVE transcription via {voice.TRANSCRIBE_MODEL} (file endpoint)\n")

    ran = 0
    for clip in CLIPS:
        path = VOICE / clip
        if not path.exists():
            print(f"  [skip] {clip} missing — convert it into runs/voice/ first\n")
            continue
        ran += 1
        tr = voice.transcribe_file(str(path))
        transcript = tr["transcript"]
        res = voice.handle(chain, transcript, voice.LIVE, voice=True)
        if res["intent"] == "detect":
            outcome = f"{res['result']['decision']}"
        elif res["intent"] == "witness":
            outcome = "READY TO SHIP" if res["result"]["ready_to_ship"] else "NOT shipped"
        else:
            outcome = "general"
        print(f'  {clip:12} heard: "{transcript}"')
        print(f'     -> {outcome}: {res["reply"]["text"]}\n')

    if ran == 0:
        print(f"  [FAIL] no voice clips found in {VOICE.relative_to(ROOT)}/ (expected {', '.join(CLIPS)}) "
              "— nothing was transcribed or routed, so no voice-in check ran.")
        print("\nVOICE LIVE RUN: FAIL (no clips)")
        return 1
    print(f"  clips run: {ran} of {len(CLIPS)}")

    receipts = chain.receipts()
    vin = [r for r in receipts if r["action"].get("type") == "voice_input"]
    ok, reason = verify_chain(CHAIN)
    checks = {
        "every voice_input stamped live-transcribe": all(r["action"]["source"] == voice.LIVE for r in vin),
        "every voice_input names the transcribe model": all(
            r["action"].get("transcribe_model") == voice.TRANSCRIBE_MODEL for r in vin
        ),
        "chain verifies end to end": ok,
    }
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    print(f"\n{len(receipts)} receipts ({reason})")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
