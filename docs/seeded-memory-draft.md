# Seeded memory — DRAFT

**DRAFT · NOT ACTIVE · NOT LOADED BY ANDY.**

**Status, Oct 30, 2026:** Tony approved all seven lines below. Approval alone activated
nothing: a separate commit copied them word for word into `agent/policy.py`
`SEEDED_FACTS`. This file is still never loaded by Andy; it stays as the draft record.

These are proposed standing-policy lines, in Tony's own words, to be **cited** (never
enforced) when the deterministic checker *already* blocks or stages a request — so a
refusal reads "because the owner said so, and here is the receipt," not as a model
opinion. `policy.toml` stays canonical and **wins every conflict**.

The active list — `agent/policy.py` `SEEDED_FACTS` — was **EMPTY** until Tony
approved the lines; it was filled in a later session. Andy never reads this
file; nothing here is live. Checking a box records approval; it does **not** activate
anything by itself — a later session moves an approved line into `SEEDED_FACTS` as a
`{category, text, source, asserts: "refuse"}` entry.

Every line below traces to an existing `policy.toml` rule, and none contains private
data, keys, tokens, or personal details (no location, schedule, or account facts).

## Proposed lines — approve one at a time

- [x] **no-exfiltration** — "Nothing of mine leaves this machine on its own — Andy
  doesn't post, upload, email, or send my files or data anywhere."
  _source: `policy.toml` rule `exfiltration` (block)_

- [x] **no-unapproved-financial** — "Andy never moves money — no wires, transfers, or
  payments from my accounts."
  _source: `policy.toml` rule `financial` (block)_

- [x] **no-destructive-without-approval** — "Destructive actions wait for me —
  deleting, overwriting, wiping, or erasing is held until I say go."
  _source: `policy.toml` rule `destructive` (stage)_

- [x] **no-secret-fields** — "Andy doesn't read or act on secret fields — passwords,
  keys, tokens, or one-time codes."
  _source: `policy.toml` rule `secret-fields` (block)_

- [x] **stay-on-task** — "Andy stays on my active task and won't be talked into
  ignoring its own gate."
  _source: `policy.toml` rule `off-task` (block)_

- [x] **no-system-commands** — "Andy doesn't run shell or system commands outside its
  own tools."
  _source: `policy.toml` rule `system-command` (block)_

- [x] **no-comment-on-people** — "Andy doesn't comment on, rate, or judge people."
  _source: `policy.toml` rule `about-people` (block)_

---

*Status: approved by Tony on Oct 30, 2026 and activated in a separate commit (see the
status note at the top). The session that drafted this file activated nothing.*
