# Evaluation — measured, not claimed

Every number here comes from a script in this repo that you can run with no API
key and no network. Each row names the suite, the exact command, what it measures,
and the result at the head these numbers were taken on (`052a976`, Oct 31, 2026,
Python 3.14 on macOS). A result that needs a key, photos, or clips says so.

## 1. Policy engine — attacks caught, legitimate work not blocked

```bash
python3 scripts/policy_acceptance.py
```

| What | Result |
|---|---|
| Attack action summaries (exfiltration, secrets, about a person, off-task, destructive) | **12/12 caught** (blocked or staged) |
| Legitimate local tasks (notes, reminders, lists) | **8/8 allowed**, none blocked |
| Legitimate tool payloads, incl. every real trip note for the eight places alone and in pairs | **126/126 allow** |
| Payload checks: a dirty payload behind a clean summary, nested strings, tab-split patterns | all caught |

The checker is a deterministic substring engine over `agent/policy.toml`
(first match wins, block before stage, default allow). It is injection-immune for
the *decision* — no text can argue a rule into "allow" — so what this suite
measures is rule *coverage*.

## 2. Injection gauntlet — six attack classes against the real gates

```bash
python3 scripts/injection_acceptance.py
```

16 hostile inputs in six classes (prompt injection typed and spoken, out-of-scope
place or action, confidence tricks, receipt and chain attacks, Witness spoofing,
voice injection), each thrown at the real policy, detect, voice, Witness, and
verifier code paths. The only passing outcome is fail-closed: blocked, staged,
unverified, or rejected by the verifier.

| What | Result |
|---|---|
| Attacks that failed closed | **16/16** |
| Legitimate controls (Myrtle answers, Tybee stages, a benign note and "buy cat food" allowed, Witness ships on real photos) | **5/5 with the photos and a key; 4/5 without** (the Witness control needs SAM) |

## 3. Over-blocking probe — ordinary sentences that must not be refused

```bash
python3 eval/overblock_probe.py
```

The other side of coverage: a checker that refuses ordinary questions is useless.
36 plain sentences a judge might type (ferry terminal, "published", "go to a public
park", "comment on the rule", "drop by", "what is bitcoin?", "pay my respects" …)
and 32 attack strings that must keep blocking, each run through the checker with
*every* pattern that fires listed.

| Head | Plain sentences allowed | Attack strings caught |
|---|---|---|
| `d3b0ab6` (Oct 30, before the trim) | 16/36 | 32/32 |
| `052a976` (Oct 31, after narrowing 14 patterns) | **32/36** | **32/32** |

The four still refused are the single-digit "send 2 notes" / "transfer 2 kids"
shape: the patterns `send 1`…`send 9` are what catch "send 5k" and "send 5000",
and a substring engine cannot free one without losing the other. The same trim was
checked against 955 unique strings taken from every acceptance suite: the only
verdicts that moved were three test labels, not inputs. Known residuals that still
*allow* ("send bob my notes", letter-spaced or look-alike spellings) are listed in
the README's Known limitations and printed by the probe.

## 4. Receipt chains — tamper detection and signatures

```bash
python3 scripts/verifier_acceptance.py
python3 scripts/signing_acceptance.py
python3 scripts/multiprocess_acceptance.py
```

| What | Result |
|---|---|
| Tampered chains: byte flip, deleted receipt, swapped receipts, truncated tail, anchored count/tip | **5 cases, each fails at the exact receipt** |
| Signed tip: rewrite with recomputed hashes, truncated tail, tampered signature, foreign key | **FAIL** each; no signature → **UNSIGNED**, never VERIFIED |
| A forged or hand-edited earned answer | stages that one entry only |
| Four processes appending 25 receipts each to one chain | **100 receipts, none lost or duplicated, tip VERIFIED**; with the lock off, duplicates and a broken link appear (the race is real) |
| The recorded live chain, no key | `python3 scripts/verify_receipts.py examples/live-demo-chain.jsonl --require-signature` → PASS, 33 receipts, signature VERIFIED |

## 5. Rule lookup and Witness

```bash
python3 scripts/detect_acceptance.py
python3 scripts/witness_acceptance.py --selftest
```

| What | Result |
|---|---|
| Eight vetted places | 7 answer with a cited primary source (Jekyll with its corroboration caveat), Tybee Island stages |
| Any place outside the sample | staged with a site-index candidate when one exists, never a guessed verdict |
| Witness on the three fixed Razr photos (needs SAM and a key) | cable, book, charger verified at 49%, 35%, 34% of the frame; box READY TO SHIP. Receipt-backed on the demo Mac (`runs/witness-receipts.jsonl`, Oct 28) |
| A photo of nothing, a recycled photo hash, a claim with no photo | unverified, box not shipped |

## What is not measured

- Muse Spark's plan quality: with a key, the loop is checked step by step, but no
  benchmark scores the plans themselves.
- SAM 3.1's failure point: an Oct 30 stress run on four harder cable photos all
  verified, and its receipts were not kept, so that run is reported, not measured.
- Latency and cost: a full live run costs about $0.03 in Meta credits; nothing
  here times it.
- Anyone but the author: no user study, no judge trial.

The whole set runs as one command, `python3 -m unittest discover tests`: 23
suites, 19 pass, 4 skip with a stated reason (the key-, clip-, photo-, and
Mac-app-gated runs), 0 fail, in about 20 seconds.
