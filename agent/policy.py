"""Policy: what Andy may do, when he may speak, and what he never touches.

The scope rules Andy is checked against live in a readable, declarative file,
`policy.toml` — rules, risk tiers, and the reason each one gives, as data, not
hidden in code. This module loads that file; the daemon's speaking policy,
which is a separate concern, lives here as plain constants.

Fail-closed: a missing or malformed policy file raises here, and the checker
turns that into a block. A policy the engine cannot read is never a silent
allow.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

POLICY_FILE = Path(__file__).resolve().parent / "policy.toml"

_cache: dict | None = None


def rules() -> dict:
    """Load and cache the declarative policy from policy.toml.

    Raises on a missing or unparseable file; the checker catches that and fails
    closed rather than letting an unreadable policy wave actions through.
    """
    global _cache
    if _cache is None:
        with POLICY_FILE.open("rb") as f:
            _cache = tomllib.load(f)
    return _cache


# ---- Daemon speaking policy (separate from the action-scope rules above) ----

# The daemon speaks unprompted only when ALL of these hold.
SPEAK_WHEN = {
    "task_active": True,          # never ambient, only during an active checklist
    "evidence_above_checker_bar": True,
    "not_dismissed_this_session": True,
}

# One dismissal silences unprompted comments for the rest of the session.
DISMISSAL_SCOPE = "session"

# Demo memory is SEEDED, not learned: owner-approved facts only, stated
# honestly as seeded. Filled in by the owner before the demo; nothing invented.
SEEDED_FACTS: list[str] = []
