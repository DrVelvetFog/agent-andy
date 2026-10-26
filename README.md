# Agent Andy

A voice-driven personal agent that cannot act without leaving a receipt.

Every action Andy takes — a tool call, an observation, even an unprompted
remark — is written to a hash-chained receipt log *as part of taking it*, and
a separate checker — a deterministic policy engine in its own trust domain,
local, with no model and no network — rules on every action before it executes.
Change one byte of the history and
verification fails. Miss a visual confirmation and the checklist refuses to
tick. The agent's claim is never "trust me"; it is "here is the chain —
recompute it."

Built solo for the **Meta Global AI Developer Hackathon** (Oct 26 – Nov 4,
2026) · **Indie Developer** track · theme: **Build for Your World**.

## Architecture

| Part | What it is | Model |
|---|---|---|
| Brain | proposes actions from voice input | Muse Spark (`muse-spark-1.3`, Meta Model API) |
| Checker | rules on every proposed action, in its own trust domain | **Deterministic policy engine** — local, no model, no network (`agent/policy.toml`) |
| Eyes | verified observation for Witness receipts | SAM 3.1 (`sam-3.1`, Meta Model API) |
| Voice in | speech to text | Muse Voice Transcribe |
| Receipts | hash-chained, fail-closed action log | stdlib, no model — `receipts/` |

The loop is perceive → propose → **check** → act → **receipt**, in that order,
every turn. There is no code path to a tool that skips the checker, and no
action that doesn't leave a receipt.

## Try the Day 1 acceptance test

```bash
python3 scripts/day1_acceptance.py
```

It writes three stub actions as receipts, verifies the chain, then flips one
byte and shows verification fail. No network, no API key, no dependencies.

## Try the gated-loop acceptance test

```bash
python3 scripts/gated_loop_acceptance.py
```

A full turn from text input: Muse Spark proposes a plan as JSON, the checker
rules on every step, and each step is receipted *before* it runs. Shows an
allowed action executing, a staged action held, a blocked action refused, the
chain verifying, and a one-byte tamper rejected by name. Needs `MODEL_API_KEY`
(the Spark call); the checker is local.

## Try the policy-engine test

```bash
python3 scripts/policy_acceptance.py
```

Runs the deterministic checker against real attack and legitimate-task cases
and prints a measured score — no network, no model. Current: 12/12 attacks
caught (blocked or staged), 8/8 legitimate tasks allowed, 0 blocked.

## Build log — what was built Oct 26 – Nov 4

- **Oct 26 (kickoff day):** repo created; receipt chain (`receipts/chain.py`),
  fail-closed verifier (`receipts/verify.py`), policy rules as data
  (`agent/policy.py`), deterministic Day 1 checker, gated tool registry, loop
  sketch, and the Day 1 acceptance test (3 receipts verify; 1 flipped byte
  fails verification).
- **Oct 26 (gated loop):** the loop now runs end to end — Muse Spark
  (`agent/brain.py`) proposes a JSON plan from a text utterance, the checker
  (`agent/checker.py`) rules allow / stage / block on every step, and each
  step is receipted before it can run. Tools (`agent/tools.py`) are safe,
  local, and sandboxed. Acceptance: `scripts/gated_loop_acceptance.py`.
- **Oct 26 (independent verifier):** `receipts/verify.py` re-reads a chain
  from disk and recomputes every hash itself, trusting no cached state; an
  optional tip/count anchor catches a truncated tail, which a bare hash chain
  cannot. A plain-language CLI (`scripts/verify_receipts.py`) and an acceptance
  test (`scripts/verifier_acceptance.py`) cover a 12-receipt mixed chain and
  five tamper cases — middle/last byte flip, middle delete, adjacent swap, tail
  truncation — each failing by exact receipt.
- **Oct 26 (policy engine):** the checker is a deterministic policy engine. Its
  rules, risk tiers, and reasons live in a readable file (`agent/policy.toml`),
  not in hidden code, and each verdict's reason is written into the receipt. It
  is local and fail-closed, with no model, no network, and no GPU in the live
  loop — so every verdict is fast, repeatable, and auditable, the behaviour we
  want in a live demo. It stays in its own trust domain from the brain: separate
  code path, separate rules, receipts before execution. Measured by
  `scripts/policy_acceptance.py`: 12/12 attack cases caught (blocked or staged),
  8/8 legitimate tasks allowed, 0 blocked.

## Prior inspiration — not claimed as hackathon work

Everything in this repository was written during the hackathon window. Three
earlier ideas of mine inspired the design, as concepts only — none of their
code is used here:

- the **taint-gate concept** from my local assistant Plummy (actions that
  follow untrusted input stage behind a human keypress),
- the **receipt-format concept** from my aee-e2 evidence experiments
  (per-claim evidence tiers in signed statements),
- the **fail-closed recompute pattern** from my Kaspa verifiable-index work
  (anything the verifier cannot positively confirm is a failure).

## License

MIT — see [LICENSE](LICENSE).
