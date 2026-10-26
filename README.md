# Agent Andy

A voice-driven personal agent that cannot act without leaving a receipt.

Every action Andy takes — a tool call, an observation, even an unprompted
remark — is written to a hash-chained receipt log *as part of taking it*, and
a separate checker (a different model, on different weights, running locally)
rules on every action before it executes. Change one byte of the history and
verification fails. Miss a visual confirmation and the checklist refuses to
tick. The agent's claim is never "trust me"; it is "here is the chain —
recompute it."

Built solo for the **Meta Global AI Developer Hackathon** (Oct 26 – Nov 4,
2026) · **Indie Developer** track · theme: **Build for Your World**.

## Architecture

| Part | What it is | Model |
|---|---|---|
| Brain | proposes actions from voice input | Muse Spark (`muse-spark-1.3`, Meta Model API) |
| Checker | rules on every proposed action, locally | Muse Glimmer (open-weight, self-hosted) |
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

## Build log — what was built Oct 26 – Nov 4

- **Oct 26 (kickoff day):** repo created; receipt chain (`receipts/chain.py`),
  fail-closed verifier (`receipts/verify.py`), policy rules as data
  (`agent/policy.py`), deterministic Day 1 checker, gated tool registry, loop
  sketch, and the Day 1 acceptance test (3 receipts verify; 1 flipped byte
  fails verification).

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
