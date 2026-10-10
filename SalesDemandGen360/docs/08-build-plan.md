# 08 — Build Plan

Fourteen phases (0–13), each sized to **one working session**. The sizing is deliberate: a phase that
overflows a context window gets finished by a session that has forgotten why it started, and that is
where invariants get quietly broken.

## How this plan manages context

The specification is ~3,400 lines. No phase needs more than a few hundred of them. Four devices keep
each session small:

**1. Vertical slices, not horizontal layers.** Building "all models, then all services, then all
endpoints" forces every session to hold the whole schema. Building *account lists, end to end* touches
five files and needs one domain. Every phase below is a slice a rep could notice.

**2. A context manifest per phase.** Each phase names exactly which doc sections to read, which files
it creates, and what "done" means. Read the manifest, read those sections, write the code. Nothing
else.

**3. Contracts frozen early.** DDL and Pydantic models land in phases 1–3 and become the reference.
Later phases read `docs/schema/*.sql`, not the design rationale that produced it — the rationale
matters when deciding, not when implementing.

**4. Tests as the acceptance record.** A phase is done when its tests pass. A later session can verify
the previous phase without re-reading its reasoning.

`CLAUDE.md` carries the ten invariants into every session automatically. It is deliberately short —
every line costs context on each load.

---

## Phase sequence

Dependencies run downward. Phases at the same depth can be built in either order.

```
0  Skeleton
│
1  Config domain ─────────────┐
│                             │
2  Accounts & lists           │
│                             │
3  Evidence & signals ────────┤   (schema already written)
│                             │
4  Research pipeline          │
│                             │
5  Context & qualification    │
│                             │
6  Strategy                   │
│                             │
7  Queues & campaigns         │
│                             │
8  Drafting                   │
│                             │
9  Evaluation & approval      │
│                             │
10 Execution — LGM            │
│                             │
11 Engagement & outcomes      │
│                             │
12 Sales Prep                 │
│                             │
13 Learning ──────────────────┘
```

---

### Phase 0 — Skeleton

| | |
|---|---|
| **Read** | `01` (whole, it is short) |
| **Build** | FastAPI app, async SQLAlchemy, Alembic, settings, `/health`. Angular shell with routing and the design tokens from the mockup. Docker compose for Postgres. CI: ruff, mypy, pytest, `ng lint` |
| **Done when** | `docker compose up` serves both, `alembic upgrade head` runs on an empty database, CI is green |

No business logic. The point is that every later phase starts from a working, checked baseline.

### Phase 1 — Config domain

| | |
|---|---|
| **Read** | `03` Domain 1 · `04` config endpoints · `05` Settings screens |
| **Build** | `org_profile`, `service_catalog`, `proof_point`, `writing_sample`, `sales_rules`, `scoring_config`, `llm_config`, `integration_credential`, `signal_type`. CRUD + the Settings UI |
| **Done when** | A config change writes a **new version** rather than mutating; credentials return `last_four` only; deprecating a signal type leaves its rows intact |

First because everything downstream reads it, and because the versioning pattern established here is
copied by every other config surface.

### Phase 2 — Accounts and lists

| | |
|---|---|
| **Read** | `03` Domains 2 and 5b · `05` lists and the sortable contract |
| **Build** | `account`, `contact`, `account_list`, `account_list_member`, `run`. CSV import with column mapping and a dry run. The **shared sortable-table infrastructure** — one backend dependency with a per-endpoint allowlist, one Angular directive |
| **Done when** | Import shows per-row outcome before writing; every list endpoint sorts; a sort param outside the allowlist returns `400`, not a 500 |

Build the sort infrastructure here, before there are eight tables wanting it.

### Phase 3 — Evidence and signals ✅

| | |
|---|---|
| **Read** | `docs/schema/signals.sql` (**the reference — start here**) · `06` §4 structured output |
| **Build** | The four tables as written, the deferred constraint trigger, the `signal_current` view, and the extraction service with its evidence-resolution guard |
| **Done when** | A signal citing a non-existent `evidence_id` is **dropped and logged**, not stored; a contact-scoped type cannot be written without a `contact_id`; one document supports three excerpts without a dedup collision |

The DDL is already written and comment-annotated. This phase is largely translating it and building
the guard around it.

**Built.** `app/models/signal.py`, migration `1a502862c17d` (four tables, the deferred trigger, the
`signal_current` view), `app/schemas/signal.py`, `app/services/extraction.py`, and
`tests/test_extraction_guard.py`. Two deviations from the DDL, both forced by earlier decisions and
recorded in the model docstring: `signal_type` is keyed on a surrogate UUID here, so the composite
FK needed an explicit `UNIQUE (key, scope)`; and `signal_evidence` is a Core table because its
composite primary key is the thing that stops one signal citing the same excerpt twice, which a
`Base`-mandated surrogate id would undo.

Two guards beyond what `docs/08` asked for, both closing holes the stated three would not:
a cited `evidence_id` is resolved **within the account**, so a citation cannot reach another
prospect's documents; and a paused type produces nothing, since a signal written against one would
be invisible in `signal_current` yet still stored.

### Phase 4 — Research pipeline ✅

| | |
|---|---|
| **Read** | `02` research and enrichment · `06` §3 per-stage config, §5 caching |
| **Build** | Query families driven by the registry, CRM adapter (stub), Apollo → ContactOut waterfall, the background worker, coverage-gap reporting |
| **Done when** | CRM is checked **first**; a family returning nothing is reported as a gap; `cache_read_input_tokens` is non-zero across repeated runs |

The caching assertion belongs in a test. A silent cache miss is the most expensive bug in the system
and it is invisible without one.

**Built.** `app/services/crm.py` (interface + stub), `providers.py` (waterfall), `research.py` (plan
and coverage), `prompt.py` (cache-safe assembly), `pipeline.py` (the run), model
`research_coverage` with migration `155733dd2961`, and four test modules.

Two additions beyond what the phase named, both because the stated condition could not otherwise be
met honestly:

* **`research_coverage` is a new table** — `docs/03` defines none. Coverage cannot be derived from
  the evidence rows, because the interesting fact is a negative: "the hiring family ran and found
  nothing" is indistinguishable from "it never ran" and from "the run died halfway" if all three
  leave zero rows.
* **`empty` and `failed` are distinct statuses.** Empty is intelligence; failed is ignorance. Shown
  as the same blank, a rep reads a broken provider as a quiet prospect and walks away from a live
  one.

The caching condition is tested in two layers. Determinism tests run always and free: two
independently built prefixes must be byte-identical, which is what every invalidator §5 names
breaks. The live `cache_read_input_tokens > 0` assertion is marked `llm`, is excluded from the
default run so a plain `pytest` never bills, and skips without `ANTHROPIC_API_KEY`. Run it with
`pytest -m llm` once a key is set.

**Not built here:** the real Apollo and ContactOut HTTP clients, and the real CRM transport. All
three need credentials and a spec (`docs/07 Q2`) that do not exist yet — the interfaces and the
waterfall logic they will plug into are done and tested.

### Phase 5 — Context and qualification ✅

| | |
|---|---|
| **Read** | `03` Domain 4 · `06` qualification · `02` §6 |
| **Build** | `account_context` (versioned), `qualification`, the deterministic scoring service |
| **Done when** | Re-scoring the whole book after a weight change makes **zero LLM calls**; every dimension score carries cited evidence |

**Built.** `app/models/context.py`, migration `3e9d1d92b7b3`,
`app/schemas/qualification.py`, `app/services/scoring.py` (pure), and
`app/services/context.py`, with `tests/test_scoring.py` and
`tests/test_context_builder.py`.

Three decisions worth recording:

* **`docs/02 §6` states the roll-up as `FIT + INTENT + TIMING + ACCESS`.** "Timing" and "access" are
  not among the six dimensions — that line predates the six-dimension model. `scoring_config.
  dimension_weights` is authoritative, and it is validated to hold exactly the six and total 100.
* **Absence is declarable.** A dimension may carry `basis="no_evidence"` with no citations, and it
  is then pinned to a score of 0. Engagement on an account nobody has contacted is a known, correct
  zero — requiring a citation there would push the model to manufacture one, which is the single
  failure mode the whole design exists to prevent. Every other assessment must cite at least one
  evidence id.
* **Multipliers are renormalised back to 100, once.** Without that, an account of a multiplied
  industry outscores an identical account of another purely because its weights add up to more.
  The multipliers change the balance between dimensions, not the size of the result.

The zero-LLM-calls condition is enforced rather than trusted: the re-scoring test replaces the
`anthropic` module with an object that raises on any attribute access, so a single call anywhere
beneath `rescore_book` fails the test. A companion test asserts re-scoring actually moves the
numbers, since a silent no-op would satisfy the first one perfectly.

### Phase 6 — Strategy ✅

| | |
|---|---|
| **Read** | `03` Domain 5 · `06` strategy synthesis |
| **Build** | `strategy`, `strategy_thread`, `persona_service_score`, persona × service weighting |
| **Done when** | Two personas at one account produce genuinely different hypotheses; the thread cap holds; contact signals measurably move persona ranking |

**Built.** `app/models/strategy.py`, migration `df7804e718aa`, `app/services/strategy.py`
(deterministic weighting and selection), `tests/test_strategy.py`.

The weighting is deterministic Python, like scoring and for the same reason: a rep asking why the
CFO was not contacted needs an answer better than "the model felt that way". The LLM writes the
hypothesis and positioning for threads that were selected; it does not choose who is worth
talking to.

Three decisions worth recording:

* **Differentiation is enforced, not hoped for.** `assert_differentiated` rejects two active threads
  at one account carrying the same problem hypothesis, normalised for case and whitespace. Two
  people at one company receiving materially the same message is how an account learns it is being
  automated at, and it is the failure mode multi-threading otherwise invites.
* **`queued` and `not_activated` are distinct.** Above the threshold but beyond the concurrent cap
  is "not yet"; below the threshold is "no". Collapsing them would lose the only record of a
  persona we would pursue given room.
* **Contact signals carry a large weight (25) with decay (0.6).** `docs/02` says evidence about
  someone beats a guess from their title, so the bonus has to be big enough to actually reorder
  against role weights — a small nudge would leave title-ordering intact. The decay stops a noisy
  contact crowding out a better-placed one on volume alone.

Start offsets count **activated** threads rather than rank, so a `not_activated` persona sitting
between two active ones does not silently push the second one's start date out.

### Phase 7 — Queues and campaigns ✅

| | |
|---|---|
| **Read** | `03` Domains 5b and 5c · `02` selection layers and the contact lock |
| **Build** | `campaign_queue` (+ sources, members), `outreach_campaign`, `cadence_shape` registration with drift detection, `lgm_identity` resolution, the **partial unique index** |
| **Done when** | Promoting locks a queue; two concurrent promotions of the same contact — the index, not the service, rejects the second; a `changed_in_lgm` cadence blocks enrolment |

Test the lock with genuine concurrency. An application-level check passes a sequential test and fails
in production.

**Built.** `app/models/campaign.py` (queue, members, campaign, sources, `cadence_shape`,
`lgm_identity`, `outreach_sequence`, `deferred_enrolment`), migration `38222180ce22`,
`app/services/lgm_identity.py`, `cadence.py`, `promotion.py`, and three test modules.

The race test was **verified by removing the index**: without it both concurrent commits succeed
(`['committed', 'committed']`), which is the production bug exactly; with it one is rejected on
`one_active_sequence_per_lgm_identity`. A test that cannot fail proves nothing, so this one was
made to fail on purpose before being trusted.

`promotion.enrol_thread` deliberately does **no pre-check** for an existing sequence. It attempts
the insert inside a SAVEPOINT and catches the unique violation, so a rejection costs one enrolment
rather than the whole promotion. Checking first and inserting second is the race the index exists
to close.

One doc inconsistency resolved: `docs/03` lists `outreach_sequence.status` values without
`stopped`, while the terminal/non-terminal table immediately below it names `stopped` as terminal.
The CHECK includes it — the lock semantics need a terminal state distinct from `completed` and
`cancelled`.

### Phase 8 — Drafting ✅

| | |
|---|---|
| **Read** | `06` §7 arc generation · `03` Domain 6 |
| **Build** | `outreach_sequence`, `touch`, `draft`. Whole-arc generation in one pass, shape selection, signal-dependence banding |
| **Done when** | One call produces the whole arc; a late touch citing a dated signal **fails evaluation**; the attribute budget is validated against the shape |

**Built.** `app/models/content.py` (`touch`, `draft`), migration `ecce41568756`,
`app/schemas/draft.py` (`DraftSet`, `TouchDraft`, `FreshnessVerdict`),
`app/services/drafting.py`, `tests/test_drafting.py`.
(`outreach_sequence` and shape selection landed in Phase 7.)

Decisions worth recording:

* **Banding is by thirds, not by fixed step numbers.** `docs/06` names touches 5–6 as late for a
  6-touch cadence, but hardcoding that would leave touch 8 of an enterprise 8/23 sequence
  unguarded. `band_for_step` scales with `touch_count`.
* **`dated` copy must cite the signal it depends on**, enforced in the schema. Without it the
  pre-send freshness check has nothing to re-validate and the banding guard degrades into a label.
* **`FreshnessVerdict` has no field for replacement copy.** Content is frozen on the LGM lead, so a
  redraft there would differ from what LGM actually sends. Its only outputs are stop or continue.
* **One current draft per touch** is a partial unique index, not a convention. Two current drafts
  means the copy sent is whichever row the query happened to return first.
* **`mark_content_written` refuses on any unmapped step.** Content in our database is not content on
  the LGM lead, and a half-written campaign is invisible until a recipient gets the wrong message.

### Phase 9 — Evaluation and approval ◑ (backend done, arc review screen outstanding)

| | |
|---|---|
| **Read** | `04` approval endpoints · `05` Approval tab and arc review |
| **Build** | `evaluation`, `approval`, stratified sampling, the arc review screen, escalation on rejection |
| **Done when** | Flagged threads are never sampled; the sample is server-drawn and cannot be hand-picked; `review_depth` is recorded; one rejection doubles the sample |

The gate metric depends on this screen being genuinely usable. Budget more time than the table
suggests.

**Built (backend).** `app/models/governance.py` (`evaluation`, `approval`, `approval_sample`),
migration `50d80051ce53`, `app/services/approval.py`, `tests/test_approval_sampling.py`.

**Not built: the arc review screen and the Approval tab.** Frontend work, deferred at the user's
request. Every endpoint-shaped behaviour it needs is done and tested.

Decisions worth recording:

* **The sample is a stored row, not a computed value.** That is what makes "the rep cannot
  hand-pick it" true rather than intended: the drawn ids are written server-side once, and
  `accept_sample` compares what comes back against them. A sample recomputed per request could be
  reshaped by asking again until the answer suited.
* **`draw` has no parameter for chosen ids**, asserted by a test on its signature. It also only ever
  sees `stratum.clean`, which is why a flagged thread cannot be sampled by accident rather than by
  policy.
* **`secrets.SystemRandom`, not `random`.** A draw reproducible from a guessable seed is a draw
  someone can work around.
* **A redraw supersedes rather than mutates.** The record of how hard a campaign was actually looked
  at has to survive a redraw — it is the entire basis for later arguing the sample rate is safe.
* **`sample_size_for` rounds up.** A 10% rate over 4 threads would otherwise round to zero: a sample
  of nothing that reports as a sample.

### Phase 10 — Execution ✅

| | |
|---|---|
| **Read** | `02` LGM sections · `07` L1–L5 |
| **Build** | LGM adapter, attribute writing, enrolment, pre-flight, stop paths |
| **Done when** | Every pre-flight item blocks; a draft edit after enrolment returns `409`; stop-sequence and stop-campaign both work |

**Run the two empirical tests from `07` before this phase**, not during it. Both change the design if
they come back unexpected.

**Built.** `app/models/execution.py` + migration `a2b98a34107a`, `app/services/lgm.py` (adapter +
stub), `preflight.py`, `execution.py`, `tests/test_execution.py`.

**On the two empirical tests: still unrun, and deliberately built around.** Both need a live LGM
account. Neither answer changes what was built:

* *Does campaign `updated_at` move on a body-only edit?* If it does not, the 90-day verification
  backstop is the only guard for that case — which is exactly why the backstop exists and stays
  either way.
* *What happens when an import matches one lead by LinkedIn and another by email?* Either way the
  identity is marked `conflict` and enrolment blocks, because guessing at a documented unknown is
  the thing that corrupts a sequence.

So the design is defensive against both outcomes. Run them before the first real send to raise
confidence, not to unblock.

Decisions worth recording:

* **The outbound interlock is a trigger, not code.** A `sent` execution_record requires a matching
  `decision='approve'` row. It is the one gate the entire system hangs on — if a future code path
  can reach a send by forgetting a check, none of the guards upstream matter. Scoped to `sent` on
  purpose: a `skipped` or `failed` row records that we did *not* send and must stay writable
  without an approval, or the system cannot record correctly refusing.
* **Pre-flight re-runs inside `execute`.** The checklist a rep looked at may be minutes old, and an
  account can be disqualified in between.
* **Every check runs; none short-circuits.** A rep fixing a campaign needs the whole list, not one
  problem per round trip.
* **A stop writes local state even when the provider call fails.** A stop that silently did not
  happen is worse than one that errored: the sequence keeps sending while the UI shows it stopped.
* **The `enrolment_lock` pre-flight check guards a narrower case than it first appears.** Two *live*
  sequences for one identity are unrepresentable — the partial unique index sees to that. What the
  check catches is a not-yet-live sequence while another campaign holds the lock, which without it
  would fail mid-execution and leave the campaign half-enrolled.

### Phase 11 — Engagement and outcomes ⏸ **PENDING — held deliberately**

| | |
|---|---|
| **Read** | `03` Domain 7 · `02` webhooks and CRM sync |
| **Build** | Webhook receiver, `engagement_event`, `outcome`, additive CRM sync, bounce-rate attribution |
| **Done when** | A reply pauses sibling threads; CRM sync only ever appends; bounce rate is attributed to the enrichment provider |

**Held on 2026-09-05.** Not deferred for scope reasons — this phase is blocked on two of the three
open questions in `docs/07`, and building it now would mean guessing at both.

#### What blocks it

| Deliverable | Blocked by | Why guessing is worse than waiting |
|---|---|---|
| Webhook receiver | **Q3** — LGM auth scheme and API tier | The endpoint is signature-verified, and the signature scheme is not published outside LGM's Postman collection. A receiver built against a guessed scheme either rejects real callbacks or, worse, accepts forged ones. |
| `engagement_event` shape | **Q3** — LGM's actual payloads | The event vocabulary (opened / replied / connected / bounced) and its field names come from LGM. Inventing them means a migration on first contact with the real stream. |
| Additive CRM sync | **Q2** — CGVAK's custom CRM API spec | `CrmAdapter` already has no update and no delete, so the *interface* guarantee is settled. What is unknown is the transport, the note format, and whether the CRM accepts appends at all. |
| Bounce-rate attribution | Real sends | Bounce rate comes from LGM's campaign metrics endpoint, attributed back to whichever provider resolved the email (`contact.email_provider`). With zero sends there is nothing to attribute, and the join has never been exercised against real data. |

#### What is *not* blocked, and is already built

Two of this phase's three "done when" conditions have their mechanism in place from earlier phases:

- **A reply pauses sibling threads.** The cross-thread rule is specified in `02 §9`. The pause lever
  itself is `execution.stop_sequence`, built and tested in Phase 10 — what is missing is only the
  trigger that calls it, which is the webhook.
- **CRM sync only ever appends.** Guaranteed structurally: `CrmAdapter` declares
  `find_account`, `contacts_for`, `create_account`, `append_note` and nothing else, asserted by a
  test on its method surface. A future adapter cannot acquire an update path by being careless.

#### What unblocks it

1. An LGM account with API access provisioned, plus the Postman collection or an LGM support
   contact, to settle the auth and signature scheme (**Q3**).
2. CGVAK's CRM API spec (**Q2**).
3. The two empirical LGM tests noted on Phase 10 — worth running in the same session as (1), since
   both need the same account.

Until then this phase stays closed on purpose. `docs/07` Q2 and Q3 are the tracking items; when
either lands, the corresponding row above becomes buildable independently — the webhook receiver
and the CRM sync do not depend on each other.

### Phase 12 — Sales Prep — **BUILT (2026-10-10), minus the queue**

Held from 2026-09-05 to 2026-10-10. Built against design 2; see `docs/13` §111
and §112 for what the real data changed about it.

**What shipped:** the search path, the brief, generation on demand, and the
post-call verdict. The *queue* did not, and could not: it fills from
`meeting_booked` and reply events that arrive through the Phase 11 webhook
receiver, and no event has ever been received. The screen says so in those
words rather than showing an empty list, because "no event can arrive yet" is a
build state and "nobody has replied" is a sales fact.

**Not verified live.** Generation returns a clean 503 while the Gemini quota is
exhausted project-wide. The route, storage, staleness and verdict round-trip
are tested; what the model writes has not been seen.

Not blocked by an external dependency the way Phase 11 is — this one is a sequencing choice. The
`sales_prep` table does not exist, and the phase's centre of gravity is the **prep queue**, which is
driven by `meeting_booked` and positive-reply events. Those events arrive through the webhook
receiver that Phase 11 is waiting on, so a prep queue built now would have nothing to fill it and no
way to test that it fills correctly.

The export half (`pptx` / `docx` / `pdf` via Agent Skills) is genuinely independent and could be
built at any point.


| | |
|---|---|
| **Read** | `05` Sales Prep screens · `06` §7.2 objection frameworks, §6 document generation |
| **Build** | The Sales Prep menu: searchable contact index, the prep queue driven by `meeting_booked` and positive-reply events, the per-contact detail screen with scoped re-research, the manual-intel entry point, and generation. Exports via the `pptx` / `docx` / `pdf` Agent Skills |
| **Done when** | Prep is generated **one contact at a time, on demand** — never in batch and never in advance; a contact with no meeting can still be prepped by search; research age is shown and a stale account warns before generation; the brief includes what was already sent and replied |

**Why this is its own phase and this late.** An earlier draft had Sales Prep inside the content
milestone, generated for every thread alongside the drafts. That is wrong twice over: at 24 threads
and roughly 3 meetings it is about 8× waste, and a brief written on day 0 for a call that happens on
day 18 argues from a picture that predates the entire conversation.

It sits after Phase 11 because the queue is driven by engagement events — a meeting booked, or a reply
asking for a call. The *manual* path (search any contact, generate) only needs Phases 1–6, so if the
queue slips, the search path can ship without it.

**Two behaviours that are easy to miss and carry the value:**

- **Staleness is surfaced before generation, not after.** Research age against the meeting date, plus a
  count of touches sent since. A confident brief built on stale research is worse than no brief.
- **The brief reads the outreach history.** What was already said and what they replied matters more
  for a call than the original signals, and the prompt must be told not to re-argue points the contact
  has already heard and agreed with.

### Phase 13 — Learning ⏸ **PENDING — held deliberately**

**Held on 2026-09-05**, alongside Phase 12, to finish the frontend first.

Learning compares outcomes, and there are none: no campaign has sent, so `outcome` has no rows and
`approval.review_depth` has no `sampled`-versus-`inherited` performance to compare. Candidate
pattern detection over an empty book would produce patterns that are artefacts of the seed data.

The one piece worth building before real data exists is the **promotion flow** — a detected pattern
must never reach live config without human review (`02 §8`). That guard is worth having in place
before the first candidate appears rather than after.


| | |
|---|---|
| **Read** | `03` Domain 8 · `02` learning |
| **Build** | `learning_record`, candidate detection, the promotion flow |
| **Done when** | A candidate cannot be promoted without its counter-examples being opened; promotion writes a **new** `scoring_config` version and never rewrites past decisions |

---

## Gate checks

The milestone gates from `01` map onto phases. They are questions, not ship dates:

| After | Question |
|---|---|
| Phase 4 | Can it reliably understand an account? |
| Phase 5 | Does it identify worthwhile prospects against a human baseline? |
| Phase 6 | Would a senior BDE agree with the recommended play? |
| Phase 9 | **Would the BDE actually use the output?** Measured as approve-without-edit rate on the first 100 drafts |
| Phase 13 | Does it improve targeting over time? |

Phase 9's gate is the one that decides whether the system is adopted or shelved. Everything before it
is a bet on that answer.

## Practical notes

- **One phase per session.** If a phase will not fit, split it at a table boundary and say so — do not
  half-build two.
- **Write the migration first.** The schema is the contract every other file in the phase agrees on.
- **Tests before the UI.** UI work is the easiest to verify by eye and the easiest to get subtly wrong.
- **Update `07`** whenever a phase resolves an open question, and `CLAUDE.md` if a new invariant emerges.
- **Run `mockups/check_ui.py`** after touching the mockup. It exists because the same silent breakage
  happened three times.
