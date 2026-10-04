# 07 — Open Questions

Decisions needed before M0 starts, or shortly after. Each has a recommended default so work is not
blocked — but the ones marked **blocking** change the shape of the build if answered differently.

## Resolved (2026-09-03)

### Q1 — Claude Agent SDK or Claude API? ✅ Claude API
CGVAK confirmed no standardisation reason to use the Agent SDK. Building on the Claude API +
`anthropic` Python SDK, Tool Runner for the research stage only. See [06 §1](06-llm-integration.md).
Not open any further.

### Q4 — Apollo.io or ContactOut? ✅ Both, as a waterfall
Not an either/or — CGVAK confirmed Apollo and ContactOut are both for enrichment (LGM handles
outreach separately). Built as a two-provider waterfall: ContactOut first when a LinkedIn URL is
already known (the usual case — the buying committee map starts from LinkedIn), Apollo for
name+domain lookups and org-chart mapping. `contact.email_provider` / `phone_provider` track which
provider resolved which field, independently. Full logic in
[06 §9.2](06-llm-integration.md#92-apolloio--contactout--enrichment-waterfall).

**Follow-up, not blocking:** get both providers under contract before M1 enrichment testing —
Apollo needs the Professional plan or above for API access; ContactOut's API requires a Team/API
plan (~$2k–4k/yr) and a sales call to provision a key. Neither is instant.

## Blocking

### Q2 — Custom CRM API spec **(blocking for M5, shapes M1)**
CGVAK confirmed the CRM is custom-built, not HubSpot/Salesforce/other. The `CrmAdapter` interface in
[06 §8](06-llm-integration.md) is written and stable regardless of the answer, and
`StubCrmAdapter` unblocks M1 dedup work in the meantime — but the real
`CustomCrmAdapter` implementation cannot be written until CGVAK supplies: the API's base URL and
auth scheme, the shape of an account/contact/activity/note record, and whether it exposes anything
resembling a dedup/search endpoint (needed for M1's CRM-match step) or only CRUD by id.

*Needed:* the custom CRM's API documentation or an engineering contact who can produce it.

*Currently holding:* **Phase 11's additive CRM sync is paused on this.** The append-only *guarantee*
is already structural — `CrmAdapter` declares no update and no delete, asserted by a test on its
method surface — so what is missing is only the transport and the note format. See `docs/08`
Phase 11.

### Q3 — La Growth Machine: auth scheme + provisioning **(blocking for M5)**
Largely de-risked — LGM publishes a documented REST API (Postman collection) and its own MCP server
with explicit Claude support, so programmatic campaign creation and webhook delivery are confirmed
to exist (see [06 §9.1](06-llm-integration.md#91-la-growth-machine--outreach-execution-domain-7s-execution_record)).
What's still open: the specific auth header/scheme (not published outside the Postman collection),
API access tier on CGVAK's LGM account, and which of the two build options (custom REST wrapper vs.
LGM's native MCP server) to commit to.

*Needed:* an LGM account with API access provisioned, and the Postman collection or LGM support
contact to confirm auth before M5 starts.

*Currently holding:* **Phase 11 is paused on this** — the webhook receiver is signature-verified and
the scheme is unpublished, and `engagement_event`'s vocabulary comes from LGM's real payloads.
Building either against a guess means a migration on first contact with the live stream, or a
receiver that accepts forged callbacks. See `docs/08` Phase 11.

## Important, non-blocking

### Q5 — What is actually in the service catalog?
The approach doc uses EIA and "Service B" as placeholders. Strategy quality depends entirely on the
real catalog: each service needs its positioning angles, target personas, and approved proof points
with numbers. This is the single highest-leverage input the system takes.

*Needed by:* M3. Gather during M1/M2 — it is a content task, not an engineering one, and it will
take longer than expected.

### Q6 — Who are the reps, and how many accounts per week?
Volume determines whether Approvals needs assignment and ownership, or whether one shared
queue suffices. It also sets the cost envelope (~$2/account in Claude spend, plus per-lookup
Apollo/ContactOut credits on top — see [06 §10](06-llm-integration.md)).

*Recommended default:* single shared queue for the first build; add ownership only when a second
rep joins.

### Q7 — Is there a labelled baseline for the M2 gate?
Gate 2 needs a senior BDE to rank ~40 accounts independently. That has to be scheduled with a real
person, not assumed. Same for gate 3 (30 strategies) and gate 1 (20 accounts of signal review).

*Needed:* commitment of roughly a day of a senior BDE's time per gate.

### Q8 — Geography and compliance scope
GDPR changes what may be stored about EU contacts and what disclosures outbound email requires.
`sales_rules.compliance` has a slot for it, but the rules themselves need stating.

*Recommended:* confirm target geographies in M0; if EU is in scope, the compliance rules must exist
before M4, not M5.

### Q9 — Auth and multi-user
No authentication is specified anywhere in the approach doc. `approval.reviewer_id` implies user
identity exists.

*Recommended:* single-tenant with simple session auth for the first build. Do not build SSO or RBAC
until a second team uses it — but do populate `reviewer_id` from day one so the audit trail is real.

### Q10 — Naming: product vs engine
The repo is `SalesDemandGen360`; the approach doc calls the system "Prospect Engine".

*Recommended:* Sales Demand Gen360 as the product, Prospect Engine as the internal engine name.
Pick one for the UI header before M4 and stop mentioning the other.

### Q11 — Should "Proposal" be a fourth Sales Prep artifact?
Sales Prep currently produces a pitch deck, a call brief, and their exports. An 11-section client
proposal (cover, executive summary, situation analysis, proposed solution, scope of work, timeline,
tiered investment, ROI projection, team, case studies, next steps) would generate from the same
Strategy object and reuse the `docx`/`pdf` skills already wired.

*Shown in the mockup* on the Sales Prep tab, marked as proposed-not-scoped, so the decision can be
made by looking at it. Adds roughly a milestone-quarter of M4 scope if adopted; skipping it costs
nothing else.

*Recommended:* defer to after gate 4. A proposal matters at a later deal stage than the one this
system's gate metric measures, and M4 should not grow before approve-without-edit rate is known.

### Q12 — Should query families be editable at runtime? ✅ Yes, but not yet — and versioned

**Decided 2026-09-05.** Today the families are a closed set in
`backend/app/services/query_families.py`, served read-only at `GET /api/config/query-families` and
rendered read-only on `/settings/research`. That stays true until the research agents exist.

**Why closed, today.** A family name no agent actually runs is indistinguishable from one that ran
and found nothing — both produce zero evidence rows. A typo would report forever as a coverage gap
on a prospect who is perfectly well covered, and the rep would read a broken pipeline as a quiet
market. This is the same reason `signal_type.produced_by` is a checkbox picker rather than free
text, and why the API validates it against the registry.

**What is agreed for when it opens up.**

*1. A used family can never be deleted.* "Used" is exactly two references, both countable:

| Reference | Meaning |
|---|---|
| `signal_type.produced_by` | a signal type claims it as a producer |
| `research_coverage.family` | it actually ran against an account |

`usage_count = 0` → delete; `> 0` → deprecate. The same guard already built and tested for signal
types (`signal_count`) and account lists (`account_count`). Deleting a family that has run would
orphan every coverage row that names it, and coverage rows are the only record that a gap was a
gap rather than an oversight.

*2. Per-family status, not set-versioning.* There are two config patterns in the system —
versioned singletons (`scoring_config`, `sales_rules`, `org_profile`, where you activate the whole
object) and registries of individually-managed rows (`signal_type`, with its own
active/paused/deprecated lifecycle). Families are a registry. Versioning the whole *set* would
force every `research_coverage` row and every `produced_by` entry to carry a set-version
reference, to answer a question nobody asks: the question is always "did hiring run for this
account and what did it find", never "which version of the family set was active".

*3. A change to a used family's definition must be a new version, not an edit.* This is the part
that matters for traceability and it is not the same as deletion. A family's fields are a **prompt
fragment** — they tell the research agent what to look for. Editing `hiring` from "open roles" to
"open roles and layoffs" silently changes what every future coverage row means, while the rows
recorded before the edit still say `hiring`. The gap report stops being interpretable and nothing
errors.

So on a **used** family, these fields are immutable in place and a change writes a new definition
version:

| Field | Versioned? | Why |
|---|---|---|
| `key` | **Never changes** | It is the value stored in `produced_by` arrays and `research_coverage.family`. Renaming orphans both. |
| `scopes` | **Versioned** | Changing which scope a family serves changes which signal types may legally claim it. |
| `description` ("looks for") | **Versioned** | It is the instruction the agent runs on. This is the silent one. |
| `support_only` | **Versioned** | Flipping it changes whether a type producible only by this family can ever fire. |
| *feeds* | **Not versioned — derived** | "Feeds" is computed from `signal_type.produced_by`; it is not a column on the family. It changes when a *signal type* changes, and is traced there, not here. |

`research_coverage` gains a `query_family_version_id`, so a coverage row records the definition
that actually ran — the same reasoning as `scoring_config_version` on a qualification, and for the
same reason: "why is last month's number different from this month's" has to be answerable without
guessing.

Shape: `query_family` (immutable `key`, status lifecycle) + `query_family_definition` (versioned
`scopes`, `description`, `support_only`, one active per family).

*4. The blocker is not the data model.* An editable family still needs **code that runs it**.
Adding `patent_filings` to a table does nothing until an agent knows how to query for it, and an
unrunnable family reports as a permanent coverage gap — the exact failure the closed set prevents.
So the table needs a `has_runner` flag, and a family without one must be **flagged as unrunnable**
on the Research screen rather than quietly reporting empty.

**Therefore: build this when the research agents exist**, not before. Phase 4 built the plan and
coverage plumbing; the agents themselves are still absent, and until they are there an editable
family cannot be anything but a coverage gap with extra steps.


## Deferred by design

These are answered "not now" on purpose, and re-opening them early is scope creep:

| Question | Deferred until |
|---|---|
| Autonomous sending without review | Never, per the out-of-scope list |
| Fine-tuning on approved drafts | Sufficient evaluation data exists (post-M6) |
| Multi-tenant / multi-client | A second client exists |
| Inbound / intent-data vendors (Bombora et al.) | The Intent dimension proves useful with free signals first |
| Automatic promotion of learning patterns | Never without human review, per [02 §8](02-architecture.md) |
| Runtime-editable query families | The research agents exist — see Q12 |


## Open with La Growth Machine — undocumented behaviours

Raised with LGM support; all three came back as not covered by available documentation. Each has a
chosen default, so none of them blocks the build.

| # | Question | Default we build against | Cost if the assumption is wrong |
|---|---|---|---|
| L1 | Is the scheduled send time per lead per step exposed anywhere? | **Closed by design.** We no longer need it — all content is written at enrolment, so there is no window to hit | None. Knowing the schedule would only reopen an option we chose not to take |
| L2 | Does a step read its attribute at step start or at send? | **Closed by design.** Never write to a lead already enrolled | If it reads at send, a future version could support mid-flight correction — worth re-testing before M6 |
| L3 | Are custom attributes scoped per campaign or globally per lead? | **Answered: global.** Stored on the lead profile, shared across the account | None — the conservative assumption was correct |

L3 is worth restating: the global per-account thread cap is what prevents the collision. If attributes
turn out to be global *and* the cap were ever relaxed, two campaigns would overwrite each other's copy
on a shared contact.

**How to close these:** they need either LGM engineering or an empirical test on a throwaway campaign
with a single test lead. The empirical route answers L2 and L3 in an afternoon and is worth doing
before M5.


### Why L1 and L2 stopped mattering

Both existed to support writing content shortly before each step fired. That design is gone: content
is written once, at enrolment, and frozen. The questions are now only interesting if we ever want to
*reopen* mid-flight correction — which would need both answers plus a verified update endpoint.

L3 (attribute scope) still matters and is still open.


### L4 — can LGM's sequence structure be read programmatically? **Answered: no**

LGM confirmed the API exposes campaign **metadata** (name, description, status, channels, audience,
timestamps) and **performance metrics** (open, reply, bounce rates, steps completed) — but **not** the
sequence graph: no steps, shapes, or message templates.

**Consequences, all now built:**

- Cadence registration stays manual, and step-level accuracy can only be confirmed by a person.
- Metadata gives a real change detector — `updated_at` against `verified_at` — replacing a blind
  30-day timer with same-day detection, plus a 90-day backstop for body-only edits the timestamp may
  not reflect.
- `channels` gives a coarse structural cross-check.
- Separately, **bounce rate** from the metrics endpoint became the enrichment-quality signal we were
  otherwise missing.

**Remaining unknown:** whether campaign `updated_at` moves when only a sequence body is edited. If it
does not, the backstop timer is the only guard for that case — which is why it stays. Worth confirming
empirically: edit a test campaign's message body, then poll its metadata.

L3 (attribute scope — per campaign or global per lead) remains the one genuinely open item.


### L3 — answered: attributes are global to the lead

LGM confirmed custom attributes live on the lead profile and are shared across the account. There is no
documented mechanism for per-campaign values.

The conservative assumption turned out to be right, so nothing built on it needs revisiting. What
changed is that the **contact-level enrolment lock moved from prudent to mandatory**, and it is now
enforced by a partial unique index rather than application logic — see [03](03-data-model.md).

LGM suggested two workarounds; neither survives our cadence lengths. Using different attribute ranges
per campaign needs 12 of 10 attributes and doubles the registration-drift surface. Updating attributes
before each campaign runs is the mid-flight rewrite already ruled out by L1/L2.

**All four LGM questions are now closed.** L1 and L2 by design, L3 and L4 by answer. The remaining
unknown is narrower: whether campaign `updated_at` moves when only a message body is edited, which
determines whether the 90-day backstop is redundant or load-bearing. One test campaign answers it.


### L5 — LGM's deduplication key — **answered**

A priority cascade: **LinkedIn URL → email → first + last + company**. First match merges the import
into the existing lead. Same email means same lead *even across different companies*.

**This broke the assumed key.** I had assumed email-only, reasoning that stricter was safer. It was
wrong in a way that mattered: LinkedIn ranks *above* email, so two contacts sharing a LinkedIn profile
but holding different emails resolve to different keys under a single-column scheme while LGM merges
them into one lead. The fix is a real `lgm_identity` resolution table matching on any identifier —
see [03](03-data-model.md).

**Also confirmed, and load-bearing:** deduplication prevents duplicate *profiles*, not duplicate
*campaign membership*. LGM will happily run one lead in several campaigns at once. Our contact lock is
the only thing preventing it, which settles any question of whether it earns its complexity.

**Two further findings, both from the same exchange:**

1. Concurrent campaigns **share the sending identity's daily action limits** — throughput is not
   additive, and a second campaign silently stretches the first.
2. A reply or opt-out **stops that lead across every campaign** on the same identity — defence in
   depth beneath our own cross-thread pause.

Both are written up in [02](02-architecture.md).

**Remaining unknown:** what LGM does when a new import matches one existing lead by LinkedIn and a
*different* one by email. Undocumented, so `lgm_identity.resolution_state = 'conflict'` blocks
enrolment rather than guessing.
