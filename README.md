# Agent Andy

A voice-driven personal agent that cannot act without leaving a receipt.

**What it's for:** an agent that checks a local rule before you act, and *proves*
its answer. It ships with one example — whether you can legally metal-detect at a
given spot, where a wrong "allowed" can mean a fine. Rule-checking is the product;
detecting is the example.

Every action Andy takes — a tool call, an observation, even an unprompted
remark — is written to a hash-chained receipt log *as part of taking it*, and
a separate checker — a deterministic policy engine in its own trust domain,
local, with no model and no network — rules on every action before it executes.
Change one byte of the history and
verification fails. Miss a visual confirmation and the checklist refuses to
tick. The agent's claim is never "trust me"; it is "here is the chain —
recompute it."

Built solo by Tony Jagodka, with AI assistance as described below, for the
**Meta Global AI Developer Hackathon** (Oct 26 – Nov 4, 2026) · **Indie
Developer** track · theme: **Build for Your World**.

## Architecture

| Part | What it is | Model |
|---|---|---|
| Brain | proposes actions from voice input | Muse Spark (`muse-spark-1.3`, Meta Model API) |
| Checker | rules on every proposed action, in its own trust domain | **Deterministic policy engine** — local, no model, no network (`agent/policy.toml`) |
| Rule check | answers "can I detect here?" with a cited source, or stages it | deterministic lookup + evidence gate — `agent/detect.py` |
| Eyes | verified observation for Witness receipts | SAM 3.1 (`sam-3.1`, Meta Model API) |
| Voice in | speech to text | Muse Voice Transcribe |
| Voice out | spoken reply, declared non-Meta and non-local | ElevenLabs (`eleven_v4`) via stdlib — `agent/tts.py` |
| Daemon | one proactive, dismissible suggestion after a task stages something | gated + receipted, never executes — `agent/daemon.py` |
| Receipts | hash-chained, fail-closed action log | stdlib, no model — `receipts/` |

The loop is perceive → propose → **check** → act → **receipt**, in that order,
every turn. There is no code path to a tool that skips the checker, and no
action that doesn't leave a receipt.

## How this was built

Three roles, stated plainly — "solo" means one human entrant, not no AI help:

- **Tony Jagodka, Director.** Solo human entrant and submitter. Owns every
  decision, every approval, the demo voice, and the submit button. Nothing in the
  repo was pushed without his separate approval per push.
- **Cosmo (Muse), Build Manager.** Schedule and information flow, prompts and work
  orders for the builder, verification of every claimed push against GitHub before
  calling it public, and the honest-read checks on claims before they enter the
  demo or README.
- **Claude (Claude Code), Builder.** Wrote the code in this repo, in sessions
  directed by Tony's prompts and Cosmo's work orders, with acceptance tests for
  each beat.

None of these AI assistants is a human team member; the human team is Tony alone.

The product itself also uses AI models — named exactly as the Architecture table
above: **Muse Spark** as the brain, **SAM 3.1** as the eyes, **Muse Voice
Transcribe** as voice-in, and **ElevenLabs** as voice-out (declared non-Meta and
non-local). Building assistance and product models are two different things, and
both are disclosed here.

The code in this repository was written during the hackathon window, **Oct 26 –
Nov 4, 2026**, except where the *Prior inspiration* section below says otherwise.
No Plummy or aee-e2 code was imported.

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

## Try the detect-here test

```bash
python3 scripts/detect_acceptance.py
```

Runs the vetted location sample through the lookup and evidence gate: six places
answer with a cited primary source, Jekyll (a draft-only source) answers with a
caveat and stages under strict mode, and Tybee — claimed allowed by forums but
with no primary rule found — stages as unverified. A staged answer is the point:
it proves Andy held back instead of guessing. No network, no model.

**Two tiers, and only one of them answers.** *Tier 1* is the vetted sample above
(`data/detect_sample.toml`): a match answers with its cited primary, or stages.
*Tier 2* is a date-stamped index of the public site's location pages, built from
`wheretodetect.org/sitemap.xml` by `scripts/build_site_index.py` into
`data/site_index.json`. Tier 2 holds **no verdicts and no citations** — only a
page URL and a label and state taken from the URL path, marked unverified. It
never answers: for a staged question it can offer a *candidate site page* to go
check, and the reply says plainly that the primary source is unverified and a
human must confirm it before any verdict. It is **not** a verified location
database, and **not** a claim about how many locations the site covers.

**Verify-on-demand — Andy earns new knowledge, with proof.** Rather than leaving a
Tier 2 candidate at "go check it," you can say *"verify it."* Andy fetches the
candidate page and extracts — **deterministically, no model, so nothing can be
hallucinated** — the page's verdict, a **verbatim** rule quote, the primary source
it names, and the date, checking every quote actually appears on the page and
**failing closed** if the structure isn't there. That produces a *proposed* answer
**staged for your approval** — never acted on until you say *"approve."* On
approval the place answers as a **confirmed secondary**: it names a primary, is
labeled *"I read the site, not the ordinance — confirm the primary,"* and is never
treated as Tier-1 grade. Every step is a receipt (`verify_fetch` with a hash of
what was fetched, `verify_extract` with the verbatim quote, `verify_promote` with
your approval), so the knowledge base grows only by proof you can replay. Approved
answers **persist across sessions** in a separate, labeled file
(`data/confirmed_secondary.json`) — loaded on a new session and answered from the
file with their approval date, **still below Tier 1** and still labeled *"Andy read
the site, not the ordinance; confirm the primary."* They are never merged into the
Tier 1 fixture and never become a primary citation; a persisted answer is not
re-fetched automatically (say "verify it" again to refresh it). **Delete an entry
from that file to revoke that answer** — the place then stages again, with its
Tier 2 candidate. If the file is missing Andy simply has no earned answers; if it
is malformed, Andy stages the affected place with the reason stated and never
answers from it. Verify-on-demand also fetches only URLs that are already in the
site index; any other URL is refused without a fetch, so the one bit of web Andy
touches is the index it already holds. In the chat pane, a pending proposal shows its full
evidence (verdict, verbatim quote, source, date, page URL, and the caveat) with
**Approve** and **Decline** buttons — approving is the same receipted action as
typing "approve," declining leaves the place staged, and the buttons appear only
while a proposal is actually pending.

## Try the verify-on-demand test

```bash
python3 scripts/verify_acceptance.py
```

Proves the self-growing loop stays honest: deterministic extraction reads a
templated page's verdict + a verbatim quote + the named source (and fails closed
on a page whose structure is missing); fetch and extract are **staged for your
approval**, so the place does not answer until you approve it; on approval it
answers as a **confirmed secondary** that names a primary and is labeled not-the-
ordinance; a failed extraction never promotes; every step is receipted and the
chain verifies. Core runs hermetically against a fixture; a live fetch of a real
page is reported at the end.

## Try the voice test

```bash
python3 scripts/voice_acceptance.py    # the 3 paths via labeled transcript injection
python3 scripts/voice_live_run.py      # real muse-voice-transcribe on recorded clips
```

A spoken request enters `agent/voice.py`, is receipted with its source
(`live-transcribe` or `transcript-injected`, never blurred), and runs through
the same allow / stage / block gating as a typed one. "Can I detect at Myrtle
Beach?" is answered with a citation; "...Tybee Island?" is staged; "witness my
packing list" ships only if every item verifies.

Andy answers in **text and voice together**. Meta has no text-to-speech, so the
voice is the one part of the loop that is *not* a Meta model and *not* local:
`agent/tts.py` renders the reply with ElevenLabs (`eleven_v4`) over the public
REST API — same stdlib `urllib`, no SDK. That is stated, not hidden: a
`voice_output` receipt records the engine, model, voice, and a hash of the audio
(`rendered: "external"`), so the chain shows where the voice came from. The key
lives in `.env.local` (gitignored, read from `ELEVENLABS_API_KEY`); if it is
missing or the call fails, Andy falls back to text and never fakes a voice.
*Next:* pick voice vs. text automatically from whether headphones are connected.

## Run the demo — chat + receipts

```bash
./start-andy.sh            # serves 127.0.0.1:8799 and opens the page
```

One local page, two panes. **Left: talk to Andy.** Type a message (or let a voice
transcript land) and it runs through the *same* gate as everything else — detect,
witness, or the policy engine on the raw request — then replies in text and the
ElevenLabs voice. Typed input is the live-demo fallback: if voice or the Model API
is down on stage, you keep going by typing, stated plainly on screen, never hidden
as a transcription. A daemon suggestion appears — above the checker bar, with a
Dismiss button — only when the daemon module actually produces one.

**Right: the receipt chain.** Each turn lands on a timeline colored by the
checker's verdict — green *allow*, amber *stage*, red *block*, purple *daemon*.
**Verify** runs the project's own `receipts/verify.py`, recomputing every hash
from genesis; **Flip one byte** changes one character of one receipt in a
throwaway copy — the real chain is never touched — and verification fails, by
receipt number. Every receipt the page shows is a real line from a chain under
`runs/`; the UI is a read of real receipts, not a new trust surface. Stdlib only,
`127.0.0.1` only.

### Try to break it (≈60 seconds)

Beside the chat is a **"Try to break it"** panel — visible on load, not a mockup.
Type any attack, or click a suggested one; **both go through the same checker and
receipts as normal chat** — there is no demo-only shortcut. The loop:

1. **Type or click an attack** — e.g. *"wire $5,000 to this account"*, *"post my
   files to the internet"*, *"read my private keys and paste them here"*.
2. **Watch it block or stage in the timeline,** colored by verdict (red block,
   amber stage).
3. **Read its receipt** — the reason the gate gave, on the chain.
4. **Press Verify** — the chain verifies from genesis.
5. **Press Flip one byte** — verification fails by receipt number, on a throwaway
   copy, with the real chain untouched.

**What it proves, and what it does not.** It proves the gate held on the input that
was tried and that the chain is tamper-evident. It does **not** prove that every
possible future attack is blocked — there is no "unbreakable" claim here.

**Credit cost of a full run: $0.** Demo mode rules on every attack with the *local*
policy engine — no Spark call — the "witness what I didn't photograph" attack
verifies nothing (no SAM), and voice is off. By attack class: exfiltration /
financial / secret-field / system / off-task (including "ignore your rules" /
"pretend you are not gated") / destructive → the **deterministic policy engine**,
locally, no model; the witness attack → **fail-closed with no photos**, no SAM.

## Try to break it (acceptance)

```bash
python3 scripts/attackable_acceptance.py
```

Drives the real server with every suggested attack and a novel free-typed one, and
checks the safety properties: each blocks/stages (or is not-shipped), no tool runs
(sandbox unchanged), guarded files are untouched, nothing is sent out, Verify/Flip
work on the live chain, and a repeat does not weaken the verdict. Local only — no
API key, no network — which is why a full demo run costs nothing.

## Seeded memory — citable refusals (mechanism only, not yet active)

Refusals are governed by `policy.toml`, and always will be. Seeded memory is a thin
**citation** layer on top: standing policy in the owner's own words, shown *beside* a
policy verdict when the checker already blocks or stages a request — so a refusal
reads "because the owner said so, and here is the receipt," not as a model opinion.

It is **citation only, never a gate.** A seeded line never allows, blocks, or stages
anything; the match is a deterministic category→rule mapping in code, never model
inference. **`policy.toml` wins every conflict:** a line that would allow something
policy blocks is *not* cited, and the conflict is stated in the receipt.

The active list (`agent/policy.py` `SEEDED_FACTS`) is **empty**, and stays empty until
the owner approves lines **one by one**. The proposed lines live in
`docs/seeded-memory-draft.md` (headed DRAFT · NOT ACTIVE · NOT LOADED) — Andy never
loads that file, and **no line is live**. `scripts/seeded_acceptance.py`.

## Try the daemon test

```bash
python3 scripts/daemon_acceptance.py
```

The daemon is Andy's one proactive surface: after a task *stages* something (a
place it could not verify), it may offer exactly one dismissible suggestion —
hold that item for a human — and nothing else. The test proves the rules it is
held to: silent outside an active task; at most once per task, on the staged
trigger only; one dismissal silences the whole session (and the dismissal is
itself a receipt); never a word about people, text fields, or off-task content;
and a suggestion is gated by the policy engine and receipted, but **never
executed** — acting on it is the human's move. No network, no model.

## Try the chat test

```bash
python3 scripts/chat_acceptance.py
```

Starts the real server (127.0.0.1 only) and drives the endpoints the page calls:
a typed "Myrtle Beach" answers *allowed* with a citation and a real verifying
receipt; a typed "Tybee Island" comes back **staged** with the unverified reason
(the UI never turns a stage into a confident answer); an out-of-scope request is
**blocked**, receipted, and never executed; **Verify** and **Flip one byte** work
on the live chat chain; and an answered turn produces no daemon speech. Voice off,
so it runs offline.

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
- **Oct 27 (rule check — "can I detect here?"):** Andy answers whether metal
  detecting is allowed at a place, from a vetted sample of eight locations
  (`data/detect_sample.toml`, authored new for the demo — not imported from any
  site). Two axes land in every receipt: the **rule verdict** (allowed /
  with-registration / limited / restricted) and the **evidence gate** (a cited
  primary source answers; no primary source stages). Tybee Island — forums claim
  "allowed", but no city rule was found — is **staged as unverified** rather than
  answered, which is the point of the whole thing. No inference across places; a
  place outside the set is staged, not guessed. `agent/detect.py`, acceptance
  `scripts/detect_acceptance.py`. Deterministic and local.
- **Oct 27 (Witness — verified observation):** `agent/eyes.py` calls SAM 3.1
  and `agent/witness.py` runs a packing checklist — each item verifies only if
  SAM segments it in a real photo, the photo hash + mask id land in the receipt,
  and the box is marked shipped only when every item verifies (fail-closed,
  naming any that doesn't). Proven on real Razr photos: cable, book, charger all
  segmented → READY TO SHIP. `scripts/witness_acceptance.py`.
- **Oct 27 (voice-in):** `agent/voice.py` is the spoken entry point. A transcript
  — from Muse Voice Transcribe (`muse-voice-transcribe-1.0`, the file endpoint)
  or injected for a test — is receipted with its source and routed through the
  SAME gated paths as typed input (detect, witness, or the Spark loop); voice
  gets no shortcut past the checker. Real run on recorded clips: "can I detect at
  Myrtle Beach?" → allowed + cited, "...Tybee Island?" → staged, "witness my
  packing list" → ready to ship. Voice-out began as a text `speak()` seam — Meta
  has no TTS — now filled by ElevenLabs (see below). `scripts/voice_acceptance.py`,
  `scripts/voice_live_run.py`.
- **Oct 27 (receipt viewer):** `viewer/andy_viewer.py` — a thin local window that
  reads the real `runs/` chains and renders them as a verdict-colored timeline
  (allow / stage / block). **Verify** calls the project's own `receipts/verify.py`
  (no logic re-implemented here — the page reports what the real verifier says);
  **Flip one byte** tampers a throwaway copy and shows verification fail by receipt
  number, the real file untouched. Stdlib only, `127.0.0.1` only. `viewer/index.html`.
- **Oct 27 (voice-out):** `agent/tts.py` fills the `speak()` seam with ElevenLabs
  (`eleven_v4`), called over the public REST API with stdlib `urllib` — no SDK, no
  new dependency, like every other model client here. Output is text + voice
  together; a `voice_output` receipt stamps the engine, model, voice, and a hash
  of the audio (`rendered: "external"`), so the one non-local, non-Meta part of the
  loop declares itself in the chain. Missing key or failed call → text fallback,
  never a faked voice. Key read from `ELEVENLABS_API_KEY` (`.env.local`, gitignored).
- **Oct 28 (daemon):** `agent/daemon.py` adds Andy's one proactive beat — after a
  task stages something, it surfaces exactly one dismissible suggestion (hold the
  staged item for review) through the existing `speak()` seam. It honors the
  declared speaking policy (`policy.py: SPEAK_WHEN`, `DISMISSAL_SCOPE`): silent
  outside an active task, once per task on the staged trigger only, never about
  people / text fields / off-task, one dismissal silences the session (receipted).
  The suggestion is gated by the policy engine and receipted with its verdict, but
  **never executed** — it is a surface on the loop, not a second actor. Off by
  default (the loop is unchanged without one). `scripts/daemon_acceptance.py`.
- **Oct 28 (talk interface):** the viewer gains a chat pane beside the timeline —
  one local page, same server, same `127.0.0.1`-only binding, stdlib only. A typed
  message (`voice.chat_turn`) runs through the same gate as spoken input, stamped
  honestly as `typed` (never a transcription); the general path is ruled on by the
  policy engine directly, so an off-scope request is blocked and receipted without
  ever running. Andy replies in text + the ElevenLabs voice; the daemon slot
  renders only real suggestions, with a Dismiss button. A one-line launcher,
  `./start-andy.sh`, starts the server, opens the page, and prints the typed-chat
  fallback. `viewer/andy_viewer.py`, `viewer/index.html`, `scripts/chat_acceptance.py`.
- **Oct 28 (hybrid knowledge base):** detect gains a second tier behind the vetted
  eight. **Tier 1** is unchanged and still the only thing that answers. **Tier 2**
  (`agent/tier2.py` over `data/site_index.json`, built by
  `scripts/build_site_index.py` from the public sitemap, date- and URL-count-
  stamped) is index-only — no verdicts, no citations, labels and state from the URL
  path only. It sits behind Tier 1 and can only add a *candidate site page* to a
  **stage**, never turning a stage into an answer: Tybee stages with a candidate to
  check; a place in the index but not Tier 1 stages with its candidate URL and the
  unverified-primary reason; a place in neither tier, or a fictional one, stages
  with no candidate and no invented URL. `scripts/detect_acceptance.py` (two-tier).
- **Oct 28 (verify-on-demand):** Andy can now *earn* knowledge, with proof. On
  "verify it," `agent/verify_source.py` fetches a Tier 2 candidate page and extracts
  its verdict, a **verbatim** rule quote, the named primary, and the date —
  **deterministically, no model**, checking each quote is verbatim and failing
  closed if the structure is missing. The result is staged for the owner's
  approval (`verify_fetch` + `verify_extract` receipts, nothing acted on); on
  "approve" the place becomes a **confirmed secondary** answer that names a primary
  and is labeled not-the-ordinance (`verify_promote` receipt). Wired through the
  chat as `verify`/`approve` intents; a `KnowledgeStore` holds the earned answers.
  The knowledge base grows only by replayable proof. `scripts/verify_acceptance.py`.
- **Oct 28 (Approve/Decline buttons):** the chat pane renders a proposal card with
  all of a pending proposal's evidence and per-place **Approve**/**Decline**
  buttons, which POST the same `approve`/`decline <place>` the typed intents use —
  Decline lands a `verify_decline` receipt and leaves the place staged.
  `scripts/approve_button_acceptance.py`.
- **Oct 28 (persist earned answers):** approved answers now survive a new session,
  written on approve (after the `verify_promote` receipt, atomically) to a separate,
  labeled file `data/confirmed_secondary.json` — loaded on a new session, answered
  with their approval date, **still below Tier 1** and never a primary citation. The
  Tier 1 fixture is never touched; lookup is Tier 1 → persisted secondary → Tier 2;
  a malformed file fails closed with the reason stated; deleting an entry revokes it.
  `scripts/persist_acceptance.py`.
- **Oct 28 (attackable "Try to break it" mode):** the viewer gains a visible panel
  beside the chat with suggested attacks and a free-type input; both go through the
  *same* gate as normal chat (a `demo` flag only removes model spend — no Spark, no
  SAM, voice off — the checker is never skipped). Every suggested attack blocks,
  stages, or is not-shipped; the off-task rule was strengthened to catch "ignore
  your rules" / "pretend you are not gated" (a gate fix, verified against the legit
  controls). A full run costs $0 and runs locally. `scripts/attackable_acceptance.py`.
- **Oct 28 (seeded memory — citable refusals):** a thin citation layer so a refusal
  can read "because the owner said so." When the checker blocks/stages, the chat reply
  may cite a standing-policy line in the owner's words — but only by a deterministic
  category→rule mapping (`agent/policy.py` `cite_for`), never model inference, and
  never changing the verdict; `policy.toml` wins every conflict. The active
  `SEEDED_FACTS` is empty and stays empty until the owner approves lines one by one;
  drafts live in `docs/seeded-memory-draft.md`, which Andy never loads.
  `scripts/seeded_acceptance.py`.

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
