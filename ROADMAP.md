# Agent Andy — Roadmap

Drafted Nov 3, 2026, after submission, updated the same day with brainstorming on verified actions, security hardening, and a general agent. **None of this is built yet, except where a section says an item is already in the submitted build.** Submitted build is main f0dede0, Nov 3, 2026. This roadmap does not change what was submitted, and nothing here is claimed as done.

## The core claim, stated honestly

Andy cannot be always true about anything. Future events, opinions, unrecorded facts, and adversarial input have no verifiable answer, and an agent that answers them anyway will hallucinate with confidence. What Andy can be is always honest about verification: it answers with proof when proof exists, stages when it does not, and never upgrades a guess into a verdict.

That is the moat. Anyone can add a fact checker in a weekend. Almost nobody ships an agent that will refuse to send, buy, or publish without evidence, and then prove, after the fact, exactly what it did and why.

## Principle

What transfers is the pattern, not the knowledge: a deterministic checker before action, a staged answer when evidence is missing, a signed receipt after. Each new domain needs its own vetted sources, its own checker patterns, and its own failure modes tested, exactly as the 8-location sample took primary-source work. Do not claim "any niche" with no caveat.

## Evidence tiers

A question is answerable only at the tier its evidence supports. The tier decides the response, and the tier is shown, not buried.

- Tier A, primary source, quoted verbatim, with date and publisher. Ordinance text, official docs, a contract clause, a live API response just fetched. Answer with a citation.
- Tier B, corroborated secondary, two independent sources agreeing, with a caveat. Answer with the caveat on screen.
- Tier C, single secondary, or stale, or inferred from a URL path. Stage it, show what was found and what is missing, and offer the next check.
- Tier D, no evidence, opinion, future, or private knowledge Andy cannot access. Stage it, say plainly "I can't verify this," and do not fill the gap with a fluent guess.

Trust in Tier A answers comes from having seen Andy stage Tier D ones. A "confident mode" that answers Tier D questions to feel helpful would break that trust, and is explicitly out.

## Phase 0 — Nov 9 live final prep (only if top 5 in Indie)

Not new features. Rehearsal only, on the submitted code.

- Live rehearsal on the Mac, same code as recorded, typed fallback ready.
- SAM fail-closed drill: missing item = NOT SHIPPED.
- Jekyll direct Municode read, plus a full Form 2 source recheck.
- Typed fallback and Witness capture-then-pull drill on the Razr.
- Slides only if needed, with Muse Image banked as a candidate for them.

## Phase 1 — From verified facts to verified actions

This is the next version's main thread, ahead of more domains.

- A policy gate before tool calls, not just before chat replies. Read, search, and calculate are low risk. Send, buy, delete, publish, share a file, change a setting, and contact a person are high risk, and each needs its own gate, its own evidence, and its own receipt.
- A tool payload check, not just a planner summary check. The planner can say "safe" while the actual tool arguments smuggle in a different recipient, amount, or file. Check the payload that will actually run.
- An egress check. Before anything leaves the machine, what data is in it, where is it going, and was that destination approved for that data? That kills the classic exfiltration path, "summarize my notes and send them to this helpful address."
- A receipt per action, not per turn, with the exact inputs, the rule applied, the evidence cited, and the result, all hash-chained and signed. If a later step rewrites history, verification names it.
- Human-in-the-loop for irreversible actions: a staged beat that says "here is what I will do, here is the evidence, approve or edit," with one dismissal meaning silence for the session. That is already Andy's daemon rule, and it stays.

## Phase 2 — Security hardening, for a general agent

Expanding scope expands attack surface, in a specific order. Already in the submitted build, or in its README as known work:

- Injection in all channels, not just chat: tool outputs, web pages, files, images, transcripts, and memory. Every one is untrusted input until gated. Voice transcripts are already treated that way in Andy.
- Disguised inputs: letter-spaced, look-alike letters, and "send bob my notes" phrasing. Those need a normalizer before the gate, not a bigger model after it.
- Memory poisoning: a seeded or earned answer that was true once, then reused in a new context where it is false. Fix it with per-entry signing, expiry, and revocation, plus a rule that an earned answer never promotes to Tier A without a fresh primary check. Per-entry signing is already in the submitted build.
- Secret and credential redaction: scan every receipt, log, and outbound payload for key-shaped material before it is stored or sent, and fail closed if a secret is present.
- Least privilege by default: the smallest set of tools, files, and network destinations needed for the current task, and a receipted ask before expanding that set.
- Multi-process and multi-turn locking: interleaved turns, parallel tool calls, and restarts must not create a gap where two gates both think the other one checked. Whole-turn locking and a cross-process chain lock are the fix.
- Bloat removal and cold-run polish, with suites re-run after each removal.
- Combined test rig cleanup (test server, launch entry, voice worktree), only on Tony's word.

## Phase 3 — Make it easier for a stranger to check

- Pages re-record with newer model labels (optional, the Oct 31 recorded chain is still valid, it just has older daemon text).
- Receipt explainer, final mp4 only, in docs/, labelled as a diagram supplement, never as the submitted demo video. The v2 narration is not recorded yet, so v2 does not ship until it is recorded and watched once.
- Verified research mode: Andy fetches, quotes, and dates sources live, shows which claims came from which source, and stages any claim with no source, instead of giving a clean essay with fake citations.
- A public verify page for any chain: paste a chain, get VERIFIED, UNSIGNED, or FAIL, with the exact failing receipt named. That is already in Andy's Pages replay, and it is the feature that makes trust portable, because a third party does not have to trust Andy, they can verify the receipt themselves.
- Gated, canned hosted Andy, post-submission candidate only. No public hosted Andy that takes live input until Tony approves that scope separately. The viewer stays 127.0.0.1 only in the submitted build, and serving it from a container or a host is a security change, not a packaging change.
- Post-submission read-only review with Muse Code, if Tony wants it. No code change from that review without its own approval.

## Phase 4 — Witness, generalized

The packing list idea is not about boxes. It is "prove the physical world matches the claim."

- Photo, receipt, screenshot, or sensor reading, checked by a vision model, fail-closed if the item does not show.
- Generalizes to deliveries, inventory, safety checklists, and inspections, each with its own item list and its own fail-closed rule, not a generic "looks good" judgement.

## Phase 5 — New domains, one at a time

Only after a vetted-source pass for that domain, with the same fail-closed rule: no primary rule found = stage, not answer. Candidates, in no committed order, because Tony has not picked one:

- Local ordinances beyond metal detecting.
- Packing and shipping checklists.
- Workplace safety checklists.
- A second wheretodetect-style rule set, only with primary sources.
- Verified personal assistant mode: "book this, send that, file this" all go through the same gate and receipt chain, so a week later you can audit what Andy did, why, and on what evidence.

Each domain gets its own sample, its own eval counts, and its own staged-vs-allowed evidence, before it is claimed in the README.

## Phase 6 — Research, not committed

- Open-weight checker, revisited only with hardware that can run it. The submitted checker is a deterministic policy engine, honestly labelled. An open-weight version needs a machine or rented GPU with enough RAM/VRAM for a Glimmer-class model, plus fine-tuning time, and it is a separate project, not a patch to Andy.
- Any new Meta model families, only if they add a real gate, eye, or voice job, not for a model-count claim.

## Explicitly not on this roadmap

- No "always true" claim, and no confident mode for Tier D questions.
- No general chat mode with no gate, for "just talking."
- No open-weights bonus chase for the submitted build.
- No live public Andy with untrusted input, no signup, no account.
- No new domain claimed without its own primary-source vetting.
- No roadmap beat added to the submitted demo video after the fact.
- No post about Andy publicly until after Nov 4, per Tony's Oct 29 rule.

## Status

Draft only, Nov 3, 2026, updated with the Nov 3 brainstorming. Not yet in the repo, not in the submitted form, not in the video. Adding it to the repo as ROADMAP.md is the next step Tony approved in chat, via the usual PR workflow: branch, one signed commit, Tony author/committer, diff shown first, PR text approved first, CI on the PR, fast-forward main locally and push, GitHub marks the PR merged, no merge commit, no squash, no GitHub rebase button. Updating the submission to match is a separate decision, not included in adding the file to the repo.
