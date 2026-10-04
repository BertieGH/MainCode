# 04 — API Surface

FastAPI, mounted at `/api`. Every router is a module under `app/api/`. Pydantic v2 schemas live in
`app/schemas/`, one module per domain.

Conventions:
- List endpoints accept `?limit=&cursor=` and return `{items: [...], next_cursor: str|null}`.
- Long-running work never blocks a request. Those endpoints return
  `202 {run_id, status: "queued"}` and the client polls `GET /runs/{id}`.
- Mutating endpoints that cross a governance boundary (approve, execute) require an explicit
  `reviewer_id` from the authenticated session — never from the request body.

---

## Health and runs

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + DB/Redis reachability |
| POST | `/runs` | Start a pipeline run: `{account_id \| account_ids[], objective, stages?}` → `202` |
| GET | `/runs/{id}` | Stage, status, token usage, error |
| GET | `/runs` | Recent runs, filterable by account and status |
| POST | `/runs/{id}/cancel` | Cooperative cancel |
| POST | `/runs/{id}/retry` | Retry from the failed stage, reusing prior evidence |

`stages` lets you re-run one stage in isolation (e.g. `["strategy","content"]` after a config
change) without re-paying for research.

## Sorting — shared infrastructure

Every list endpoint accepts `?sort=<field>&dir=asc|desc`. This is **one FastAPI dependency**, not
per-endpoint code, and the field is validated against a per-endpoint **allowlist**.

> Sort fields are never interpolated into SQL. An allowlist maps an external field name to a column
> object; anything not on it is a `422`. A `?sort=` parameter reaching a query builder as raw text is
> an injection hole.

The Angular side is likewise one sortable-header directive with a three-state cycle
(asc → desc → none, where none restores insertion order), applied to every table.

## Account lists

| Method | Path | Purpose |
|---|---|---|
| GET | `/lists` | Labelled import sets with counts |
| POST | `/lists` | Create a list |
| GET | `/lists/{id}` | List detail |
| PATCH | `/lists/{id}` | Rename / re-describe |
| POST | `/lists/{id}/import` | CSV upload → per-row outcome |
| GET | `/lists/{id}/accounts` | Members, sortable |
| POST | `/lists/{id}/accounts` | Add accounts manually |
| DELETE | `/lists/{id}/accounts/{account_id}` | Remove from list |
| GET | `/lists/{id}/targeting` | What the list is worked for, plus `available_icps` |
| PUT | `/lists/{id}/targeting` | Set services and ICPs |
| POST | `/lists/{id}/run-research` | Enqueue research across the list → `202` |
| POST | `/lists/{id}/verify-contacts?service_id=` | Run the enrichment waterfall. **`service_id` required** |
| POST | `/lists/{id}/accounts/remove` | Take `{account_ids[]}` off the list. **Membership only** — accounts are kept |
| POST | `/lists/{id}/run-research` | Optional body `{account_ids[]}` narrows to a selection, still scoped to this list |
| POST | `/lists/{id}/accounts/bulk` | Bulk action over selected ids: `{action, account_ids[]}` where action is `research` / `enrich` / `add_to_queue` / `remove` |

`GET /lists/{id}/accounts` accepts `research_status` and `enrichment_status` filters, plus
`incomplete=true` as a shorthand for "anything that did not finish cleanly" — the single filter a rep
reaches for most often.

Enrichment is never triggered automatically by import or research. It is an explicit action, because
it spends provider credits per lookup — see [03 — `account`](03-data-model.md).

### Targeting

`PUT /lists/{id}/targeting` takes `{service_ids[], icp_profile_ids[]}`, both non-empty. Services are
chosen first; the ICPs must be linked to them. An ICP outside that set is **refused with `422`, not
filtered** — dropping it quietly would leave the list enriching for fewer profiles than the screen
showed, with nothing to say so.

`available_icps` on the response is the set reachable from the chosen services, computed server-side
so the picker cannot drift from the rule the server enforces.

### `verify-contacts`

`service_id` is a required query parameter. Without it the pass ran alphabetically over every
unverified contact, spending a metered provider to find a junior developer's address when the
service needed the CTO — and the list then *looked* enriched.

The service names the ICPs; the list's own targeting narrows them further. A list nobody has
targeted still runs, against every ICP that service sells to — targeting narrows, it does not gate.

| Status | Meaning |
|---|---|
| `200` | Ran. The report carries `checked / verified / risky / not_found / unavailable`, plus `out_of_persona` and `unknown_persona` |
| `409` | `service_not_ready` — that service has no ICP, or its ICPs have no active definition |
| `404` | No such list |

A returned address is **not** automatically verified. Apollo grades its own output and a `guessed`
address is stored `risky`, which does not satisfy the send gate — see [09](09-vocabulary-rework.md).

## Campaign queues

`POST /queues/{id}/members/bulk` takes `{account_ids[], source_list_id?}` and runs on what it can,
returning `{added, already, refused[{account_id, reason}]}`. A locked queue refuses the whole call
with `409`; anything else is per account.

**Queue eligibility is enforced by the server**, in `promotion.add_member`: an account must have a
confirmed identity (`resolution_status = 'resolved'`) and must not be `disqualified`. The single-add
route returns `409` with the reason; the bulk route lists it under `refused`. The account table
greys the action for the same two reasons, so screen and server cannot disagree.

| Method | Path | Purpose |
|---|---|---|
| GET | `/queues` | All queues with status and source labels |
| POST | `/queues` | Create — body carries `{label, members: [{account_id, source_list_id}]}` |
| GET | `/queues/{id}` | Queue detail |
| GET | `/queues/{id}/members` | Members, sortable |
| POST | `/queues/{id}/members` | Add accounts (**draft only** — `409` if locked) |
| DELETE | `/queues/{id}/members/{account_id}` | Remove (**draft only**) |
| POST | `/queues/{id}/clone` | New draft queue with the same members — the way to reuse a locked queue |
| POST | `/queues/{id}/promote` | Create a campaign from this queue and **lock** it |

`POST /queues` takes an explicit member array rather than a filter — the queue is built by copying
what the rep selected, so there is no filter to store and nothing to recompute later.

`POST /queues/{id}/promote` runs the **global thread-cap check** before doing anything. On conflict
it returns `409` with the offending accounts and the campaigns already working them, so the rep sees
the clash at promotion rather than discovering silent skips at send time.

## Outreach campaigns

| Method | Path | Purpose |
|---|---|---|
| GET | `/campaigns` | All campaigns, sortable |
| POST | `/campaigns` | Create from one or more queues — dedups contacts across them |
| GET | `/campaigns/{id}` | Campaign detail |
| GET | `/campaigns/{id}/threads` | Threads with their adapted cadence, sortable |
| PATCH | `/campaigns/{id}` | Label, description, cadence template (**pre-execution only**) |
| GET | `/campaigns/{id}/preflight` | Execution readiness: approvals, contact verification, thread-cap conflicts, no-go screen, send-cap headroom |
| POST | `/campaigns/{id}/execute` | Begin execution — **refused unless every preflight check passes** |
| POST | `/campaigns/{id}/pause` | Pause all threads |
| GET | `/campaigns/{id}/approval` | The two strata: flagged threads with reasons, clean count, drawn sample, sample rate |
| POST | `/campaigns/{id}/approval/redraw` | Draw a fresh random sample — server-side, never client-chosen |
| POST | `/campaigns/{id}/approval/accept-sample` | Approve the sample and accept its stratum; writes `review_depth` per thread |
| GET | `/campaigns/{id}/progress` | Sent / scheduled / awaiting re-approval / skipped counts |

`GET /campaigns/{id}/preflight` returns a per-check verdict rather than a bare boolean, because
"why can't I launch this?" is the question a rep actually has. `POST /execute` re-runs it server-side
and refuses on failure — the UI check is a convenience, not the gate.

## Thread execution

The per-member view: which touches went out, what they said, what came back, what's queued.

| Method | Path | Purpose |
|---|---|---|
| GET | `/threads/{id}` | Thread header: contact, campaign, cadence, progress counts |
| GET | `/threads/{id}/touches` | Every touch with status, timestamps, engagement, and the **content actually sent** |
| GET | `/threads/{id}/adaptation` | Why this thread's cadence differs from the campaign template |
| POST | `/threads/{id}/pause` | Pause this thread only |
| POST | `/touches/{id}/approve` | Approve a single regenerated touch — **pre-enrolment only**; returns `409` once the sequence is enrolled |
| POST | `/touches/{id}/skip` | Skip a touch, with reason |

`GET /threads/{id}/touches` returns, per touch: `status` (`sent` / `scheduled` / `pending` /
`stopped` / `skipped`), sent timestamp, the draft version that was sent, engagement events against
it, and — where the sequence was stopped — `stop_reason`. A rep asking
"what did we actually say to this person, and what's about to go out?" is answered by one call.

## Cadence

| Method | Path | Purpose |
|---|---|---|
| GET | `/cadence-templates` | Library + campaign-local templates |
| POST | `/cadence-templates` | Create |
| PATCH | `/cadence-templates/{id}` | Edit steps |
| POST | `/cadence-templates/{id}/save-to-library` | Promote a campaign-local template to shared |
| GET | `/sequences/{id}/cadence-diff` | Template vs actual, with each deviation's rule, reason, and evidence |

`cadence-diff` is what the Approvals screen renders. A rep approving a thread whose cadence differs
from the campaign template must be able to see *why* without leaving the screen.

## Accounts and contacts

| Method | Path | Purpose |
|---|---|---|
| GET | `/accounts` | Filter by status, priority band, ICP score, country, owner |
| POST | `/accounts` | Create one; runs resolution + dedup synchronously |
| POST | `/accounts/import` | CSV upload → `{created, merged, skipped, rows[]}` with a per-row reason |
| GET | `/accounts/{id}` | Full account record |
| PATCH | `/accounts/{id}` | Manual field correction |
| POST | `/accounts/{id}/disqualify` | `{reason}` — removes from all queues |
| GET | `/accounts/{id}/timeline` | Merged chronological view: signals, touches, engagement, approvals |
| GET | `/accounts/{id}/contacts` | Buying committee |
| POST | `/accounts/{id}/contacts` | Manual contact add |
| PATCH | `/contacts/{id}` | Correct a title, role, or contact detail |
| POST | `/contacts/{id}/verify` | Re-run provider verification |

The import endpoint's per-row reason matters: reps need to know *why* 40 of their 200 rows were
skipped (`duplicate_domain`, `no_go_list`, `icp_below_threshold`, `unresolvable`).

## Evidence and signals

| Method | Path | Purpose |
|---|---|---|
| GET | `/accounts/{id}/evidence` | Raw provenance records |
| GET | `/evidence/{id}` | One record with its source link and excerpt |
| GET | `/accounts/{id}/signals` | Filter by type, lifecycle state, strength |
| GET | `/signals/{id}` | Signal + linked evidence, fully expanded |
| PATCH | `/signals/{id}` | Rep correction: strength, lifecycle state, or mark invalid |
| POST | `/signals/{id}/supersede` | Point to a newer signal |
| POST | `/accounts/{id}/signals/refresh` | Re-scan for new signals without full research |

`PATCH /signals/{id}` writing `lifecycle_state='expired'` is how a rep kills a bad signal. That
correction is itself a learning input.

## Manual intelligence

| Method | Path | Purpose |
|---|---|---|
| POST | `/accounts/{id}/intel/propose` | Free text in → proposed typed signals out. **Proposes only, writes nothing** |
| POST | `/accounts/{id}/intel` | Save confirmed signals + the manual `evidence` row (author, capture method, date) |
| GET | `/accounts/{id}/impact` | What a new signal would change: qualification delta, strategy staleness, affected unsent touches |
| POST | `/accounts/{id}/strategy/rebuild` | Rebuild on the rep's say-so — never automatic |

The split between `propose` and save is deliberate: the proposal step must be free of side effects,
so a rep can discard it. `GET /impact` is what powers the consequence panel — it answers "if I save
this, what becomes stale?" before anything is committed.

## CRM

| Method | Path | Purpose |
|---|---|---|
| POST | `/accounts/{id}/crm/pull` | Read CRM records → `evidence` rows with `source_type='crm'` |
| GET | `/accounts/{id}/crm` | Relationship context: status, prior deals, owner, last activity, last synced |

`crm/pull` runs automatically as the first research step and is also exposed for manual re-sync.

## Context and qualification

| Method | Path | Purpose |
|---|---|---|
| GET | `/accounts/{id}/context` | Latest Account Context |
| GET | `/accounts/{id}/context/versions` | Version history |
| GET | `/context/{id}` | A specific version's payload |
| POST | `/accounts/{id}/context/rebuild` | Force a new version |
| GET | `/accounts/{id}/qualification` | Current scores + per-dimension reasons |
| GET | `/accounts/{id}/qualification/history` | Score movement over time |
| POST | `/accounts/{id}/qualification/rescore` | Recompute with the active `scoring_config` — deterministic, no LLM call |
| POST | `/qualification/rescore-all` | Bulk recompute after a weight change → `202` |

`rescore` being LLM-free is the payoff of keeping the maths in Python: changing a weight and
re-ranking the entire book is seconds and free, not a bill.

## Strategy

| Method | Path | Purpose |
|---|---|---|
| GET | `/accounts/{id}/strategy` | Current strategy + threads |
| GET | `/strategy/{id}/matrix` | Full persona × service weighting, including non-activated rows |
| POST | `/accounts/{id}/strategy/generate` | Generate or regenerate → `202` |
| PATCH | `/strategy-threads/{id}` | Rep override: positioning, CTA, channel, avoid list |
| POST | `/strategy-threads/{id}/activate` | Promote a queued thread (respects the thread cap) |
| POST | `/strategy-threads/{id}/deactivate` | Pause or drop a thread |

## Outreach and sales prep

| Method | Path | Purpose |
|---|---|---|
| GET | `/strategy-threads/{id}/sequence` | Cadence with touches and current drafts |
| POST | `/strategy-threads/{id}/sequence/generate` | Build the cadence and drafts → `202` |
| GET | `/touches/{id}/drafts` | All draft versions for a touch |
| POST | `/touches/{id}/regenerate` | New draft version, optionally `{guidance}`. **Pre-enrolment only** — after enrolment the copy is frozen on the LGM lead, so this returns `409` and the caller must stop and re-enrol |
| PATCH | `/drafts/{id}` | Rep edit — stores `edited_body`, keeps the original |
| GET | `/strategy-threads/{id}/sales-prep` | Pitch, discovery questions, objections |
| POST | `/strategy-threads/{id}/sales-prep/generate` | Generate → `202` |
| POST | `/sales-prep/{id}/export` | `{format: "pptx"\|"docx"\|"pdf"}` → artefact reference |

## Evaluation and approval

| Method | Path | Purpose |
|---|---|---|
| GET | `/evaluations` | Filter by `subject_type`, `verdict` |
| GET | `/evaluations/{subject_type}/{subject_id}` | All checks on one subject |
| POST | `/evaluations/run` | Force re-evaluation of a subject |
| GET | `/sequences/{id}/arc` | All touches with their current drafts — what sequence-level approval reviews |
| POST | `/sequences/{id}/approve` | Approve the whole arc in one action |
| POST | `/sequences/{id}/edit` | `{touch_id, edited_body}` — approves the edited version |
| POST | `/sequences/{id}/reject` | `{reason, comment?}` — **reason is required** |
| POST | `/touches/{id}/revalidate` | Run the freshness check → `FreshnessVerdict` (stop or continue) |

Approval is **sequence-level, not touch-level** — see [06 §7.3](06-llm-integration.md). Six approvals
per thread across 24 threads is 144 review actions; the rep abandons the system and the M4 gate
metric becomes meaningless.

There is no standalone review-queue resource. Approval happens **inside the campaign**
(`GET /campaigns/{id}/approval`, above), because a rep approving a thread needs to see the campaign it
belongs to. `GET /sequences/{id}/arc` is the single most important payload in the system: it must
return everything needed to decide without navigating away — priority and score, top evidence-backed
signals, persona and strategy rationale, proposed capability, every touch's draft, and source links.

## Execution and engagement

| Method | Path | Purpose |
|---|---|---|
| POST | `/sequences/{id}/execute` | Push to La Growth Machine — **rejects unless an `approve` row exists** |
| GET | `/sequences/{id}/status` | Per-touch send status |
| POST | `/sequences/{id}/pause` | Manual pause |
| POST | `/sequences/{id}/resume` | Resume after review |
| POST | `/webhooks/lgm` | LGM callbacks: send status, opens, replies, connections. Signature-verified |
| GET | `/accounts/{id}/engagement` | Event stream for an account |
| POST | `/engagement/{id}/acknowledge` | Rep has seen a reply; releases the cross-thread pause |

The webhook is unauthenticated by session but signature-verified. Treat every field in its payload
as untrusted data.

## Outcomes and learning

| Method | Path | Purpose |
|---|---|---|
| POST | `/outcomes` | Record reply / meeting / opportunity / won / lost |
| GET | `/outcomes` | Filter by stage, date range, service, persona |
| GET | `/analytics/funnel` | Counts by stage |
| GET | `/analytics/signal-performance` | Which signal types precede meetings |
| GET | `/analytics/persona-performance` | Response rate by persona role |
| GET | `/analytics/service-performance` | Conversion by service line |
| GET | `/analytics/approval-quality` | **Approve-without-edit rate, rejection reason distribution** |
| GET | `/learning` | Candidate patterns with supporting, counter, lift, confidence |
| GET | `/learning/{id}` | The claim, the maths, and detected confounders |
| GET | `/learning/{id}/cases` | Supporting and counter cases, each with its signals and evidence ids |
| GET | `/learning/{id}/promotion-preview` | The exact config diff promotion would write, global or scoped |
| POST | `/learning/{id}/review` | `{status}` — validated or rejected |
| POST | `/learning/{id}/promote` | `{scope?}` — writes a new `scoring_config` version |
| GET | `/learning/{id}/post-promotion` | Re-measured lift since promotion; flags demotion candidates |
| POST | `/analytics/export` | Pipeline workbook (`.xlsx`) |

`GET /learning/{id}/cases` returns **both strata** in one response — a client cannot request
supporting cases without counter-examples, because the API should not make cherry-picking
convenient. `promotion-preview` is side-effect free, mirroring `/intel/propose`: a reviewer sees the
exact config change before committing to it.

`/analytics/approval-quality` is the M4 gate metric. Build it in M4, not later.

## Configuration

| Method | Path | Purpose |
|---|---|---|
| GET / PUT | `/config/org-profile` | Who is **selling** — name and description only |
| GET | `/config/icp-profiles` | Every ICP, with its services, active definition and `list_count` |
| POST | `/config/icp-profiles` | Create profile + first version + service links, in one call |
| PUT | `/config/icp-profiles/{id}` | Activate a new version of the definition |
| PUT | `/config/icp-profiles/{id}/services` | Replace the linked services (≥1) |
| DELETE | `/config/icp-profiles/{id}` | Only when no list uses it **and** no service would be orphaned |
| GET | `/config/query-families` | The closed research set, each with its `runner` |
| GET / POST / PATCH / DELETE | `/config/services` | Service catalog |
| GET / POST / PATCH / DELETE | `/config/proof-points` | Proof points; `PATCH` toggles `is_approved` |
| GET / POST / PATCH / DELETE | `/config/writing-samples` | Voice references |
| GET | `/config/sales-rules` | Active rules |
| POST | `/config/sales-rules` | New version (creating a version is the only way to change rules) |
| POST | `/config/sales-rules/{version}/activate` | Switch active version |
| GET / POST | `/config/scoring` | Scoring config versions |
| POST | `/config/scoring/{version}/activate` | Switch, then bulk-rescore |
| GET / PUT | `/config/prompts` | Prompt templates per stage, with named presets |
| GET / PUT | `/config/scoring` | Industry and size multipliers travel with the scoring config. There is no `/config/industries` — the rows are the union of industries across active ICP definitions |
| GET / POST / PATCH / DELETE | `/config/persona-roles` | Buying-role taxonomy and persona weights |

Creating an ICP is **one call**, not three. Created separately, a profile could exist linked to no
service between two requests — a state the model says cannot happen. `POST` therefore takes
`{name, description?, definition, service_codes[]}` and refuses an empty `service_codes`.

`DELETE` returns `409` when an account list points at the profile (its enrichment would stop being
explainable) or when removing it would leave an active service with no ICP at all.
| GET / POST / PATCH / DELETE | `/config/query-families` | Research families, signal mapping, weights, can-create-signal flag |
| POST | `/config/llm` | Add a model scenario |
| POST | `/lists/{id}/import/dry-run` | Column mapping in, per-row outcome out. **Writes nothing** |
| POST | `/lists/{id}/import/commit` | Apply a confirmed dry run |
| POST | `/campaigns/preflight` | Check a proposed campaign **before** creating it — thread cap, dedup, no-go |
| GET | `/config/llm` | Per-scenario model config (model, effort, max tokens, output contract) |
| PATCH | `/config/llm/{scenario}` | Tune one scenario |
| GET | `/config/llm/spend` | Month-to-date spend, cap, per-account average |
| GET | `/config/weights` | Industry and size multipliers, persona-role weights, signal-family weights |
| POST | `/config/weights` | New `scoring_config` version — then offer bulk re-score |
| GET | `/config/credentials` | Provider list with `last_four` and status. **Never returns a full value** |
| PUT | `/config/credentials/{provider}` | Store a credential — write-only, encrypted at rest |
| POST | `/config/credentials/{provider}/test` | Test connection; updates `status` and `last_tested_at` |

`import/dry-run` and `campaigns/preflight` are both side-effect free, matching `/intel/propose` and
`/learning/{id}/promotion-preview`. The pattern is consistent across the system: **anything with a
consequence gets a preview endpoint that writes nothing.**

`GET /config/credentials` returning only `last_four` is a hard rule, not a convenience. A full-value
read endpoint is an exfiltration path, and the research agents consume untrusted web content by
design.

Sales rules and scoring config are **append-only and versioned**. Editing in place would make every
historical qualification and strategy unexplainable.

## CRM

CGVAK's CRM is custom-built. These routes call the `CrmAdapter` interface
([06 §8](06-llm-integration.md)) — their shape does not change once CGVAK's API spec is available;
only the adapter's internals do.

| Method | Path | Purpose |
|---|---|---|
| GET | `/crm/status` | Adapter health — is the custom CRM reachable |
| POST | `/crm/match` | Resolve an account/contact against custom-CRM records |
| POST | `/crm/sync/{account_id}` | Push additive updates (create/append only — no update, no delete) |
| GET | `/crm/sync-log` | Audit of what was written |

Blocked on CGVAK supplying the custom CRM's API spec — see [07 Q2](07-open-questions.md). Until
then, `CrmAdapter` runs against a `StubCrmAdapter` so M1 dedup logic isn't blocked on it.

## Router → milestone map

| Router | Milestone |
|---|---|
| `health`, `config`, sorting dependency | M0 |
| `accounts`, `lists`, `evidence`, `signals`, `runs` | M1 |
| `queues` | M3 |
| `campaigns`, `cadence` | M4 |
| `context`, `qualification` | M2 |
| `strategy` | M3 |
| `outreach`, `sales_prep`, `evaluations`, `review_queue` | M4 |
| `execution`, `engagement`, `webhooks`, `crm` | M5 |
| `outcomes`, `analytics`, `learning` | M6 |


## Cadence registration and drift

| Method | Path | Notes |
|---|---|---|
| GET | `/cadences` | Registered shapes with sync state (`in_sync`, `changed_in_lgm`, `backstop_due`, `unregistered`) |
| POST | `/cadences` | Register a shape — validates the attribute budget, refuses above 10 |
| POST | `/cadences/{id}/verify` | Records a human verification; sets `verified_at` |
| POST | `/cadences/refresh-metadata` | Polls LGM campaign metadata for every shape; updates `lgm_updated_at`, `lgm_channels`, `lgm_status`. Runs hourly on a schedule as well |

Enrolment (`POST /campaigns/{id}/execute`) rejects with `409` when the selected cadence is
`changed_in_lgm` or `backstop_due`, naming the shape and what needs re-checking. It also rejects with
`409` when any contact in the campaign holds a non-terminal sequence elsewhere, returning the
conflicting contacts, the sequence locking each, and its estimated completion — which is what the
pre-flight table renders. It is deliberately a
hard block rather than a warning: a stale mapping sends the wrong words to real people, and there is no
downstream check that would catch it.


## Arc review and execution

| Method | Path | Purpose |
|---|---|---|
| GET | `/campaigns/{id}/threads` | Every thread with persona, selected cadence, draft count, evaluation verdict, review state — the All threads table |
| GET | `/sequences/{id}/arc` | One thread's full arc: each touch with day, channel, target attribute, anchored signal and its evidence, current draft, signal-dependence band |
| PATCH | `/touches/{id}/draft` | Save an in-place edit. **Pre-enrolment only** — `409` afterwards |
| POST | `/sequences/{id}/approve` | Approve the arc; records `review_depth` and, when sampled, the `sample_id` |
| POST | `/sequences/{id}/reject` | `{reason, comment?}` — reason required; triggers sample escalation |
| GET | `/campaigns/{id}/preflight` | The execute checklist, each item with pass/fail and a human-readable reason |
| POST | `/campaigns/{id}/execute` | Writes every approved draft to its LGM lead and starts the campaign |

`POST /campaigns/{id}/execute` is the irreversible one. It rejects with `409` on any failing
pre-flight item, and the response names which — an unapproved thread, a `changed_in_lgm` cadence, an
attribute budget overflow, or a contact holding a live sequence elsewhere. After it succeeds the only
mutating endpoints for that campaign are `/sequences/{id}/stop` and `/campaigns/{id}/stop`.


## Sales Prep

| Method | Path | Purpose |
|---|---|---|
| GET | `/prep` | Contact index — search across all contacts, plus the queue with `why_now`, meeting time, research age, prep status |
| GET | `/prep/{contact_id}` | Context for the brief: current signals, strategy thread, touches sent with engagement, replies, research age |
| POST | `/prep/{contact_id}/research` | Re-run research and enrichment **scoped to this account and contact** → `202` |
| POST | `/prep/{contact_id}/generate` | Generate the brief → `SalesPrepPayload` |
| GET | `/prep/{contact_id}/export/{fmt}` | `pptx` / `docx` / `pdf` via Agent Skills; `409` if no brief exists |

`GET /prep/{contact_id}` returns `research_age_days` and `touches_since_research` so the client can
warn before generation rather than after. Generation is deliberately **one contact per call** — there
is no batch endpoint, because a brief is only worth writing when a specific conversation is scheduled.
