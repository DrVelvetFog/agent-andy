"""Run every acceptance suite as a unittest, so `python3 -m unittest discover tests` works.

Each scripts/*_acceptance.py (plus scripts/voice_live_run.py) runs as its own
subprocess, one after another (the suites bind fixed ports), with MODEL_API_KEY
and ELEVENLABS_API_KEY unset and the network forced to a dead proxy.

Exit 0 is a pass. A suite that cannot run here is a SKIP that says why, never a
silent pass: gated_loop's PASS-BY-FALLBACK (exit 3), injection's L3 control
with no witness photos or key, voice_live_run with no clips, and macapp with no
built .app. In a checkout that has the Witness photos or voice clips, the
suites that would use them need MODEL_API_KEY, which this run unsets, so those
skip too (voice_acceptance's Witness path, voice_live_run). Each skip is
matched on the suite's own output, so any other non-zero exit is a FAIL.

Warning: macapp_acceptance kills any running viewer (pkill -f andy_viewer.py).
Never run this while the viewer is up.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SUITES = sorted(SCRIPTS.glob("*_acceptance.py")) + [SCRIPTS / "voice_live_run.py"]
TIMEOUT = 600

DEAD_PROXY = "http://127.0.0.1:9"
LOCAL = "127.0.0.1,localhost"


def _env() -> dict:
    env = dict(os.environ)
    env.pop("MODEL_API_KEY", None)
    env.pop("ELEVENLABS_API_KEY", None)
    env.update(HTTPS_PROXY=DEAD_PROXY, HTTP_PROXY=DEAD_PROXY, https_proxy=DEAD_PROXY,
               http_proxy=DEAD_PROXY, NO_PROXY=LOCAL, no_proxy=LOCAL,
               ANDY_APP_NONINTERACTIVE="1")
    return env


def _injection_only_l3(out: str) -> bool:
    # Every attack failed closed, the chain verified, and the ONLY failing line is L3.
    m = re.search(r"attacks fail-closed: (\d+)/(\d+)", out)
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("[FAIL]")]
    return (bool(m) and m[1] == m[2] and "receipts verified" in out
            and fails == ["[FAIL] L3 Witness ships on real photos"])


def _voice_only_witness(out: str) -> bool:
    # Photos are present, so path c called SAM with no key; it is the ONLY failing check.
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("[FAIL]")]
    return fails == ["[FAIL] c) witness ran 3 observations and shipped"]


# suite stem -> [(exit code, does the output match, skip reason), ...]
SKIPS = {
    "gated_loop_acceptance": [(
        3, lambda out: "PASS-BY-FALLBACK" in out,
        "PASS-BY-FALLBACK: Spark not called (no MODEL_API_KEY); gate, receipts and verifier passed")],
    "injection_acceptance": [(
        1, _injection_only_l3,
        "L3 needs real photos in runs/witness/ and MODEL_API_KEY (unset here); "
        "every attack failed closed and the other controls passed")],
    "voice_acceptance": [(
        1, _voice_only_witness,
        "photos are in runs/witness/, so the Witness path calls SAM, which needs MODEL_API_KEY "
        "(unset here); every other voice check passed")],
    "voice_live_run": [(
        1, lambda out: "VOICE LIVE RUN: FAIL (no clips)" in out,
        "no voice clips in runs/voice/ (and it needs MODEL_API_KEY); nothing was transcribed"), (
        1, lambda out: "MODEL_API_KEY is not set" in out,
        "clips are in runs/voice/, but transcribing them needs MODEL_API_KEY (unset here)")],
    "macapp_acceptance": [(
        1, lambda out: "FAIL (.app not built)" in out,
        "AgentAndy.app not built; run `bash scripts/build_mac_app.sh` first")],
}


class AcceptanceSuites(unittest.TestCase):
    pass


def _make_test(script: Path):
    def test(self):
        proc = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=_env(),
                              capture_output=True, text=True, timeout=TIMEOUT)
        out = proc.stdout + proc.stderr
        if proc.returncode == 0:
            return
        for code, matches, reason in SKIPS.get(script.stem, []):
            if proc.returncode == code and matches(out):
                self.skipTest(reason)
        tail = "\n".join(out.splitlines()[-25:])
        self.fail(f"{script.name} exited {proc.returncode}\n{tail}")
    return test


for _script in SUITES:
    setattr(AcceptanceSuites, f"test_{_script.stem}", _make_test(_script))


if __name__ == "__main__":
    unittest.main()
