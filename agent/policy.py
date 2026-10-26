"""Policy: what Andy may do, when he may speak, and what he never touches.

These rules are data, not vibes — the checker enforces them in code. Decided
Oct 26 before kickoff; they change only by an explicit owner decision recorded
in the README build log.
"""

# Actions the checker refuses outright, regardless of what the brain proposes.
NEVER = [
    "comment on people",
    "read or act on text fields or password prompts",
    "act outside the active task",
    "post or send anything off-machine",
]

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

# ---- Deterministic placeholder-checker triggers (case-insensitive substrings) ----
# These are the fixed scope rules today's checker matches on. They stand in for
# the open-weight model checker, not replace it: honest and auditable, but shallow.
# An off-scope action is BLOCKED; an irreversible one is STAGED for a human.
BLOCK_TRIGGERS = [
    "post ", "tweet", "publish", "upload", "email ", "send to", "dm ",
    "off the machine", "off-machine",            # nothing leaves the laptop
    "comment on", "rate the", "judge the",       # never about people
    "password", "credit card", "ssn", "api key", # never touch secret fields
    "outside the task", "off-task",              # never act outside the active task
]
STAGE_TRIGGERS = [
    "delete", "remove", "overwrite", "erase", "uninstall",
    "wipe", "purge", "format ", "rm -", "drop ",
]
