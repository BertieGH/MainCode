# 01 — Project Plan

## 1. Problem statement

CGVAK's outbound motion depends on senior BDEs doing account research, judging whether an account is
worth pursuing, deciding an angle, and writing the message. That work is slow, inconsistent between
reps, and invisible — when a deal lands nobody can say which signal predicted it.

Sales Demand Gen360 industrialises the research-to-strategy half of that motion and leaves the
judgment call with a human. The system produces an evidence-backed recommendation; a rep approves,
edits, or rejects it with a structured reason. Those decisions become training data for targeting.

## 2. Objectives

| # | Objective | How we'll know |
|---|---|---|
| O1 | Research an account faster than a rep can | Time-to-context under 5 minutes per account, unattended |
| O2 | Prioritise accounts consistently | Qualification agrees with a senior BDE's ranking on a held-out set |
| O3 | Recommend a defensible play | A senior BDE agrees with the Strategy on the majority of High-priority accounts |
| O4 | Produce drafts reps actually send | Approve-without-edit rate is the headline metric |
| O5 | Close the loop | Outcomes attach back to the signals and strategy that produced them |

## 3. Scope

### In scope (first build)

- Account ingest and CRM de-duplication
- Parallel research: company, decision-makers, signals
- Evidence store with provenance and a signal lifecycle
- Versioned Account Context
- Six-dimension qualification with a configurable scoring model (MAN retained as a legacy view)
- Strategy agent producing weighted per-persona threads
- Outreach drafts (LinkedIn + email cadence) and Sales Prep artefacts
- Automated evaluation before human review
- Human approval gate with structured rejection reasons
- Execution handoff to La Growth Machine
- Engagement and outcome capture, additive CRM sync
- Learning store (candidate patterns, reviewed before promotion)

### Out of scope (explicitly, from the approach doc)

- Fully autonomous outbound
- Autonomous LinkedIn interaction beyond approved execution
- Automatic strategy changes from small samples
- Fine-tuning before sufficient evaluation data exists
- Reinforcement-learning infrastructure
- Large numbers of independent micro-agents
- Automatic destructive CRM updates

## 4. Milestones

Milestones map onto the five gates in the approach document, plus a foundation milestone.
**A gate is a question a senior BDE can answer honestly about the system** — not a ship date.
Do not start milestone N+1 until gate N passes.

### M0 — Foundation

Repo skeleton, Docker Compose (Postgres, Redis, API, worker, web), Alembic baseline, FastAPI app
with health endpoint, Angular 17 shell with routing and an API service, config asset CRUD
(org profile, ICP, service catalog, proof points, writing samples, sales rules, scoring config).

*Exit:* `docker compose up` gives a running API and UI; config assets can be created and read.
No gate — this is plumbing.

### M1 — Intelligence → *Gate: can the system reliably understand an account?*

Account ingest (single + CSV), CRM dedup, ICP pre-match. Parallel research across three domains.
Evidence store with source, retrieval time, and observation date. Signal extraction into typed,
confidence-scored signals linked to evidence. Signal lifecycle (`discovered → validated → active →
stale → expired`) with per-type TTLs.

*Gate test:* run 20 accounts a BDE knows well. For each, the BDE marks every extracted signal
correct / wrong / missed. Target: no fabricated signals, and the material ones are found.

### M2 — Qualification → *Gate: does it identify worthwhile prospects against a human baseline?*

Context Builder producing a versioned, compressed Account Context. Six-dimension scoring
(Fit, Opportunity, Buyer, Commercial, Intent, Engagement) rolling up to an Opportunity Priority.
Scoring weights and band cut-offs live in a versioned config row, not a prompt. MAN available as
an optional derived view.

*Gate test:* a senior BDE independently ranks 40 accounts into High/Medium/Low. Compare rankings.
Target: strong agreement on the High band, and near-zero High-rated accounts the BDE calls Low.

### M3 — Strategy → *Gate: would a senior BDE agree with the recommended play?*

Strategy Agent: persona × service weighting across every mapped buying-committee member,
problem hypothesis, trigger, positioning, channel, CTA, and an explicit "avoid saying" list.
Thread activation governed by the sales-rules thread cap.

*Gate test:* blind review of 30 strategies. The BDE marks each play "I'd run this" / "wrong angle" /
"wrong person". Target: majority agreement on High-priority accounts, with the wrong-person rate
near zero.

### M4 — Content → *Gate: would the BDE actually use the output?*

Outreach Agent generating the **whole arc of copy** for each active thread — one draft per step of
whichever LGM cadence the campaign selected. Gen360 does not author the cadence itself; touch count
and timing belong to La Growth Machine, and Gen360 fills that sequence's variables.
Evaluation Agent (deterministic rules + LLM semantic checks). Human approval UI with
approve / edit / regenerate / reject and mandatory rejection reasons — all valid **before** the
sequence is enrolled, after which the copy is frozen on the LGM lead.

Also in M4: registering the LGM cadences in Settings and the drift guards around that registration,
since nothing can be enrolled against an unverified mapping.

**Sales Prep has moved out of M4.** It is generated on demand when a call actually exists — see
Phase 12 in [08](08-build-plan.md). Producing it for every thread would be roughly 8× waste, and a
brief written two weeks before a call argues from a picture that predates the conversation.

*Gate test:* approve-without-edit rate on the first 100 drafts. This is the metric that decides
whether the system gets used or shelved.

### M5 — Execution

La Growth Machine adapter: push an approved sequence, receive send status and engagement events
via webhook. Contact verification enforced before any send. Additive, versioned CRM sync via MCP
connector. Multi-thread coordination — a reply on any thread pauses the others pending review.

*No separate gate; folded into gate 5.*

### M6 — Closed loop → *Gate: does the system improve targeting and strategy over time?*

Outcome capture (reply, meeting, opportunity, won/lost) attributed back to signals and strategy.
Learning store recording candidate cross-account patterns. Nothing in the learning store changes
production scoring or strategy without an explicit human review-and-promote step.

*Gate test:* after ~200 outreach threads, the learning store surfaces at least one pattern a BDE
recognises as true and at least one they can refute — evidence the loop measures something real.

## 5. Sequencing note

M1 and M2 can partially overlap: the Context Builder can be stubbed to pass raw signals through
while research is still being tuned. **M3 must not start before gate 2 passes** — a strategy built
on mis-prioritised accounts is untestable, because you cannot tell whether a bad play came from a
bad strategy or a bad account.

## 6. Key risks

| Risk | Impact | Mitigation |
|---|---|---|
| Research fabricates plausible-sounding signals | Fatal — destroys rep trust on day one | Evidence links are mandatory; a signal with no evidence row is rejected at write time, not at review time |
| Contact data quality (bounces, wrong numbers) | Sender reputation damage | Licensed provider only (Apollo.io / ContactOut), verification status stored per contact, unverified contacts blocked from send |
| LinkedIn ToS exposure | Account restriction | No scraping. Enrichment via licensed API; all LinkedIn *actions* go through La Growth Machine's own compliant automation |
| Reps ignore Approvals | System is shelfware | Approve-without-edit rate is the M4 gate; if it is low, fix generation before adding features |
| Stale signals drive live campaigns | Embarrassing outreach | Per-type TTL and lifecycle state; `stale`/`expired` signals cannot be cited by a new strategy |
| LLM cost per account runs away | Budget | Prompt caching on the stable prefix, per-stage effort tuning, Batch API for bulk qualification — see [06](06-llm-integration.md) |
| Scope creep toward autonomy | Governance collapse | The out-of-scope list above is a contract, not a preference |

## 7. Definition of done, per milestone

Every milestone ships with: an Alembic migration, FastAPI routes with Pydantic schemas, an Angular
page wired to real endpoints (no mock data left behind), and the evaluation checks for that stage
from [02 §7](02-architecture.md).


## Implementation sequence

The milestones above describe *what* is built and the gate each must clear. [08 — Build Plan](08-build-plan.md) decomposes them into thirteen phases sized to one working session each, with a context manifest per phase naming exactly which sections to read.

The two are different documents on purpose: milestones are the argument for build order, phases are the unit of work. A gate spans several phases.
