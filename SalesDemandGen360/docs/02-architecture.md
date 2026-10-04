# 02 — Architecture

## 1. Governing principle

> **Claude reasons; the application governs.**

Every business-critical decision point — workflow state, tool permissions, approval state, scoring
weights, evidence records, audit logs, send authorisation — lives in the application and the
database. Claude produces schema-constrained outputs that the application validates, stores, and
acts on. A prompt can never grant a capability the application has not granted.

Two corollaries that shape everything below:

1. **The send capability is unreachable until a rep approves.** Not "the prompt says don't send" —
   the Execution Adapter is a separate service that refuses any sequence whose approval row is
   missing or not `approve`.
2. **Nothing crosses a stage boundary as free text.** Each stage's output is a typed record with a
   schema; the next stage reads that record, not the previous stage's prose.

## 2. Runtime topology

| Service | Runtime | Responsibility |
|---|---|---|
| `web` | Angular 17, nginx | Rep-facing UI |
| `api` | FastAPI (Python 3.12), uvicorn | REST surface, validation, auth, orchestration entry points |
| `worker` | arq + Redis | Long-running pipeline stages (research, qualification, strategy, content) |
| `db` | PostgreSQL 16 + `pgvector` | All state, evidence, and memory embeddings |
| `redis` | Redis 7 | Job queue and short-lived run state |
| `llm` | Anthropic API (external) | Claude reasoning — see [06](06-llm-integration.md) |

Pipeline stages run in the worker, never in a request handler. The API enqueues a `run`, returns
`{run_id, status: "queued"}` immediately, and the UI polls or subscribes for stage transitions.

*Note on the dev fallback:* the RecruitmentIntel project's in-process `fire_and_forget` fallback
(used when Redis is unreachable) is a reasonable pattern to carry over for local dev, but production
must use the worker — a research run is minutes long and will not survive a request lifecycle.

## 3. Pipeline stages

```
                      ┌──────────────────────────────┐
                      │ Input & Account Resolution   │
                      │ list · CRM dedup · ICP match │
                      └──────────────┬───────────────┘
                                     │ parallel fan-out
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
      ┌───────────────┐    ┌───────────────────┐   ┌───────────────┐
      │ Company       │    │ Decision-maker    │   │ Signal scan   │
      │ research      │    │ enrichment        │   │ news/hiring   │
      └───────┬───────┘    └─────────┬─────────┘   └───────┬───────┘
              └──────────────────────┼──────────────────────┘
                                     ▼
                   ┌──────────────────────────────────┐
                   │ Signal Extraction + Evidence     │
                   │ raw → typed signals + provenance │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌──────────────────────────────────┐
                   │ Context Builder (versioned)      │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌──────────────────────────────────┐
                   │ Qualification Engine (6 dims)    │
                   │ → Opportunity Priority           │
                   └──────────────┬───────────────────┘
                                  │ priority ≥ threshold
                                  ▼
                   ┌══════════════════════════════════┐
                   ║ Strategy Agent                   ║
                   ║ persona × service weighting      ║
                   ╚══════════════┬═══════════════════╝
                     ┌────────────┴────────────┐
                     ▼                         ▼
             ┌───────────────┐        ┌────────────────┐
             │ Outreach      │        │ Sales Prep     │
             │ (per thread)  │        │ (per thread)   │
             └───────┬───────┘        └───────┬────────┘
                     └────────────┬───────────┘
                                  ▼
                   ┌──────────────────────────────────┐
                   │ Evaluation Agent (rules + LLM)   │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐
                   ╎ Human Approval Gate              ╎
                   ╎ approve · edit · regen · reject  ╎
                   └╌╌╌╌╌╌╌╌╌╌╌╌╌╌┬╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘
                                  ▼
                   ┌──────────────────────────────────┐
                   │ Execution — La Growth Machine    │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌──────────────────────────────────┐
                   │ Engagement & CRM Sync (additive) │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌──────────────────────────────────┐
                   │ Outcome & Learning ──────────────┼──► back to Context Builder
                   └──────────────────────────────────┘
```

Two governance points, not one: the **Evaluation Agent** is automated and runs before a human ever
sees a draft; the **Human Approval Gate** is the final outbound control. Everything downstream of
Strategy is disposable and regeneratable. Nothing upstream of Strategy is ever silently rewritten.

## 4. Stage contracts

This table is the enforcement spec, not a description. Each row becomes a service-layer assertion.

| Component | Must produce | Must not do |
|---|---|---|
| Research agents | Source-backed facts, people records, confidence-scored contact data | Invent conclusions; assume authority without evidence |
| Signal Extraction | Normalised signal objects with evidence links | Draft outreach |
| Context Builder | A versioned Account Context | Dump the raw research corpus into a prompt |
| Qualification Engine | Dimension scores + per-dimension reasons | Write the sales message |
| Strategy Agent | A Strategy object + hypotheses | Bypass qualification |
| Outreach & Sales Prep | Channel drafts within the approved strategy | Change strategy silently |
| Evaluation Agent | Pass/fail + issues + scores | Override business rules |
| Human Gate | Decision + structured feedback reason | Be bypassable by a prompt |
| Execution Adapter | Send status + engagement events | Modify approved content |
| Learning Layer | Validated learning records | Change production rules without review |

**How "must not" is enforced.** These are not prompt instructions. Concretely:

- Research agents get a tool set containing only `web_search`, `web_fetch`, and the contact-provider
  tool. There is no `create_signal` tool and no send tool in their scope.
- `Signal` rows have a `NOT NULL` relationship to at least one `evidence` row, enforced by a service
  guard on write (a check constraint cannot span the join table, so this is a repository-level
  invariant with a test).
- The Outreach Agent receives the `strategy_thread` record as its input contract; the evaluation
  step re-checks the draft against that record's `positioning`, `cta`, and `avoid_list`, and fails
  the draft on drift.
- `execution_record` insert is gated by a query for an `approval` row with `decision='approve'` on
  the parent sequence. No approval, no insert, no API call to La Growth Machine.

## 5. Evidence and signal model

Every conclusion traces back to a date and a source:

```
Source + Date  →  Evidence  →  Signal  →  Conclusion
(where, when)     (stored,     (typed,     (what Qualification
                  not          confidence   and Strategy use)
                  interpreted)  -scored)
```

Reversible in the UI: click any conclusion and walk it back to the exact evidence it rests on.

**Signal lifecycle.** `discovered → validated → active → stale → expired`. Transitions:

| From → To | Trigger |
|---|---|
| discovered → validated | Evaluation stage confirms evidence linkage and classification |
| validated → active | Signal is fresh (within its type's TTL) and used in the current context version |
| active → stale | TTL elapsed, or a newer signal supersedes it (`superseded_by`) |
| stale → expired | Hard expiry; the signal is retained for audit but cannot be cited |

TTLs are per signal type and live in `sales_rules.signal_ttl_days` — a funding round stays relevant
far longer than a job posting. **A `stale` or `expired` signal cannot be cited as a trigger by a new
strategy.** This is checked at strategy-build time, not at review time.

**Hypothesis tagging.** Generated interpretations (problem hypotheses, persona-fit guesses, inferred
org structure) carry `is_hypothesis = true` in storage and render with distinct styling in the UI.
A hypothesis never silently hardens into a fact.

### 5.0a A provider's verdict is carried, not assumed

Apollo returns *guessed* addresses beside confirmed ones and grades them itself. A guess is a
pattern applied to a name — often right, and when wrong the cost lands on the sending domain's
reputation rather than on the provider.

So `ContactRecord.email_status` carries the provider's own verdict through to the contact row:
`verified` stays verified, `guessed` becomes `risky`, `unavailable`/`bounced` become `invalid`, and
anything unmapped falls to `unverified` with a warning. **Only `verified` satisfies the send gate.**
A risky address stays visible for a rep to judge; it never enrols on its own.

Apollo also answers `200` with a fully-formed `person` for a name it has never seen — echoing back
the request with an `id` and an `organization` resolved from the domain. Neither field is proof of a
match, so a record with no independent evidence of the person is discarded.

### 5.0 CRM is read first, before anything is spent

CRM lookup is the **first** research step, ahead of web research and well ahead of enrichment. The
reason is economic and reputational: an account that is already a customer, or one CGVAK lost on
price eleven months ago, should stop a cold campaign before a single token or enrichment credit is
spent — and before a rep sends a "nice to meet you" opener to a company with an account manager.

CRM findings land as `evidence` with `source_type='crm'` and become ordinary signals. A prior lost
deal is a **Medium-strength `prior_relationship` signal**, not a disqualification by itself; the
rep decides. The Relationship card on Account Overview renders this, with a last-synced timestamp
and a manual re-sync, because CRM data goes stale between runs.

Read-only inbound does not conflict with the additive-write-only outbound rule in §8.5 — those are
different directions. Blocked on the custom CRM API spec ([07 Q2](07-open-questions.md)); built
against `CrmAdapter` with the stub in the meantime, exactly as the dedup path already is.

### 5.1 Industry and size

The same signal means different things at a 20-person startup and a 5,000-person enterprise, and
different things again at an insurer and a design agency. Two axes carry that, and they are
deliberately separate — a SaaS startup is both, and one column could only ever record it as one of
the two things it plainly is. See [09](09-vocabulary-rework.md) for the full history.

**Industry** is the market, and comes from the ICPs. Every industry named by any active ICP
definition gets a multiplier row defaulting to ×1.00 — the **union** across profiles, so the two
lists cannot disagree and nothing is calibrated for a market nobody targets. An industry that stops
being named by any ICP is struck through and kept, never dropped on save: a qualification already
scored under it has to stay explainable. `account.industry` joins to it through
`industry_key` — a normalised form (case-folded, whitespace collapsed), because both sides are free
text and "FinTech" versus "Fintech" would otherwise miss silently.

**Size** is banded from `employee_count`, derived rather than detected:

| Band | Rule |
|---|---|
| `small` | under 50 |
| `mid` | 50–999 |
| `large` | 1,000+ |
| `unknown` | no headcount recorded |

Derived because headcount is a fact already on the row. No classifier, no confidence score, and
nothing stored that could go stale.

Both weighting shifts are **multipliers applied to the active `scoring_config`**, stored alongside
it and versioned with it — not a second scoring system. They compose by multiplying and are
**renormalised once**, so they change the balance between dimensions without inflating the score;
renormalising after each set separately would quietly favour whichever was applied last. An account
whose industry matches no row, or whose band is `unknown`, scores on the base weights — visibly,
rather than on a guess.

`industry_key` is stored on `account`, so a re-run that changes an account's industry is visible in the audit
trail rather than silently changing its score.

*Weighting approach adapted from [ai-sales-team-claude](https://github.com/zubair-trabzada/ai-sales-team-claude)
(MIT) — see [docs/reference](reference/README.md).*

## 6. Qualification model

Six dimensions replace the single MAN score. MAN is retained as a derived, optional view for reps
who still think in it.

| Dimension | Question it answers | Primary inputs |
|---|---|---|
| **Fit** | Is this the kind of company we sell to? | ICP match, firmographics, industry, tech stack |
| **Opportunity** | Is there a problem we can solve? | Signals with a business implication |
| **Buyer** | Can we reach someone who can say yes? | Buying committee map, seniority, contact verification |
| **Commercial** | Can they afford it and is the deal worth it? | Funding, headcount, revenue band, spend proxies |
| **Intent** | Are they showing active interest? | Hiring, tech adoption, content consumption, inbound |
| **Engagement** | Have we already got traction? | Prior outreach, replies, meetings, CRM history |

Roll-up: a weighted average of all six dimensions → **Opportunity Priority**, 0–100 (bands: Low / Medium / High). *(An earlier draft of this line read `FIT + INTENT + TIMING + ACCESS`, from the four-dimension model this table replaced; `scoring_config.dimension_weights` is authoritative and holds exactly the six above, totalling 100.)*
Weights and band cut-offs live in a versioned `scoring_config` row. **The maths is deterministic
Python, not an LLM call** — the LLM produces per-dimension evidence-grounded assessments; the
application computes the score. That keeps the model auditable and swappable, and makes
re-scoring the whole book after a weight change a cheap batch job rather than thousands of LLM calls.

## 7. Evaluation framework

Checked at every handoff, not just before sending. Deterministic checks for rules, schema, and
policy; LLM evaluation for semantic quality.

| Stage | Checked for | Method |
|---|---|---|
| Research | Factual accuracy, source quality, completeness, freshness, duplicate handling | LLM + rules |
| Signals | Correct classification, evidence linkage, confidence, temporal validity | Rules |
| Qualification | Consistency, explainability, alignment with scoring config | Rules |
| Strategy | Evidence-backed reasoning, correct persona, relevant problem, appropriate capability | LLM |
| Outreach | Factual support, personalisation, tone, CTA, compliance, strategic alignment | LLM + rules |
| Execution | Approval state, contact verification, rate limits, delivery status | Rules |
| Outcome | Reply, meeting, opportunity, win/loss, rep feedback | Rules |

Results land in the `evaluation` table with a `verdict` of `pass` / `warn` / `fail`. A `fail` at the
Outreach stage blocks the draft from reaching Approvals and triggers one automatic
regeneration; a second failure surfaces to the rep flagged, rather than silently looping.

## 8. Memory architecture

Three stores, kept separate on purpose. Mixing them makes the system unable to distinguish
"true for CGVAK" from "true for this account" from "true across many deals" — exactly the
distinction Strategy and Qualification depend on.

| Store | Holds | Tables |
|---|---|---|
| **Enterprise Memory** | CGVAK's own facts — services, capabilities, ICP, industries, case studies, proof points, methodology, approved messaging | `org_profile`, `service_catalog`, `proof_point`, `enterprise_memory` |
| **Account Memory** | Per-account history — company facts, people, conversations, previous outreach, objections, responses, opportunities, historical signals | `account_memory`, plus the account-scoped operational tables |
| **Sales Learning** | Cross-account patterns — which signals predict meetings, personas that respond, angles that convert, false-positive signals, service-line performance | `learning_record` |

Retrieval uses `pgvector` embeddings on `enterprise_memory` and `account_memory`. **Sales Learning
is never retrieved into a prompt directly** — a promoted learning changes a config value or a prompt
template through a reviewed change, so its influence is explicit and reversible.

## 8.5 Selection layers — lists, queues, campaigns

Three labelled containers sit between an import and a send. **Every boundary is a copy, not a link**,
and each one is a deliberate human act.

```
Account List ──copy──► Campaign Queue ──copy + lock──► Outreach Campaign
 (import set)          (mutable while draft)          (independent from here on)
```

| Layer | Holds | Mutability |
|---|---|---|
| Account List | Accounts | Grows by import or manual add. No filter, so no sync concept |
| Campaign Queue | Accounts copied from one or more lists | Editable while `draft`; **locked on promotion** |
| Outreach Campaign | Threads (per contact) copied from one or more queues | Independent once created |

**Why copy rather than link.** A live link — where a queue is a saved filter recomputed on read —
looks convenient and fails in four ways: research and drafting fire automatically on accounts nobody
chose (cost); the Approvals inbox fills with drafts the rep never intended, polluting the M4 gate
metric; "which accounts were in the September campaign?" stops being answerable, breaking §12; and an
account dropping out of a filter leaves its **already-running sequences orphaned** — live outreach to
a contact whose membership record says they were never there. Copying costs a manual rebuild and
avoids all four.

To reuse a locked queue, **clone** it into a new draft. Re-opening a locked queue would make "which
version did campaign 2 use?" unanswerable.

**Two guards this design makes load-bearing:**

1. **The thread cap goes global.** With no cross-queue dedup, `max_concurrent_threads` is the only
   thing stopping two campaigns working one account simultaneously. It is enforced across *all*
   campaigns and checked **at promotion**, blocking with the conflict named — a rep can act on that;
   a silent send-time skip is invisible.
2. **A send-time safety interlock** — the one deliberate exception to "nothing flows backward".
   Decoupling is right for convenience syncing, but taken literally it would let a company that
   landed on the no-go list yesterday keep receiving touches. Before each send the Execution Adapter
   re-checks: account not disqualified, not on the no-go list, contact not unsubscribed, email
   verified for email touches. Failure skips the touch. Nothing propagates back to the queue.

## 8.6 Cadence

**Cadence structure belongs to La Growth Machine.** Gen360 does not author, edit, or reorder steps —
it selects one of a small set of pre-built LGM cadences and fills that cadence's variables. Touch
count and timing are LGM's to decide. See *Cadence ownership* below for why, and *Cadence
registration* for how the two systems stay in step.

**Selection, not adaptation.** Because each distinct set of day offsets would need its own LGM
campaign, per-thread variation quantises to shape selection:

| Condition on the account or contact | Shape selected |
|---|---|
| `contact.email_status != 'verified'` | LinkedIn-only 5 / 15d |
| size band `large` | Enterprise 8 / 23d |
| size band `small` | Startup 5 / 11d |
| Medium priority band | Nurture 4 / 21d |
| Otherwise | Standard 6 / 15d |

Selection is deterministic Python reading `sales_rules` — no LLM. The earlier design for
LLM-proposed cadence variation is **dropped**, not deferred: with structure owned by LGM there is
nothing for it to propose.

Full storage: [03 — Domain 5c](03-data-model.md).

**Content, as distinct from structure.** The cadence governs *when and which channel*; the words come
from each thread's own Strategy object, so the same cadence produces different copy per account. The
whole arc is generated up front, approved once at sequence level, and written to the LGM lead at
enrolment — after which it is frozen. See *Content is frozen at enrolment* below.

## 8.7 Manual intelligence

A rep knows things research cannot reach — what was said on a call, who the real gatekeeper is, that
a competitor is already in the building. The system takes this as **first-class evidence**, not as a
side channel.

The entry pattern mirrors everything else in the system: **the human supplies knowledge, the model
proposes structure, the human confirms.** A rep writes plainly; the model returns typed signals with
strength, confidence, business implication, and expiry; the rep unticks what they disagree with. This
keeps signal typing consistent with researched signals — which matters, because the Learning layer
compares signals across accounts and cannot do that if every rep invents their own vocabulary.

Three entry points, one component: account header, contact card, and thread detail. The third is the
valuable one — learning something from a reply is exactly when a rep has new information and is
already on that screen.

**What must not happen:** new signals on an account with an executing campaign **flag, never
rewrite** — and in fact cannot rewrite it, since the copy is already frozen on the LGM lead. A new
signal updates qualification and shapes the *next* campaign; the running sequence is unaffected. The
rep's only lever over it is to stop it. The consequence is shown at the moment of saving:
which of qualification, strategy, and cadence the new signal would change, with the rebuild left as
the rep's decision.

## 9. Multi-thread coordination

An account rarely has one buyer. Strategy weighs every mapped persona and may activate several
threads, capped by `sales_rules.max_concurrent_threads`.

- Thread start times are **offset** so two contacts at the same company are not touched the same day.
- A reply on **any** thread is visible across the account — the rep sees one account, not per-persona
  silos — and **pauses the other threads' next touch** pending review.
- The thread cap is a sales rule enforced by the application, not a per-agent judgment call.

## 10. Integration boundaries

| Integration | Direction | Mechanism | Notes |
|---|---|---|---|
| Apollo.io + ContactOut | Read | Two-provider enrichment waterfall, each an HTTP client wrapped as a Claude tool | No off-the-shelf connector for either — custom code. Apollo primary, ContactOut fallback / LinkedIn-first — see [06 §9.2](06-llm-integration.md) |
| Web research | Read | Anthropic server-side `web_search` / `web_fetch` | Runs on Anthropic infrastructure; domain allow/block lists configurable |
| La Growth Machine | Write + webhook | Custom REST adapter against LGM's Postman-documented API (LGM also offers its own MCP server — evaluate for a later swap) | The **only** component with send capability; post-approval only — see [06 §9.1](06-llm-integration.md) |
| CRM — custom (CGVAK-internal) | Read + write | `CrmAdapter` interface, one implementation calling CGVAK's internal API directly; not exposed to the LLM at all | Writes are create/append only — the interface has no update or delete method. Blocked on CGVAK's API spec — see [06 §8](06-llm-integration.md), [07 Q2](07-open-questions.md) |
| Document generation | Write | Agent Skills (`pptx`, `docx`, `xlsx`, `pdf`) | Sales Prep artefacts — the one standard, pre-built piece of this integration list — see [06 §12](06-llm-integration.md) |

## 11. Guardrails

| Concern | Handling | Risk if skipped |
|---|---|---|
| Sending without review | Every draft stops at the human gate; the LGM send tool is reachable only after a rep confirms | Off-brand or wrong-target message goes out |
| Least-privilege tools | Research and Strategy agents have no send permission; only the Execution Adapter reaches LGM, post-approval | An upstream agent bypasses governance entirely |
| Contact verification | Enriched emails and phones are checked before use; unverified contacts are flagged, not contacted | Bounce rate and wrong-number calls damage sender reputation |
| LinkedIn scraping | Enrichment via official APIs / Sales Navigator exports; LinkedIn actions run through LGM's compliant automation | Account restriction, ToS violation |
| Contact data sourcing | Licensed provider only | Privacy complaint, provider terms violation |
| Stale signals | Expiration policy + lifecycle state; stale signals cannot drive a new campaign | Outreach built on a trigger that no longer applies |
| Hypothesis vs fact | `is_hypothesis` flag in storage and distinct rendering in the UI | A guess gets repeated as confirmed fact |
| Outreach rate limits | Cadence timing from sales rules; LGM enforces per-day send/connect caps | Spam flags, deliverability drop |
| CRM write conflicts | Additive, versioned writes | Loses a rep's manual context |
| Multi-thread coordination | Cross-thread reply visibility + pause; thread cap is a sales rule | Contacts compare notes and the account feels spammed |

## 11.4 Capabilities are gated independently

Three provider slots — `llm`, `enrichment`, `outreach` — and they fail for unrelated reasons. A
missing La Growth Machine key means nothing can *send*; it says nothing about whether Apollo can be
called or a CSV imported.

So the gate is per capability. `requires("enrichment")` on a route means that provider, not the
whole installation. Two readiness answers exist and they are not interchangeable:

| | slots | used for |
|---|---|---|
| `readiness.workable` | llm + enrichment | **What the menu locks on.** Enough to do research and enrichment work |
| `readiness.ready` | all three | The whole-installation answer, required only on the send path |

The earlier design had one flag for all three, which meant an installation with a perfectly good
Anthropic key and Apollo credits could not import a list, and the screen gave no way to tell which
of the three was at fault. A "browse anyway" escape existed precisely because the gate was too
coarse — the fix was to make the gate right, not to make the escape easier.

## 11.5 Learning is gated like everything else

The Learning layer is the last place a conclusion could enter production without evidence, and the
highest-leverage one — a promoted pattern changes the scoring of every future account, not one
message to one person.

So the same gate applies: **a pattern cannot be promoted without the reviewer being able to open the
cases behind it.** The UI enforces this by making the drill-through the primary content of the
pattern screen rather than an optional detail — supporting cases, counter-examples, and the evidence
chips that lead to source excerpts.

| Guard | Why |
|---|---|
| Counter-examples shown alongside supporting cases | A pattern without its failures is cherry-picking |
| Confounder detection (industry, size, persona, cadence concentration) | Stops an industry or size effect being promoted as a signal effect |
| Scoped promotion | A SaaS-derived finding can be applied to SaaS only |
| Promotion writes a new `scoring_config` version | Reversible, and historical qualifications keep their own version |
| Post-promotion re-measurement | A promoted pattern that stops holding becomes a demotion candidate |

This closes the one gap in [§12](#12-auditability): every conclusion in the system, including the
statistical ones, answers "what is this based on?" from the database alone.

## 12. Auditability

Every state transition writes to `audit_log` with actor type (`agent` / `user` / `system`), actor id,
subject, and before/after payloads. Three questions must be answerable from the database alone, with
no log-grepping:

1. Why was this account prioritised? → `qualification.reasons` → `signal` → `evidence`
2. Why did we say this to this person? → `draft` → `strategy_thread` → `signal` → `evidence`
3. Who approved it, and did they change anything? → `approval` (+ `edited_body`)


## Cadence ownership — settled with La Growth Machine

**LGM owns the cadence. We own the words.** Confirmed with LGM support, and it is not a preference —
a cadence step **cannot pull content from an external system at execution time**. Webhooks are event
notifications, not content providers. So content must exist on the lead *before* the campaign runs,
which makes "generate the whole arc up front" mandatory rather than a design choice.

### The mechanism

Each step in the LGM sequence inserts a variable — `{{custom_attribute_N}}` — that we fill per lead
before enrolment. Cadence structure and timing live in LGM; per-touch copy comes from that thread's
Strategy object.

### Three consequences

**1. Ten attributes per lead is a hard cap.** A six-touch mixed cadence lands exactly on it, so email
*subjects* use LGM's native variables (`{{firstname}}`, `{{companyname}}`) with per-shape templates,
and our attributes are spent on bodies. That trades some subject-line personalisation for headroom.

We deliberately do **not** rotate a small pool of attributes to dodge the cap. Compare failure modes:
with one attribute per touch, a failed rewrite sends the *original human-approved* content — stale but
valid. With rotation, a failed rewrite sends **touch 1's message again as touch 4** — visibly broken to
the recipient. Safety beats capacity.

**2. Adaptation quantises to fixed shapes.** Continuous per-thread variation is not expressible, because
each distinct set of day offsets would need its own LGM campaign. Layer 2 rules change from *"stretch
×1.5"* to *"select the Enterprise shape"*:

| Shape | Selected when |
|---|---|
| Standard 6 / 15d | default |
| LinkedIn-only 5 / 15d | email unverified |
| Enterprise 8 / 23d | size band `large` |
| Startup 5 / 11d | size band `small` |
| Nurture 4 / 21d | medium priority |

Shapes are built and edited **in LGM**. Gen360 does not author cadences and cannot add, remove, or
reorder a step — it adopts whichever cadence a campaign selects and fills that cadence's variables.
Touch count and timing are LGM's to decide.

LGM can also create campaigns programmatically via its MCP server, but for five or six fixed shapes
that is an integration dependency without a payoff — and a hand-built sequence has been looked at by
a person.

**3. Content is frozen at enrolment — this is the biggest constraint in the build.**

All of a thread's attributes are written to the LGM lead **before the campaign starts**, in one batch.
LGM's own guidance is to fill the attributes before the campaign runs. A lead-update path appears to
exist, but it is not usable for timed mid-flight rewrites: LGM exposes neither the scheduled send time
per step nor whether a step reads its attribute at step start or at send. Writing into an unverifiable
window is not something to build a send path on.

**Once a campaign is in motion, the words cannot change.** A new signal, a manual note, a rebuilt
strategy — none of it reaches a sequence already running. The only reliable in-flight control is
**stop**: pause or remove the lead so the remaining touches never fire.

Two rules follow, and both are enforced at generation rather than left to chance:

| Rule | Why |
|---|---|
| Early touches may anchor to signals; **late touches must not** | Touch 6 is written on day 0 and sends on day 15. "12 open roles right now" may be false by then. Late touches use durable framing — capability, proof points, a soft close — so they cannot go stale. Enforced in the drafting prompt, checked by evaluation |
| An expiring signal **stops** the sequence, it does not rewrite it | Sending known-stale copy is worse than sending nothing. The thread returns to the rep |

To change the words at all, a thread must be **stopped and re-enrolled** — a new enrolment writes a
fresh set of attributes. That is a new sequence from touch 1, not a resume.

This also raises the stakes on the approval gate: since content cannot be corrected after enrolment,
approval is genuinely the last point of human control. The sampling design in [05](05-frontend-spec.md)
should be read with that in mind.

### What the Execution Adapter actually does

Not "send this message". Its job is: write attributes → enrol the lead in the right shape's campaign →
manage lead status (pause, resume, remove) → consume engagement webhooks. It remains the only
component with send capability, reachable only after approval.


## Cadence registration — the contract between the two systems

Because LGM owns the cadence and Gen360 owns the words, something has to record **which
`custom_attribute_N` each LGM step reads**. That mapping is the `cadence_shape` registration, and it
is the most fragile joint in the system.

LGM's API does not appear to expose sequence structure, so registration is manual: someone records the
LGM campaign id and its ordered steps in Settings → LGM cadences.

### Drift is the failure mode

If a sequence is edited in LGM — a step added, channels reordered — and the registration is not
updated, Gen360 writes copy into the wrong slots. **Touch 3's message lands in touch 4's step, and
neither system raises an error.** The first sign is a recipient receiving something that does not follow.

LGM has confirmed the API **cannot read sequence structure** — no steps, shapes, or message templates.
It *can* read campaign metadata and performance metrics. That is enough to turn a blind expiry timer
into a change detector.

#### Checked automatically, hourly, from campaign metadata

| Check | Catches |
|---|---|
| Campaign `updated_at` vs registration `verified_at` | Any change to the LGM campaign after our last verification — blocks enrolment the same day rather than up to 90 days later |
| Declared `channels` vs registered channels | The coarsest structural drift: a channel added or removed |
| Campaign `status` | A paused or archived LGM campaign that cannot accept enrolments |

#### Still requires a person

Step order, day offsets, and — most importantly — **which attribute each step reads**. A reordered
sequence has identical metadata, so only a human comparison catches it. The part of the mapping that
matters most is exactly the part the API cannot confirm.

A **90-day backstop expiry** remains alongside the change detector, because `updated_at` is not
confirmed to move when only a sequence body is edited. The detector is the primary guard; the timer is
insurance against it being blind to body-only edits.

| Guard | Behaviour |
|---|---|
| Change detected | Enrolment blocked immediately; registration marked *Changed in LGM* |
| Backstop expiry | Enrolment blocked after 90 days without verification, even if nothing appears to have changed |
| Attribute budget | Registration refused above 10 attributes rather than silently dropping a step |
| Unregistered fallback | A selection rule pointing at an unregistered shape falls back to default and warns |

### What Gen360 may and may not decide

| | Owner |
|---|---|
| Touch count, day offsets, channel per step | **LGM** |
| Which registered cadence a campaign uses | Gen360 — via the selection rule |
| The words in each touch | Gen360 |
| Whether a touch may cite a dated signal | Gen360 — **derived** from the cadence's span, not chosen |

That last row matters: the durable-only cutoff is a function of how far ahead a touch is written, so it
falls out of LGM's timing rather than being set independently. A 21-day nurture cadence pushes the
cutoff earlier than a 11-day sprint.

Gen360's touch-performance analytics remain useful here, but only as **evidence a human carries back
to LGM**. If touch 6 earns 3%, that is an argument for shortening the sequence in LGM — not something
Gen360 can act on itself.


## A second use for LGM's metrics: enrichment quality

LGM's campaign metrics expose **bounce rate**, which our own webhook stream does not reliably provide.
That makes it the only honest read on enrichment quality — a bounce means an address a provider marked
deliverable was not.

Attributed back to the provider and verification status that produced each address, it answers a
question nothing else in the system can: *are Apollo's "verified" emails actually verified?* Early
shape of the data supports the existing rule — risky-status addresses bounce several times more often
than verified ones, which is why Sales Rules forbids emailing anything but `verified`.

This feeds the Learning layer as a provider-quality pattern, and it matters beyond one campaign:
bounces damage sender reputation for every campaign that follows.


## One campaign per contact — a hard constraint, not a policy

LGM has confirmed custom attributes are stored **on the lead profile, shared across the account** —
not scoped per campaign. A lead has one `CustomAttribute1`, and every campaign that lead is in reads
the same value.

So enrolling a contact in a second campaign **overwrites the copy the first campaign is still sending**.
Mid-sequence, the remaining touches change subject to a different angle, referencing a conversation that
never happened. Nothing errors in either system. The only person who finds out is the recipient.

### Why LGM's two suggested workarounds don't apply

| Their suggestion | Why it fails here |
|---|---|
| Use different attributes per campaign | Our standard cadence uses 6 of 10. Two concurrent campaigns need 12. And campaign A's step 1 reading `attr_1` while campaign B's reads `attr_7` multiplies the registration-drift problem |
| Update the attribute before each campaign runs | That is the mid-flight rewrite ruled out by L1/L2 — and rewriting while campaign A still runs corrupts A. It only works sequentially, which is the constraint restated |

### The guard, and why account-level was not enough

The pre-existing check was the **per-account thread cap**. That is insufficient, because the cap counts
threads on an account while the collision happens on a *contact*:

| Situation | Threads on account | Within cap of 2? | Collision? |
|---|---|---|---|
| Dana in campaign A, Marcus in campaign B | 2 | Yes | No — different leads |
| **Dana in campaign A, Dana in campaign B** | **2** | **Yes** | **Yes — same lead** |

The second row passes the account cap and still corrupts. So a **contact-level enrolment lock** is
required alongside it: a contact may hold at most one non-terminal sequence at a time.

Multi-threading within an account is unaffected — Dana and Marcus are different LGM leads with
different attribute sets, so the persona multi-threading in the Strategy layer still works as designed.

### Re-enrolment is ordered

Because the rewrite overwrites, changing a thread's copy must run in this order, and the order is
enforced rather than advised:

1. Stop the current sequence
2. Confirm it is terminal — no unsent touches remain queued in LGM
3. Write the new attribute values
4. Re-enrol

Doing 3 before 2 corrupts the sequence still running.

### Edge case worth handling in dedup

If LGM deduplicates leads by email or LinkedIn URL, one *person* is one lead even across two accounts.
A contact who appears at two companies in our book would collide despite being two `contact` rows to
us. The dedup logic should match on the same keys LGM does, not only on `account_id` + name.


## Two things LGM does that change our capacity and safety assumptions

### Daily action limits are shared per sending identity, not per campaign

LGM confirmed that concurrent campaigns **share the sending identity's daily action limits**, and the
platform distributes actions between them. Throughput is therefore **not additive**: running three
campaigns does not triple daily sends, it splits one allowance three ways.

The practical consequences:

- Capacity planning is per **sending identity**, not per campaign. The Dashboard's send-capacity bars
  are correctly drawn as one allowance, and every executing campaign draws from it.
- Launching a second campaign silently slows the first. Nothing errors — touches simply queue and roll
  to later days, stretching a 15-day cadence past 15 days.
- Adding sending identities, not campaigns, is what raises throughput.

Because LGM decides the split, a campaign's real elapsed span is not knowable from its cadence alone.
Progress must be read from actual send events rather than projected from day offsets.

### LGM stops a lead across campaigns on reply or opt-out

If a lead replies or opts out in one campaign, LGM halts automation for that lead in **every** campaign
under the same sending identity. That is a genuine safety net beneath our own rules — even if our
contact lock were bypassed, a reply would stop the rest.

It is not a replacement for our rule, because the scopes differ:

| Rule | Scope | Purpose |
|---|---|---|
| LGM's | The **same lead**, across campaigns on one identity | Stops contradicting yourself to one person |
| Ours | **Other contacts at the same account** | Stops the account being worked while a conversation is live |

Ours is the wider net and the one that protects the account relationship; LGM's protects the
individual. Both are wanted, and neither makes the other redundant.


## Evidence storage — a split, not a choice

Research retrieves whole documents; the system keeps three things from each, in three different places,
for three different reasons.

| What | Where | Why there |
|---|---|---|
| Metadata — source, url, title, dates, reliability | Postgres row | Queried constantly; tiny |
| **Excerpt** — the passage a claim rests on | Postgres row | What a signal cites, what the UI shows, what a rep reads |
| Compressed original | Object storage, via `raw_ref` | Needed rarely, large, and must not touch the query path |

The document is never stored in Postgres and never re-enters a prompt after extraction. Context
assembly reads **signals**, not evidence, so the only component that ever sees a full document is the
extraction call that created the signals in the first place.

That ordering is what makes the cost model work: research is the expensive stage and it runs once per
account, while everything downstream operates on a few hundred words per signal.
