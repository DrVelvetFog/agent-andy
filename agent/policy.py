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

# ---- Seeded memory: CITATION ONLY, never a gate ----
#
# Standing policy in the owner's own words, CITED when the deterministic checker
# already blocks or stages a request — so a refusal reads "because the owner said
# so, and here is the receipt," not as a model opinion. A seeded line never allows,
# blocks, or stages anything: policy.toml is canonical and WINS every conflict.
#
# The ACTIVE list stays EMPTY until the owner approves lines one by one (the drafts
# live in docs/seeded-memory-draft.md, which Andy never loads). Each active line is
# {category, text, source, asserts}: `category` maps (below, explicitly) to the
# checker rule-ids it may be cited for; `asserts` is "refuse" for a real standing
# refusal, and a line that "allow"s something policy blocks is reported as a
# conflict and NOT cited.
SEEDED_FACTS: list[dict] = []

# The ONLY mapping from a seeded category to the checker rule-ids it may cite for —
# explicit, in code, never inferred. A line is cited only on a block/stage whose
# rule is in its category's set.
CITE_CATEGORIES: dict[str, set] = {
    "no-exfiltration": {"exfiltration"},
    "no-unapproved-financial": {"financial"},
    "no-destructive-without-approval": {"destructive"},
    "no-secret-fields": {"secret-fields"},
    "stay-on-task": {"off-task"},
    "no-system-commands": {"system-command"},
    "no-comment-on-people": {"about-people"},
}


def cite_for(verdict: dict, seeded: list | None = None) -> dict:
    """Deterministic citation lookup for a checker verdict. Returns
    {cited, source, conflict}. A seeded line is cited ONLY when the verdict is a
    block/stage, its category maps to the verdict's rule, and it ASSERTS a refusal.
    A line that would allow what policy blocks/stages is a CONFLICT: policy.toml
    wins, the line is NOT cited, and the conflict is reported. No match -> nothing
    cited, and the reply is exactly as it was without seeded memory."""
    out = {"cited": None, "source": None, "conflict": None}
    tier = (verdict or {}).get("verdict")
    rule = (verdict or {}).get("rule")
    if tier not in ("block", "stage"):
        return out
    for line in (SEEDED_FACTS if seeded is None else seeded):
        if not isinstance(line, dict):
            continue
        if rule in CITE_CATEGORIES.get(line.get("category"), set()):
            if line.get("asserts", "refuse") == "refuse":
                out["cited"] = line.get("text")
                out["source"] = line.get("source")
            else:  # the line would allow what policy blocks/stages — policy wins
                out["conflict"] = (f"a standing-policy note would allow this, but policy.toml "
                                   f"rule '{rule}' {tier}s it — policy wins, note not cited")
            return out
    return out
