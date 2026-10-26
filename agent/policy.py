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
