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
# The ACTIVE list holds the seven lines the owner approved on Oct 30, 2026, copied
# word for word from docs/seeded-memory-draft.md (which Andy never loads; it stays
# the draft record). Approval alone activated nothing: these lines were moved here
# in their own commit. Each active line is
# {category, text, source, asserts}: `category` maps (below, explicitly) to the
# checker rule-ids it may be cited for; `asserts` is "refuse" for a real standing
# refusal, and a line that "allow"s something policy blocks is reported as a
# conflict and NOT cited.
SEEDED_FACTS: list[dict] = [
    {"category": "no-exfiltration",
     "text": "Nothing of mine leaves this machine on its own — Andy doesn't post, upload, email, or send my files or data anywhere.",
     "source": "policy.toml rule 'exfiltration' (block)", "asserts": "refuse"},
    {"category": "no-unapproved-financial",
     "text": "Andy never moves money — no wires, transfers, or payments from my accounts.",
     "source": "policy.toml rule 'financial' (block)", "asserts": "refuse"},
    {"category": "no-destructive-without-approval",
     "text": "Destructive actions wait for me — deleting, overwriting, wiping, or erasing is held until I say go.",
     "source": "policy.toml rule 'destructive' (stage)", "asserts": "refuse"},
    {"category": "no-secret-fields",
     "text": "Andy doesn't read or act on secret fields — passwords, keys, tokens, or one-time codes.",
     "source": "policy.toml rule 'secret-fields' (block)", "asserts": "refuse"},
    {"category": "stay-on-task",
     "text": "Andy stays on my active task and won't be talked into ignoring its own gate.",
     "source": "policy.toml rule 'off-task' (block)", "asserts": "refuse"},
    {"category": "no-system-commands",
     "text": "Andy doesn't run shell or system commands outside its own tools.",
     "source": "policy.toml rule 'system-command' (block)", "asserts": "refuse"},
    {"category": "no-comment-on-people",
     "text": "Andy doesn't comment on, rate, or judge people.",
     "source": "policy.toml rule 'about-people' (block)", "asserts": "refuse"},
]

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
