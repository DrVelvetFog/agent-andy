"""A throwaway Andy signing key for the acceptance suites — NEVER the real key.

use_test_key() makes a fresh Ed25519 key in a temp directory (removed at exit)
and points ANDY_CHAIN_SIGNING_KEY / ANDY_CHAIN_SIGNING_PUB at it, so a suite can
sign and verify exactly as the demo does without touching ~/.ssh or
data/andy-chain-signing.pub.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def use_test_key() -> Path:
    d = Path(tempfile.mkdtemp(prefix="andy-test-key-"))
    atexit.register(shutil.rmtree, d, True)
    key = d / "andy_test_key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "andy-test-key",
                    "-f", str(key)], check=True)
    os.environ["ANDY_CHAIN_SIGNING_KEY"] = str(key)
    os.environ["ANDY_CHAIN_SIGNING_PUB"] = str(key) + ".pub"
    return key
