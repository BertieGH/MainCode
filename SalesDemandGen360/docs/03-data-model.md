# 03 — Data Model

PostgreSQL 16 with the `pgvector` extension. All tables carry `id UUID PRIMARY KEY DEFAULT
gen_random_uuid()`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, and where mutable,
`updated_at TIMESTAMPTZ`. Those three columns are omitted from the listings below.

**Runnable DDL lives in `docs/schema/`.** Where a `.sql` file exists for a domain it is the
reference — it carries the constraints, indexes, and triggers this document describes in prose,
and it is what the migrations are written from. `signals.sql` covers `signal_type`, `evidence`,
`signal`, and `signal_evidence`.

Conventions:
- Enum-like columns are stored as `TEXT` with a `CHECK` constraint, not PG `ENUM` types — adding a
  value to a PG enum is a migration; adding one to a CHECK is a one-line `ALTER`.
- Money is `NUMERIC(14,2)`; scores are `NUMERIC(5,2)` on a 0–100 scale; confidence is
  `NUMERIC(4,3)` on a 0–1 scale.
- Anything the LLM produced that is an interpretation rather than an observation carries
  `is_hypothesis BOOLEAN NOT NULL DEFAULT false`.

---

## Domain 1 — Configuration (Enterprise Memory)

Set up once, versioned, read by every run.

### `org_profile`
Who is **selling**. Single active row. Identity only — who we sell *to* is `icp_profile`.

| Column | Type | Notes |
|---|---|---|
| `name` | TEXT NOT NULL | |
| `description` | TEXT | |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | |
| `version` | INT NOT NULL | |

The `icp` column was dropped in `d4b28e15a903`. It held one buyer profile pretending to be the only
one; services sell to different kinds of buyer, and an account list has to be able to target a
profile without dragging a service along with it. See [11](11-icp-model.md).

### `icp_profile`
A kind of buyer, named once and **shared** by every service that sells to it.

The identity, deliberately separate from the definition. Services and account lists link to *this*
row, so activating a new version cannot orphan a link — which is exactly what a single versioned
table would do.

| Column | Type | Notes |
|---|---|---|
| `name` | TEXT NOT NULL UNIQUE | e.g. `Mid-market SaaS` |
| `description` | TEXT | |

### `icp_profile_version`
What an ICP actually says, at one point in time.

Versioned because an enrichment run records the version that selected its contacts. Editing in place
would make "why were these people chosen?" unanswerable the moment somebody widened the profile. A
new run resolves whichever version is active; a finished run keeps the id of the one it used.

| Column | Type | Notes |
|---|---|---|
| `icp_profile_id` | UUID NOT NULL FK → `icp_profile` ON DELETE CASCADE | |
| `definition` | JSONB NOT NULL | Industries, regions, headcount, exclusions, signals that matter, personas |
| `version` | INT NOT NULL | Unique per profile |
| `is_active` | BOOLEAN NOT NULL DEFAULT false | Partial unique index — exactly one active per profile |

A **persona** in `definition` is two things together:
`{"buying_role": "technical_buyer", "titles": ["CTO", "CIO", "VP Engineering"]}`. Titles are what
enrichment matches on, because a CSV carries a job title and not a buying role; the buying role is
what the strategy stage reasons with. `buying_role` uses the closed set already on
`contact.buying_role_valid`.

### `service_icp_link`
Which services sell to which buyers. Many-to-many, minimums enforced by the API rather than by a
constraint — a row-level rule cannot express "at least one link" without making the first insert
impossible.

| Column | Type | Notes |
|---|---|---|
| `service_id` | UUID FK → `service_catalog` ON DELETE CASCADE | PK with the other column |
| `icp_profile_id` | UUID FK → `icp_profile` ON DELETE CASCADE | |

A service must have **≥1** ICP: one nobody can describe a buyer for cannot be strategised. An ICP
must have **≥1** service: one that sells nothing is a note, not configuration, and nothing
downstream would read it.

### `service_catalog`
The offerings Strategy chooses from (EIA and siblings).

| Column | Type | Notes |
|---|---|---|
| `code` | TEXT NOT NULL UNIQUE | e.g. `EIA` |
| `name` | TEXT NOT NULL | |
| `description` | TEXT NOT NULL | |
| `positioning_angles` | JSONB | Distinct angles the same service can be sold on |
| `target_personas` | JSONB | Persona roles this service typically lands with |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | |

### `proof_point`
Case studies, metrics, and approved claims. **Only `is_approved` rows may appear in a draft.**

| Column | Type | Notes |
|---|---|---|
| `service_id` | UUID FK → service_catalog | |
| `kind` | TEXT CHECK IN (`case_study`,`metric`,`logo`,`testimonial`) | |
| `title` | TEXT NOT NULL | |
| `body` | TEXT NOT NULL | |
| `client_industry` | TEXT | |
| `client_size_band` | TEXT | |
| `metrics` | JSONB | Quantified outcomes |
| `is_approved` | BOOLEAN NOT NULL DEFAULT false | Legal/marketing sign-off |
| `source` | TEXT | Where the claim is substantiated |

### `writing_sample`
Real messages the team has sent — the voice reference for draft generation.

| Column | Type | Notes |
|---|---|---|
| `channel` | TEXT CHECK IN (`linkedin`,`email`) | |
| `subject` | TEXT | |
| `body` | TEXT NOT NULL | |
| `notes` | TEXT | Why this one is a good exemplar |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | |

### `sales_rules`
Versioned. Qualification, Strategy, Outreach, and Execution all read the active row.

| Column | Type | Notes |
|---|---|---|
| `version` | INT NOT NULL | |
| `priority_threshold` | NUMERIC(5,2) NOT NULL | Minimum Opportunity Priority to reach Strategy |
| `persona_weight_threshold` | NUMERIC(5,2) NOT NULL | Minimum weight for a thread to activate |
| `max_concurrent_threads` | INT NOT NULL DEFAULT 2 | Per account |
| `thread_start_offset_days` | INT NOT NULL DEFAULT 3 | Stagger between threads on one account |
| `cadence` | JSONB NOT NULL | Default touch plan (step, day offset, channel, purpose) |
| `signal_ttl_days` | JSONB NOT NULL | Per signal type, e.g. `{"funding": 270, "hiring": 60}` |
| `no_go` | JSONB | Domains, companies, industries never to contact |
| `compliance` | JSONB | Required disclosures, banned phrases, per-region rules |
| `is_active` | BOOLEAN NOT NULL DEFAULT false | Exactly one active |

### `scoring_config`
Versioned qualification maths. Deterministic — no LLM reads this to "decide"; the app computes with it.

| Column | Type | Notes |
|---|---|---|
| `version` | INT NOT NULL | |
| `dimension_weights` | JSONB NOT NULL | `{fit, opportunity, buyer, commercial, intent, engagement}` |
| `industry_multipliers` | JSONB NOT NULL | Per normalised industry, per dimension — e.g. `{"fintech": {"buyer": 1.4}}`. Keys match `account.industry_key`. Applied **on top of** `dimension_weights`, never replacing them |
| `size_multipliers` | JSONB NOT NULL | Per size band (`small`/`mid`/`large`), same shape. Never `unknown` — that is the absence of a headcount, not a size. Both sets compose and are renormalised **once** |
| `persona_role_weights` | JSONB NOT NULL | Buying-role multipliers used by persona × service scoring — e.g. `{"champion": 1.4, "blocker": 0.2}` |
| `signal_family_weights` | JSONB NOT NULL | Per query family — e.g. `{"funding": 1.5, "leadership": 0.8}`; a disabled family is `0` |
| `band_cutoffs` | JSONB NOT NULL | `{"high": 75, "medium": 50}` |
| `man_view_enabled` | BOOLEAN NOT NULL DEFAULT true | Legacy MAN display |
| `is_active` | BOOLEAN NOT NULL DEFAULT false | |

### `llm_config`
Per-scenario model configuration, versioned like every other rule. One row per pipeline stage, so
effort can be tuned where judgement matters without touching stages that are constrained
transformations.

| Column | Type | Notes |
|---|---|---|
| `scenario` | TEXT NOT NULL UNIQUE | `company_research`, `signal_extraction`, `strategy_synthesis`, `outreach_drafting`, `presend_revalidation`, … |
| `model` | TEXT NOT NULL DEFAULT `claude-opus-5` | |
| `effort` | TEXT CHECK IN (`low`,`medium`,`high`,`xhigh`,`max`) NOT NULL | The primary cost lever |
| `max_tokens` | INT NOT NULL | |
| `thinking_mode` | TEXT NOT NULL DEFAULT `adaptive` | |
| `output_contract` | TEXT NOT NULL | The Pydantic model name the response must validate against |
| `version` | INT NOT NULL | |
| `is_active` | BOOLEAN NOT NULL DEFAULT false | |

### `integration_credential`
Credentials for Anthropic, Apollo, ContactOut, La Growth Machine, and the custom CRM.

| Column | Type | Notes |
|---|---|---|
| `provider` | TEXT CHECK IN (`anthropic`,`apollo`,`contactout`,`lgm`,`crm`) NOT NULL | |
| `credential_type` | TEXT CHECK IN (`api_key`,`token`,`webhook_secret`,`base_url`) | |
| `value_encrypted` | BYTEA NOT NULL | **Encrypted at rest** |
| `last_four` | TEXT | The only part ever returned by the API, for display |
| `status` | TEXT CHECK IN (`valid`,`invalid`,`untested`,`expired`) | Set by the test-connection action |
| `last_tested_at` | TIMESTAMPTZ | |
| `spend_cap` | NUMERIC(12,2) | Anthropic only — monthly ceiling with an alert threshold |

**Three rules, non-negotiable:** credentials are encrypted at rest; the API never returns a full
value (only `last_four`); and no credential is ever written to a log, a prompt, or an `audit_log`
payload. A credential appearing in a prompt would be exfiltratable by prompt injection from a
researched web page.

### `enterprise_memory`
Free-form retrievable CGVAK knowledge not covered by the structured tables above.

| Column | Type | Notes |
|---|---|---|
| `category` | TEXT NOT NULL | `methodology`, `messaging`, `industry_note`, … |
| `key` | TEXT | |
| `content` | TEXT NOT NULL | |
| `embedding` | VECTOR(1536) | |
| `source` | TEXT | |

---

## Domain 2 — Accounts and people

### `account`

| Column | Type | Notes |
|---|---|---|
| `name` | TEXT NOT NULL | |
| `domain` | TEXT | Indexed; primary dedup key |
| `linkedin_url` | TEXT | |
| `industry` | TEXT | |
| `industry_key` | TEXT INDEX | `industry`, normalised (case-folded, whitespace collapsed) for joining to `scoring_config.industry_multipliers` — see [02 §5.1](02-architecture.md). Size is derived from `employee_count` and not stored |
| `employee_count` | INT | |
| `revenue_band` | TEXT | |
| `funding_stage` | TEXT | |
| `hq_country` | TEXT | ISO-2 |
| `hq_region` | TEXT | |
| `crm_record_id` | TEXT | Id in CGVAK's custom CRM; set when matched via `CrmAdapter.find_account` |
| `icp_match_score` | NUMERIC(5,2) | Cheap pre-filter, before full research |
| `icp_match_reasons` | JSONB | |
| `status` | TEXT CHECK IN (`new`,`researching`,`qualified`,`disqualified`,`active`,`closed`) | Overall lifecycle |
| `research_status` | TEXT CHECK IN (`not_started`,`running`,`complete`,`partial`,`failed`) NOT NULL DEFAULT `not_started` | |
| `research_completed_at` | TIMESTAMPTZ | |
| `enrichment_status` | TEXT CHECK IN (`not_started`,`running`,`complete`,`partial`,`failed`,`skipped`) NOT NULL DEFAULT `not_started` | |
| `enrichment_completed_at` | TIMESTAMPTZ | |
| `pipeline_note` | TEXT | Why a stage is `partial` or `failed` — surfaced on hover in the list |
| `disqualified_reason` | TEXT | |

**Research and enrichment are tracked separately because they are separate operations with different
cost models and different failure modes.**

| | Research | Enrichment |
|---|---|---|
| Produces | Firmographics, industry, evidence, signals | Buying committee contact details |
| Costs | Claude tokens (~$2/account) | **Provider credits per lookup** (Apollo / ContactOut) |
| Fails as | No signals extracted; site unreachable | No contactable person resolved |
| `partial` means | Some query families returned nothing | Email resolved but not phone, or 2 of 4 contacts |

**Do not auto-enrich on import.** Research everything cheaply, then enrich only what clears
qualification — enriching 200 accounts when 30 qualify burns credits on 170 companies nobody will
ever contact. This is why enrichment has a `skipped` state that research does not.

The dependency runs the other way for the Buyer dimension, which needs to know whether a committee
exists. That is resolved by splitting enrichment in two:

1. **Committee discovery** — names and titles from public team pages and LinkedIn, during research.
   Free, no provider credits, and enough to score Buyer structurally.
2. **Contact resolution** — email and phone through the Apollo / ContactOut waterfall, on demand for
   accounts heading to a queue. This is the part that costs credits.

Unique partial index on `lower(domain)` where `domain IS NOT NULL`.

### `account_alias`
Name and domain variants, so "Meridian Cloud", "Meridian Cloud Inc.", and `meridiancloud.io`
resolve to one account.

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account ON DELETE CASCADE | |
| `alias` | TEXT NOT NULL | Normalised lowercase |
| `alias_type` | TEXT CHECK IN (`name`,`domain`,`crm_id`) | |

### `contact`
Decision-makers. Buying-committee members, verified or flagged.

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account ON DELETE CASCADE | |
| `full_name` | TEXT NOT NULL | |
| `title` | TEXT | |
| `seniority` | TEXT CHECK IN (`c_level`,`vp`,`director`,`manager`,`ic`,`unknown`) | |
| `persona_role` | TEXT | Normalised role key, e.g. `vp_engineering`, `cto`, `cio`, `ceo` |
| `linkedin_url` | TEXT | |
| `email` | TEXT | |
| `email_status` | TEXT CHECK IN (`verified`,`risky`,`invalid`,`unverified`) NOT NULL DEFAULT `unverified` | |
| `email_confidence` | NUMERIC(4,3) | |
| `email_provider` | TEXT CHECK IN (`apollo`,`contactout`,`manual`) | Which waterfall step resolved the email — see [06 §9.2](06-llm-integration.md) |
| `email_provider_record_id` | TEXT | |
| `phone` | TEXT | |
| `phone_status` | TEXT CHECK IN (`verified`,`unverified`,`invalid`) NOT NULL DEFAULT `unverified` | |
| `phone_provider` | TEXT CHECK IN (`apollo`,`contactout`,`manual`) | Tracked separately from `email_provider` — the two fields can resolve from different providers on the same person |
| `phone_provider_record_id` | TEXT | |
| `is_hypothesis` | BOOLEAN NOT NULL DEFAULT false | True when the role/authority was inferred, not sourced |
| `do_not_contact` | BOOLEAN NOT NULL DEFAULT false | Off limits. Enrichment, research, queues and pre-flight all refuse them |
| `do_not_contact_reason` | TEXT | Required when the flag is set (`dnc_carries_a_reason`) |
| `do_not_contact_at` | TIMESTAMPTZ | |

**Send guard:** `email_status = 'verified'` is required before an email touch executes.

**Nobody is deleted.** A person who must not be approached is suppressed, never removed: their
signals, evidence, research coverage and any outreach already sent cite them, and those citations
are the record of what was done. `do_not_contact` closes every later door instead — the reason is
required because "why is this person off limits" is asked months later by somebody who was not
there.

#### Persona taxonomy — `seniority`, `persona_role`, and buying role

Raw job titles are normalised through one shared lookup table so that "VP Eng", "Head of
Engineering", and "Engineering Lead" all resolve to the same persona. Both the Strategy Agent's
persona weighting and the Buyer qualification dimension read this table, so they can never disagree
about who somebody is. It lives in `app/services/persona_taxonomy.py` as plain data, not a prompt —
it is a classification lookup, and an LLM call would be slower, costlier, and less consistent.

**Seniority tiers** (first match wins, checked in this order):

| Tier | Title contains |
|---|---|
| `c_level` | CEO, CTO, CFO, COO, CMO, CIO, CISO, Chief, Founder, Co-founder, President, Managing Director, Owner, Partner |
| `vp` | Vice President, VP, SVP, EVP, Head of |
| `director` | Director, Senior Director, Group Director |
| `manager` | Manager, Senior Manager, Team Lead, Lead |
| `ic` | Engineer, Analyst, Specialist, Coordinator, Designer, Developer, Associate, Consultant, Architect |
| `unknown` | No match |

**Department** — Engineering, Sales, Marketing, Product, Operations, Finance, HR, Legal, IT,
Customer Success, Executive; matched on the same keyword-list principle.

**Buying role** — the field that actually drives strategy:

| Buying role | Matches | Typical seniority |
|---|---|---|
| `economic_buyer` | CEO, CFO, COO, President, Founder, Managing Director, Owner | c_level |
| `technical_buyer` | CTO, VP Engineering, Head of Platform, Chief Architect | c_level / vp |
| `champion` | VP / Director / Head of — **in the department that feels the pain** | vp / director |
| `influencer` | Manager, Team Lead, Staff or Principal engineer | manager / ic |
| `blocker` | Procurement, Legal, General Counsel, Compliance, InfoSec | any |

`champion` is the one role that cannot be assigned from the title alone — it depends on which
department the account's signals point at, so it is resolved after signal extraction, not during
contact enrichment. A contact whose buying role was inferred rather than sourced carries
`is_hypothesis = true`, same as any other interpretation.

*Taxonomy adapted from [ai-sales-team-claude](https://github.com/zubair-trabzada/ai-sales-team-claude)
(MIT) — see [docs/reference](reference/README.md).*

### `account_list`
A labelled import set. Static — a list only grows by import or manual add. There is no filter to
recompute, so lists have no sync concept.

| Column | Type | Notes |
|---|---|---|
| `label` | TEXT NOT NULL | e.g. "Q3 DevOps ISVs — US" |
| `description` | TEXT | |
| `source` | TEXT CHECK IN (`csv`,`manual`,`crm`) | |
| `created_by` | TEXT NOT NULL | |

### `account_list_member`

| Column | Type | Notes |
|---|---|---|
| `list_id` | UUID FK → account_list ON DELETE CASCADE | |
| `account_id` | UUID FK → account | |
| `added_at` / `added_by` | TIMESTAMPTZ / TEXT | |
| `import_row_reason` | TEXT | Per-row import outcome: `created`, `merged`, `duplicate_domain`, … |

Primary key `(list_id, account_id)`.

### `account_list_service` and `account_list_icp`
What a list is being worked **for**. Both many-to-many, both `ON DELETE CASCADE`.

| Table | Columns |
|---|---|
| `account_list_service` | `list_id` → `account_list`, `service_id` → `service_catalog` |
| `account_list_icp` | `list_id` → `account_list`, `icp_profile_id` → `icp_profile` |

Services are chosen first and narrow the ICP picker to profiles those services actually sell to; an
ICP outside that set is **refused, not filtered**, because quietly dropping it would leave the list
enriching for fewer profiles than the screen showed.

Read at enrichment time by `verification.resolve_targeting`. Unset is not an error — the pass then
targets every ICP the chosen service sells to. Targeting narrows; it does not gate.

### `run`
One pipeline execution over one account.

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account | |
| `objective` | TEXT | Sales objective for this run |
| `stage` | TEXT CHECK IN (`resolution`,`research`,`signals`,`context`,`qualification`,`strategy`,`content`,`evaluation`,`awaiting_approval`,`done`) | |
| `status` | TEXT CHECK IN (`queued`,`running`,`succeeded`,`failed`,`cancelled`) | |
| `triggered_by` | TEXT | User id or `schedule` |
| `started_at` / `finished_at` | TIMESTAMPTZ | |
| `input_tokens` / `output_tokens` / `cache_read_tokens` | BIGINT | Cost tracking |
| `error` | TEXT | |

---

## Domain 3 — Evidence and signals

### `evidence`
Stored, **not interpreted**. This is the bottom of every audit trail.

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account ON DELETE CASCADE | |
| `run_id` | UUID FK → run | |
| `source_type` | TEXT CHECK IN (`web`,`news`,`jobs`,`linkedin`,`crm`,`provider`,`filing`,`manual`) | |
| `source_url` | TEXT | |
| `source_name` | TEXT | Publication or provider |
| `title` | TEXT | |
| `excerpt` | TEXT NOT NULL | The quoted passage the claim rests on |
| `observed_at` | DATE | **When the fact was true** — not when we fetched it |
| `retrieved_at` | TIMESTAMPTZ NOT NULL | |
| `author_id` | TEXT | Set when `source_type='manual'` — who logged it |
| `capture_method` | TEXT CHECK IN (`conversation`,`email`,`event`,`inbound`,`other`) | How a manual observation was obtained |
| `source_hash` | TEXT NOT NULL | Hash of the fetched document. **Not unique** — one document yields many excerpts |
| `excerpt_hash` | TEXT NOT NULL | Hash of `source_url + excerpt`. The dedup key |
| `raw_ref` | TEXT | Object-storage key for the compressed original. **Never in Postgres** |
| `raw_status` | TEXT CHECK IN (`stored`,`unavailable`,`purged`) NOT NULL DEFAULT `stored` | |
| `reliability` | NUMERIC(4,3) | Source-tier score |

```sql
CREATE UNIQUE INDEX evidence_dedup ON evidence (account_id, excerpt_hash);
CREATE INDEX evidence_by_source   ON evidence (account_id, source_hash);
```

### Why two hashes, not one

An earlier draft had a single `content_hash` unique on `(account_id, content_hash)`. That was a bug:
a funding article supporting three signals needs **three excerpt rows**, and a document-level unique
index admits only the first. The second and third would be silently rejected as duplicates, and the
signals citing them would then be dropped by the missing-evidence guard — a hallucination-shaped
failure caused by our own index.

Splitting the two restores both properties: `excerpt_hash` lets one document yield many excerpts while
still deduplicating a re-run, and the non-unique `source_hash` answers "have we already fetched this?"
without a network call.

### What is and is not stored

The 500-page PDF is **never** stored in Postgres. What lives in the row is metadata plus `excerpt` —
the quoted passage a claim rests on, typically a paragraph.

`raw_ref` points at a compressed snapshot in object storage, deliberately outside the database:

| Property | Consequence |
|---|---|
| Out of the query path | No table bloat, no effect on sequential scans |
| Out of database backups | Backup size tracks rows, not crawled bytes |
| Never loaded into a prompt | Extraction reads it once; nothing downstream re-reads it |

**Why keep it at all.** Adding a signal type means re-extracting over evidence already gathered. With
only excerpts, that requires re-fetching every source — and sources rot. Job postings are the worst
case and among the most valuable: they come down the day the role is filled. A rep opening `ev_103`
six months later would get a 404 on the very record the audit trail rests on.

Roughly 10,000 documents at ~2 MB compresses to ~20 GB, about **$0.50/month** in object storage.
Losing re-extraction and audit permanence to save that is a bad trade.

`raw_status = 'unavailable'` records a fetch that could not be snapshotted (paywall, robots
exclusion); `purged` records a retention deletion. Either way the excerpt and metadata survive, so a
signal never loses its citation — it loses only the ability to be re-read in full.

### Re-extraction when a signal type is added

1. Select evidence whose `source_type` maps to a family that could yield the new type.
2. Where `raw_status = 'stored'`, re-extract from `raw_ref` — **no network, no provider spend**.
3. Where it is not, re-fetch; if the source is gone, the account is reported as a coverage gap rather
   than silently scored as if the type never applied.

Token cost is identical either way — extraction reads the document once. What the snapshot buys is not
tokens but the ability to do this at all, months later, without depending on the internet not having
changed.

**Manual and CRM input are evidence, not a parallel system.** A rep saying *"Dana told me they are
evaluating Datadog, deciding by Q1"* is evidence — sourced to a person, on a date, from a
conversation — and is arguably stronger than a scraped careers page. It gets `source_type='manual'`,
an `author_id`, and a `capture_method`; CRM records get `source_type='crm'`. Both then support
signals through the ordinary `signal_evidence` join, appear in the same signal list, and score the
same way. Nothing about qualification, strategy, or cadence needs a special case.

Two consequences follow, and both matter:

- **Scores update for free.** Qualification is deterministic from signals, so a manual signal changes
  the score on the next re-score with no LLM call and no bespoke logic.
- **CRM text is data, never instructions.** A CRM note is free text written by a person and reaches
  the model the same way a scraped page does. It is subject to the same rule in
  [06 §11](06-llm-integration.md).

### `signal`
Typed, dated, confidence-scored interpretations of evidence.

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account ON DELETE CASCADE | Always set — a contact signal still belongs to an account |
| `contact_id` | UUID FK → contact ON DELETE CASCADE | **Null for company signals, set for contact signals** |
| `run_id` | UUID FK → run | |
| `signal_type` | TEXT NOT NULL FK → signal_type(key) | Registry-backed, not a hardcoded list — see below |
| `summary` | TEXT NOT NULL | |
| `business_implication` | TEXT | e.g. "Potential delivery capacity constraint" |
| `strength` | TEXT CHECK IN (`low`,`medium`,`high`) | |
| `confidence` | NUMERIC(4,3) NOT NULL | |
| `observed_at` | DATE NOT NULL | |
| `expires_at` | DATE | Computed from `sales_rules.signal_ttl_days` |
| `lifecycle_state` | TEXT CHECK IN (`discovered`,`validated`,`active`,`stale`,`expired`) NOT NULL | |
| `is_hypothesis` | BOOLEAN NOT NULL DEFAULT false | |
| `superseded_by` | UUID FK → signal | |

### `signal_type` — the registry

Signal types are **configuration, not schema**. An earlier draft carried them as free text with the
permitted values written in a column comment, which is the worst of both worlds: nothing stopped a
typo creating `funding_round` alongside `funding`, and there was no way to retire a type without
orphaning every historical signal referencing it.

| Column | Type | Notes |
|---|---|---|
| `key` | TEXT PRIMARY KEY | `funding`, `role_change`, … |
| `label` | TEXT NOT NULL | Display name |
| `description` | TEXT | What counts as this signal, for the extraction prompt |
| `scope` | TEXT CHECK IN (`company`,`contact`) NOT NULL | Which entity it attaches to. There is deliberately no `both` &mdash; a signal is about an organisation or about a person, and a type that claimed to be either would have no consistent home in the UI or in persona ranking |
| `default_ttl_days` | INT NOT NULL | Seeds `signal.expires_at` |
| `weight` | NUMERIC(4,2) NOT NULL DEFAULT 1.00 | Multiplier applied wherever the type contributes to a score |
| `produced_by` | TEXT[] | Query families expected to yield it — an empty result is a coverage gap |
| `status` | TEXT CHECK IN (`active`,`deprecated`) NOT NULL DEFAULT `active` | |
| `deprecated_at` | TIMESTAMPTZ | |

**Retire by deprecating, never by deleting.** A deprecated type stops being extracted and stops
appearing in pickers, while existing signals still render, still carry their evidence, and remain
available to the Learning layer. Deleting it would silently rewrite history — a qualification decided
partly on a signal type that no longer exists still needs to explain itself.

`weight` closes a loop that is otherwise manual: the Learning layer can observe that funding-plus-hiring
precedes meetings 2.3× more often than either alone, and that observation has somewhere to land
besides a chart nobody acts on. Promotion writes a new weight, versioned like any other config change.

### Company scope versus contact scope

Both are first-class, and they answer different questions.

| Scope | Question it answers | Examples |
|---|---|---|
| `company` | Is this organisation worth approaching now? | `funding`, `hiring`, `tech_adoption`, `leadership_change`, `expansion`, `m_and_a`, `layoff`, `product_launch`, `regulatory`, `competitor_evaluation` |
| `contact` | Is *this person* the one to approach, and what opens the conversation? | `role_change`, `content_activity`, `public_pain_statement`, `prior_employer_match`, `team_hiring`, `mutual_connection`, `engagement_history` |

Contact signals matter disproportionately to the first touch. A company signal explains *why now*; a
contact signal explains *why you*. An opener resting only on a funding round is one a competitor could
have written from the same press release.

They also change how personas are ranked. Strategy currently weights a persona by title against the
service catalogue — a structural guess. With contact signals it weights by **evidence about that
specific person**: someone three months into a VP Engineering role who has publicly written about
review bottlenecks is a stronger primary thread than a CTO the model merely infers should care.

A contact signal always carries `account_id` as well as `contact_id`, so account-level rollups stay
simple and a contact signal can still contribute to account qualification.

### `signal_evidence`
Join table. **A signal with zero rows here is invalid** — enforced by a repository guard and a test.

| Column | Type | Notes |
|---|---|---|
| `signal_id` | UUID FK → signal ON DELETE CASCADE | |
| `evidence_id` | UUID FK → evidence ON DELETE CASCADE | |
| `role` | TEXT CHECK IN (`primary`,`supporting`) | |

Primary key `(signal_id, evidence_id)`.

### `account_memory`
Per-account history, retrievable by embedding.

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account ON DELETE CASCADE | |
| `kind` | TEXT CHECK IN (`fact`,`conversation`,`objection`,`prior_outreach`,`note`) | |
| `content` | TEXT NOT NULL | |
| `embedding` | VECTOR(1536) | |
| `source_ref` | TEXT | Evidence id, CRM id, or thread id |
| `is_hypothesis` | BOOLEAN NOT NULL DEFAULT false | |
| `occurred_at` | TIMESTAMPTZ | |

---

## Domain 4 — Context and qualification

### `account_context`
The versioned handoff contract. Immutable once written; a new build makes a new version.

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account ON DELETE CASCADE | |
| `run_id` | UUID FK → run | |
| `version` | INT NOT NULL | |
| `parent_version` | INT | |
| `payload` | JSONB NOT NULL | The compressed context handed to downstream stages |
| `signal_ids` | JSONB NOT NULL | Which signals are in scope for this version |
| `token_count` | INT | |
| `builder_version` | TEXT | Code version that produced it |

Unique on `(account_id, version)`.

### `qualification`

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account ON DELETE CASCADE | |
| `context_id` | UUID FK → account_context | |
| `run_id` | UUID FK → run | |
| `fit_score` … `engagement_score` | NUMERIC(5,2) | Six columns, one per dimension |
| `priority_score` | NUMERIC(5,2) NOT NULL | Computed roll-up |
| `priority_band` | TEXT CHECK IN (`low`,`medium`,`high`) NOT NULL | |
| `reasons` | JSONB NOT NULL | Per dimension: `{score, band, reason, evidence_ids[]}` |
| `man_money` / `man_authority` / `man_need` | TEXT | Nullable legacy view |
| `scoring_config_version` | INT NOT NULL | Which maths produced this |

---

## Domain 5 — Strategy

### `strategy`

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account ON DELETE CASCADE | |
| `qualification_id` | UUID FK → qualification | |
| `run_id` | UUID FK → run | |
| `version` | INT NOT NULL | |
| `status` | TEXT CHECK IN (`draft`,`evaluated`,`approved`,`rejected`,`superseded`) | |

### `persona_service_score`
The full weighting matrix — every mapped persona against every catalog service. Retained even for
combinations that did not activate, because "why didn't we contact the CEO?" is a real question.

| Column | Type | Notes |
|---|---|---|
| `strategy_id` | UUID FK → strategy ON DELETE CASCADE | |
| `contact_id` | UUID FK → contact | |
| `service_id` | UUID FK → service_catalog | |
| `weight` | NUMERIC(5,2) NOT NULL | |
| `rationale` | TEXT | |
| `evidence_ids` | JSONB | |

### `strategy_thread`
One per persona actually being pursued (or queued).

| Column | Type | Notes |
|---|---|---|
| `strategy_id` | UUID FK → strategy ON DELETE CASCADE | |
| `contact_id` | UUID FK → contact | |
| `service_id` | UUID FK → service_catalog | |
| `weight` | NUMERIC(5,2) NOT NULL | |
| `rank` | INT NOT NULL | 1 = primary |
| `thread_status` | TEXT CHECK IN (`active_primary`,`active_secondary`,`queued`,`not_activated`) | |
| `problem_hypothesis` | TEXT NOT NULL | Always `is_hypothesis` in spirit — labelled as such in the UI |
| `trigger_summary` | TEXT NOT NULL | |
| `trigger_signal_ids` | JSONB NOT NULL | Must reference non-stale signals |
| `positioning` | TEXT NOT NULL | |
| `channel_sequence` | JSONB NOT NULL | e.g. `["linkedin","email"]` |
| `cta` | TEXT NOT NULL | |
| `avoid_list` | JSONB | Things not to say on this thread |
| `confidence` | NUMERIC(4,3) | |

---

## Domain 5b — Selection layers (lists → queues → campaigns)

The three labelled layers between an import and a send. **Each boundary is a copy, not a link.**
That is the defining property of this design and the reason there is no sync machinery anywhere in
this domain.

```
account_list ──copy──► campaign_queue ──copy + lock──► outreach_campaign
                       (mutable while draft)           (independent from here on)
```

- **Campaigns are built from people.** A queue holds the **contacts** a rep chose
  (`campaign_queue_contact`) — enrichment and research stay company-wide, outreach is to people — and
  whole accounts can still be queued alongside (`campaign_queue_member`). A person may join when their
  company passes the queue rule and they are reachable: a verified email or a LinkedIn profile.
- Building a queue **copies** account rows in. New imports into the source list never appear in the
  queue; status changes there never propagate. The `source_list_id` recorded on each member is a
  **provenance stamp only** — a dead reference kept for "where did this come from", carrying no
  behaviour.
- A queue is editable while `status = 'draft'`: add from any list, remove members.
- **Promotion locks the queue** (`status = 'locked'`) and copies its members' strategy threads into
  the campaign. To make a variant, clone the queue into a new draft — never re-open a locked one, or
  "which version of the queue did campaign 2 use?" stops being answerable.
- Nothing flows backward. Campaign progress, replies, and outcomes have no bearing on the queue.

### `campaign_queue`

| Column | Type | Notes |
|---|---|---|
| `label` | TEXT NOT NULL | |
| `description` | TEXT | |
| `status` | TEXT CHECK IN (`draft`,`locked`) NOT NULL DEFAULT `draft` | Locked on promotion |
| `locked_at` | TIMESTAMPTZ | |
| `promoted_to_campaign_id` | UUID FK → outreach_campaign | Which campaign locked it |
| `cloned_from_queue_id` | UUID FK → campaign_queue | Set when created by cloning a locked queue |
| `service_id` | UUID FK → service_catalog | **Chosen at creation** — what everyone in the campaign is approached about |
| `icp_profile_id` / `icp_version` | UUID FK → icp_profile / INT | The ICP it is built for (must be linked to the service), and the version in force then |

### `campaign_queue_member`

| Column | Type | Notes |
|---|---|---|
| `queue_id` | UUID FK → campaign_queue ON DELETE CASCADE | |
| `account_id` | UUID FK → account | |
| `source_list_id` | UUID FK → account_list | **Provenance stamp — no behaviour.** Nullable; survives list deletion |
| `qualification_id` | UUID FK → qualification | The scores as they stood when copied in |
| `added_at` / `added_by` | TIMESTAMPTZ / TEXT | |

Primary key `(queue_id, account_id)` — dedups a queue built from overlapping lists.

### `outreach_campaign`

| Column | Type | Notes |
|---|---|---|
| `label` | TEXT NOT NULL | e.g. "Sept EIA push — VP Eng" |
| `description` | TEXT | |
| `cadence_shape_id` | UUID FK → cadence_shape | The registered LGM cadence this campaign runs on |
| `status` | TEXT CHECK IN (`draft`,`pending_approval`,`executing`,`paused`,`completed`,`cancelled`) | |
| `started_at` | TIMESTAMPTZ | |
| `service_id` / `icp_profile_id` / `icp_version` | | Copied from the source queues at promotion; queues built for different ones cannot be promoted together |

### `outreach_campaign_source`
Which queues fed this campaign. Provenance only — recorded at promotion, never re-read.

| Column | Type | Notes |
|---|---|---|
| `campaign_id` | UUID FK → outreach_campaign ON DELETE CASCADE | |
| `queue_id` | UUID FK → campaign_queue | |

`outreach_sequence` gains `campaign_id` (FK → outreach_campaign) and `contact_id` (FK → contact) — the
person it is for. `thread_id` is optional: a person promoted by name gets a sequence before any strategy
exists, and the strategy thread is linked once one is being pursued for them. **A strategy is required
before execution, not at promotion** — pre-flight's *Every person has a strategy* check blocks until each
sequence has one. A sequence names a person or a thread (`names_a_person`). Sequences are per
`strategy_thread`, so **contact-level dedup happens at promotion**: a campaign built from two
overlapping queues must not create two sequences for one contact.

### Strategy and cadence drafts belong to the campaign; qualification to the company

A strategy is the case for approaching one person about one service, for one kind of buyer — so it is
built **per campaign**, against the campaign's service and ICP. Qualification is needed before any
campaign exists (it decides what to queue), so it stays with the company and is **read per ICP**: the
stored assessment keeps opportunity, commercial and intent; fit and buyer are recomputed in Python for
the ICP and the roll-up re-run (`icp_scores`) — no model call, and no row per ICP.

- `strategy.campaign_id` (+ `service_id`, `icp_profile_id`) — `(account_id, version)` stays unique; a
  rebuild writes the next version and supersedes the campaign's previous one.
- **Defaults are the sales rules**: a person is pursued when their weight meets
  `persona_weight_threshold`, within `max_concurrent_threads` per company, and a live signal exists.
- **A rep may override per person**, and it is recorded on the thread: `strategy_thread.chosen_by_rep`
  (pursued although the rules left them out) and `without_live_trigger` (built with nothing live to
  cite — the only case `threads_cite_a_trigger` allows an empty `trigger_signal_ids`). Both flag the
  sequence in approval, so it is read rather than sampled.
- Qualification is not a precondition for a strategy. The sequence's thread is resolved from the
  campaign's strategy first, then a company-wide strategy written before this model.

### Promotion guard — the global thread cap

With no cross-queue dedup, `sales_rules.max_concurrent_threads` is the **only** thing preventing the
same account being worked by two campaigns at once. It is therefore enforced **globally across all
campaigns**, not per campaign, and checked **at promotion** — blocking, with the conflicting campaign
named — rather than silently at send time. A rep who sees the conflict at promotion can act on it; a
send-time skip is invisible.

### Send-time safety interlock

The one deliberate exception to "nothing flows backward". Because a campaign is decoupled from its
queue, a company that lands on the no-go list today would otherwise keep receiving touches. The
Execution Adapter re-checks immediately before each send:

| Check | Failure action |
|---|---|
| `account.status != 'disqualified'` | Skip touch, mark `execution_record.status = 'skipped'` |
| Account/domain not on `sales_rules.no_go` | Skip |
| No `unsubscribe` engagement event for the contact | Skip, cancel remaining sequence |
| `contact.email_status = 'verified'` for email touches | Skip |

This is a compliance guard, not a sync: the send stops, and nothing propagates back to the queue.

## Domain 5c — Cadence

Cadence structure lives in **La Growth Machine**, so Gen360 stores a registration of what exists
there rather than the steps themselves. The `cadence_shape` table and its columns are defined under
*Cadence shapes and LGM attribute mapping* later in this document.

There are no `cadence_template` or `cadence_step` tables. An earlier draft defined them, on the
assumption Gen360 would author cadences; that assumption was wrong and they are not built.

### Shape selection — deterministic, no LLM

`outreach_sequence` carries `cadence_shape_id`, and selection is a pure function of account and
contact facts read from `sales_rules`:

| Condition | Shape selected |
|---|---|
| `contact.email_status != 'verified'` | LinkedIn-only 5 / 15d |
| size band `large` | Enterprise 8 / 23d |
| size band `small` | Startup 5 / 11d |
| Priority band = medium | Nurture 4 / 21d |
| Otherwise | Standard 6 / 15d |

`outreach_sequence.selection_log JSONB` records which rule fired and on what fact, so "why did this
account get the enterprise cadence?" is answerable from the row.

Per-step continuous adaptation — stretching offsets, dropping individual steps, LLM-proposed
reordering — is **not possible**: every distinct set of offsets would need its own LGM campaign.
Where an earlier draft described stretching ×1.5 or compressing ×0.7, read that as *selecting a
different registered shape*.

## Domain 6 — Content

### `outreach_sequence`

| Column | Type | Notes |
|---|---|---|
| `thread_id` | UUID FK → strategy_thread ON DELETE CASCADE | |
| `start_offset_days` | INT NOT NULL DEFAULT 0 | Stagger vs the primary thread |
| `status` | TEXT CHECK IN (`draft`,`pending_eval`,`pending_approval`,`approved`,`executing`,`paused`,`completed`,`cancelled`) | |
| `lgm_campaign_id` | TEXT | Set by the Execution Adapter |

### `touch`

| Column | Type | Notes |
|---|---|---|
| `sequence_id` | UUID FK → outreach_sequence ON DELETE CASCADE | |
| `step_no` | INT NOT NULL | |
| `day_offset` | INT | **NULL for anything drafted since 2026-09-20** — LGM schedules its own steps and publishes no delays, so a day here could only be invented. Older rows keep the value they were written with (see corrections log §40) |
| `channel` | TEXT CHECK IN (`linkedin_connect`,`linkedin_message`,`linkedin_engage`,`inmail`,`email`) | |
| `purpose` | TEXT | "Personalised hook, no pitch yet" |
| `status` | TEXT CHECK IN (`pending`,`scheduled`,`sent`,`skipped`,`failed`) | |
| `scheduled_at` / `sent_at` | TIMESTAMPTZ | |
| `lgm_step_id` | TEXT | |

Default cadence (6 touches / 15 days): LinkedIn connect D1 → Email 1 D3 → LinkedIn engage D6 →
Email 2 D8 → InMail D12 → Email 3 (breakup) D15. Overridable via `sales_rules.cadence`.

### `draft`
Versioned message content. Regeneration adds a version; it does not overwrite.

| Column | Type | Notes |
|---|---|---|
| `touch_id` | UUID FK → touch ON DELETE CASCADE | |
| `version` | INT NOT NULL | |
| `subject` | TEXT | |
| `body` | TEXT NOT NULL | |
| `cited_proof_point_ids` | JSONB | Must all be `is_approved` |
| `model` | TEXT | e.g. `claude-opus-5` |
| `prompt_version` | TEXT | |
| `generated_as` | TEXT CHECK IN (`arc`,`regeneration`) NOT NULL DEFAULT `arc` | Written with the whole sequence, or regenerated during review. **Regeneration is only possible before enrolment** — once written to the LGM lead, content is frozen |
| `regenerated_reason` | TEXT | `signal_stale`, `proof_point_unapproved`, `rep_guidance`, … — so "this isn't what I approved" is answerable |
| `is_current` | BOOLEAN NOT NULL DEFAULT true | |

### `sales_prep`

| Column | Type | Notes |
|---|---|---|
| `thread_id` | UUID FK → strategy_thread ON DELETE CASCADE | |
| `run_id` | UUID FK → run | |
| `elevator_pitch` | TEXT | |
| `pitch_structure` | JSONB | Situation / Complication / Angle / Proof / Ask |
| `discovery_questions` | JSONB | |
| `objections` | JSONB | Objection + pre-empt pairs |
| `artifacts` | JSONB | Generated `.pptx` / `.docx` / `.pdf` file references |

---

## Domain 7 — Governance and execution

### `evaluation`
Polymorphic — one table for every stage's checks.

| Column | Type | Notes |
|---|---|---|
| `subject_type` | TEXT CHECK IN (`research`,`signal`,`qualification`,`strategy`,`draft`,`sales_prep`,`execution`) | |
| `subject_id` | UUID NOT NULL | No FK — polymorphic by design |
| `method` | TEXT CHECK IN (`rules`,`llm`,`hybrid`) | |
| `verdict` | TEXT CHECK IN (`pass`,`warn`,`fail`) NOT NULL | |
| `scores` | JSONB | Per-criterion scores |
| `issues` | JSONB | Structured findings |
| `evaluator_version` | TEXT | |

Index on `(subject_type, subject_id)`.

### `approval`
The human gate. **`execution_record` insert requires a matching `decision='approve'` row.**

| Column | Type | Notes |
|---|---|---|
| `subject_type` | TEXT CHECK IN (`strategy`,`outreach_sequence`,`draft`) | |
| `subject_id` | UUID NOT NULL | |
| `decision` | TEXT CHECK IN (`approve`,`edit`,`regenerate`,`reject`) NOT NULL | |
| `reject_reason` | TEXT CHECK IN (`wrong_persona`,`wrong_signal`,`wrong_problem`,`wrong_solution`,`poor_message`,`other`) | Required when `decision='reject'` |
| `comment` | TEXT | |
| `edited_body` | TEXT | Populated on `edit` — the delta is the most valuable learning signal in the system |
| `reviewer_id` | TEXT NOT NULL | |
| `review_depth` | TEXT CHECK IN (`individual`,`sampled`,`inherited`) NOT NULL DEFAULT `individual` | How closely this was actually read |
| `sample_id` | UUID | Groups a sampled batch together |
| `sample_size` / `stratum_size` | INT | 6 read out of 14 clean, say |
| `decided_at` | TIMESTAMPTZ NOT NULL | |

`review_depth` exists so the Learning layer can compare outcomes of drafts a human **read**
(`individual`, or `sampled` and in the sample) against those **accepted unread** (`inherited`). If
the unread group underperforms, that is evidence to raise the sample rate — without this column the
sampling model can only be assumed safe, never demonstrated. The Dashboard's Quality tab renders
exactly this comparison.

### `execution_record`

| Column | Type | Notes |
|---|---|---|
| `sequence_id` | UUID FK → outreach_sequence | |
| `touch_id` | UUID FK → touch | |
| `provider` | TEXT NOT NULL DEFAULT `lgm` | |
| `provider_ref` | TEXT | |
| `action` | TEXT | |
| `status` | TEXT CHECK IN (`queued`,`sent`,`failed`,`skipped`) | |
| `error` | TEXT | |
| `sent_at` | TIMESTAMPTZ | |

### `engagement_event`

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account | |
| `contact_id` | UUID FK → contact | |
| `touch_id` | UUID FK → touch | |
| `event_type` | TEXT CHECK IN (`open`,`click`,`reply`,`connection_accepted`,`meeting_booked`,`bounce`,`unsubscribe`) | |
| `payload` | JSONB | Raw provider event |
| `occurred_at` | TIMESTAMPTZ NOT NULL | |

A `reply` event triggers the cross-thread pause described in [02 §9](02-architecture.md).

### `crm_sync_log`

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account | |
| `entity` | TEXT | `account`, `contact`, `activity`, `note` |
| `operation` | TEXT CHECK IN (`create`,`append`) | **No `update`, no `delete`** — `CrmAdapter` has no method that could write either |
| `crm_record_id` | TEXT | |
| `payload` | JSONB | |
| `status` | TEXT | |
| `synced_at` | TIMESTAMPTZ | |

### `audit_log`

| Column | Type | Notes |
|---|---|---|
| `actor_type` | TEXT CHECK IN (`agent`,`user`,`system`) | |
| `actor_id` | TEXT | Agent name or user id |
| `action` | TEXT NOT NULL | |
| `subject_type` / `subject_id` | TEXT / UUID | |
| `before` / `after` | JSONB | |

---

## Domain 8 — Outcomes and learning

### `outcome`

| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID FK → account | |
| `thread_id` | UUID FK → strategy_thread | |
| `stage` | TEXT CHECK IN (`no_reply`,`replied`,`meeting`,`opportunity`,`won`,`lost`) | |
| `amount` | NUMERIC(14,2) | |
| `close_date` | DATE | |
| `rep_feedback` | TEXT | |
| `recorded_at` | TIMESTAMPTZ NOT NULL | |

### `learning_record`
Candidate cross-account patterns. **Nothing here changes production behaviour until
`status='promoted'` via an explicit human review.**

| Column | Type | Notes |
|---|---|---|
| `pattern_type` | TEXT CHECK IN (`signal_predicts_meeting`,`persona_responds`,`angle_converts`,`false_positive_signal`,`service_performance`) | |
| `pattern` | JSONB NOT NULL | The claim, stated precisely enough to be falsifiable |
| `supporting_case_ids` | JSONB NOT NULL | Thread ids where the pattern held |
| `counter_case_ids` | JSONB NOT NULL | **Thread ids where the signals were present and the outcome did not follow** |
| `baseline_rate` / `observed_rate` / `lift` | NUMERIC | The maths behind the claim |
| `sample_size` | INT NOT NULL | |
| `confidence` | NUMERIC(4,3) | |
| `confounders` | JSONB | Detected concentrations — industry, size, persona, cadence, single-campaign |
| `status` | TEXT CHECK IN (`candidate`,`validated`,`rejected`,`promoted`,`demotion_candidate`) NOT NULL DEFAULT `candidate` | |
| `promotion_scope` | JSONB | Global, or narrowed — e.g. `{"industry": ["saas","fintech"]}` |
| `promoted_config_version` | INT | The `scoring_config` version promotion created |
| `post_promotion_lift` | NUMERIC | Re-measured against accounts seen since promotion |
| `reviewed_by` / `reviewed_at` | TEXT / TIMESTAMPTZ | |

### Learning patterns carry evidence, like every other conclusion

A pattern is a **conclusion**, and the system's founding rule is that every conclusion traces to
dated, sourced evidence. A pattern with no traceable path back is the one place that rule could
quietly break — and it is the most dangerous place for it to break, because promoting a pattern
changes how *every future account* is scored.

The chain a reviewer can walk, entirely in the UI:

```
Pattern  →  supporting and counter cases  →  each case's signals  →  each signal's evidence
                                                                     → source, date, excerpt
```

Three requirements follow, and none is optional:

1. **Counter-examples are mandatory, not a courtesy.** `counter_case_ids` is `NOT NULL` because a
   pattern presented without the cases where it failed is cherry-picking. 34 supporting against 11
   counter is a finding; 34 against 40 is noise wearing a percentage.
2. **Confounders are computed and shown.** If 29 of 34 supporting cases share one industry, the
   pattern may be an industry effect rather than a signal effect. The system detects the
   concentration and says so — it does not need to resolve it, only to stop a reviewer promoting
   blind.
3. **Promotion can be scoped.** `promotion_scope` lets a SaaS-derived finding be promoted to SaaS
   accounts only, rather than applied globally to enterprise accounts the evidence never covered.

### Promotion is not the end

`post_promotion_lift` re-measures a promoted pattern against accounts seen *since* promotion. A claim
that drifts materially from its promoted value becomes a `demotion_candidate`. Without this, a
promoted pattern is a permanent unexamined assumption baked into scoring — which is precisely what
the evidence model exists to prevent.

---

## Table count by domain

| Domain | Tables |
|---|---|
| 1 — Configuration | 9 |
| 2 — Accounts and people | 6 |
| 3 — Evidence and signals | 4 |
| 4 — Context and qualification | 2 |
| 5 — Strategy | 3 |
| 5b — Selection layers | 4 |
| 5c — Cadence | 2 |
| 6 — Content | 4 |
| 7 — Governance and execution | 6 |
| 8 — Outcomes and learning | 2 |
| **Total** | **42** |

## Migration sequencing

| Migration | Adds | Milestone |
|---|---|---|
| `001_config` | Domain 1 | M0 |
| `002_accounts` | Domain 2 | M1 |
| `003_evidence_signals` | Domain 3 | M1 |
| `004_context_qualification` | Domain 4 | M2 |
| `005_strategy` | Domain 5 | M3 |
| `005b_lists` | `account_list`, `account_list_member` | M1 |
| `005c_queues` | `campaign_queue`, `campaign_queue_member` | M3 |
| `005d_campaigns_cadence` | `outreach_campaign`, `outreach_campaign_source`, `cadence_shape` | M4 |
| `006_content` | Domain 6 | M4 |
| `007_governance` | Domain 7 (evaluation, approval, audit_log) | M4 |
| `008_execution` | Domain 7 (execution_record, engagement_event, crm_sync_log) | M5 |
| `009_outcomes_learning` | Domain 8 | M6 |


## Cadence shapes and LGM attribute mapping

Cadence structure lives in LGM, so we store the *mapping* rather than the steps themselves.

### `cadence_shape`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `key` | TEXT UNIQUE | `standard_6_15`, `enterprise_8_23`, … |
| `label` | TEXT | Shown in the UI |
| `lgm_campaign_id` | TEXT NOT NULL | The pre-built LGM campaign this shape maps to |
| `touch_count` | INT NOT NULL | Read from the LGM campaign's active steps |
| `span_days` | INT | **NULL since 2026-09-20.** It was typed by a rep, because LGM exposes step timing on no route; it is no longer asked for |
| `attribute_map` | JSONB | `{"1": "custom_attribute_1", "2": "custom_attribute_2", …}` |
| `attributes_used` | INT | Validated against the 10-per-lead cap on save |
| `selection_rule` | JSONB | Which deterministic condition selects this shape |
| `verified_at` | TIMESTAMPTZ | When a person last checked the registration against the live LGM sequence |
| `lgm_updated_at` | TIMESTAMPTZ | From LGM campaign metadata, polled hourly. `lgm_updated_at > verified_at` blocks enrolment |
| `lgm_channels` | TEXT[] | From metadata — cross-checked against the registered steps |
| `lgm_status` | TEXT | Paused or archived campaigns cannot accept enrolments |
| `verified_by` | TEXT | Who checked it |
| `durable_from_step` | INT | Historical. Was derived from `span_days`; nothing computes a new one |
| `active` | BOOLEAN | |

`cadence_shape` rows are a **mirror of LGM, not a source of truth**. Gen360 never creates a sequence
from one; it reads the mapping to know which attribute each step consumes. `verified_at` is load
bearing: enrolment is refused when LGM reports the campaign changed after it, or when it is older than
the 90-day backstop — because a stale mapping writes copy into
the wrong step and nothing detects it.

**Timing belongs to LGM.** `/campaigns/:id` carries no step delay, `/campaigns/:id/settings` is a
404, and `/campaigns/:id/messages` gives order, channel and template only. So a cadence is
registered by naming the campaign — everything else is read — and the schedule is never set here.
It is *observable* after a campaign runs, from `/statsleads` and from `outreach_event` send times;
that is evidence, not configuration.

### Changes to `touch`
| Column | Type | Notes |
|---|---|---|
| `lgm_attribute` | TEXT | Which `custom_attribute_N` this touch's body is written into |
| `content_sync_status` | TEXT CHECK IN (`pending`,`written`,`failed`) | All touches move `pending` → `written` in one batch at enrolment, never per-step. `failed` blocks enrolment rather than letting a campaign start half-written |
| `content_written_at` | TIMESTAMPTZ | Same timestamp across every touch in a sequence — they are written together |
| `stop_reason` | TEXT | `signal_expired`, `reply_received`, `compliance`, `manual` — why remaining touches were halted |
| `subject_source` | TEXT CHECK IN (`lgm_template`,`custom_attribute`) | Subjects default to LGM-native to save attribute budget |

`outreach_sequence` gains `cadence_shape_id` and `lgm_lead_id`; `cadence_template` / `cadence_step`
are dropped — they modelled steps we no longer own.

**Why `content_sync_status` matters:** content existing in our database is not the same as content
existing on the LGM lead. Without this column, a failed attribute write is invisible until a recipient
gets the wrong message.


### A consequence worth stating in the schema

Because content is frozen at enrolment, `draft` rows for an enrolled sequence are **immutable**. There
is no "edit the draft for touch 5 while touches 1–4 have sent" path — that would silently diverge from
what LGM will actually send. Editing means stopping the sequence and re-enrolling, which creates a new
`outreach_sequence` with new `draft` rows.

Enforce it: a trigger or repository guard rejecting `UPDATE` on `draft` where the parent sequence
status is `executing`. Without it, the UI and LGM drift apart and nobody notices until a recipient
gets copy nobody approved.


## Enforcing the contact enrolment lock

Because LGM stores attributes per lead, two non-terminal sequences for one contact will corrupt each
other's copy. This invariant is too consequential to leave to application logic — it belongs in the
database, on a column that matches how LGM decides two records are the same person.

**Key on LGM's identity, not ours.** An index on `contact_id` has a hole: if LGM collapses two of our
contact rows into one lead, both pass the index and still overwrite each other's attributes.

LGM confirmed it deduplicates on a **priority cascade**, not a single field:

| Priority | Identifier | Behaviour |
|---|---|---|
| 1 | LinkedIn URL | Same profile → same lead, whatever the email |
| 2 | Email | Used when no LinkedIn URL. **Same email → same lead even across different companies** |
| 3 | First + last + company | Used only when neither LinkedIn nor email is present |

A single computed column cannot express this, and assuming it could was wrong. Consider:

- Contact A — LinkedIn `X`, email `E1`
- Contact B — no LinkedIn, email `E1`

Keyed on a coalesce cascade, A resolves to `X` and B to `E1` — different keys, so a unique index
admits both. LGM matches B against A's stored email and merges them into one lead. The two sequences
then overwrite each other's attributes, which is exactly the state the lock exists to prevent.

### `lgm_identity`

Resolution therefore needs its own table, clustering contacts the way LGM would:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `linkedin_slug` | TEXT UNIQUE | Normalised — host, casing, and trailing slash stripped |
| `email` | TEXT UNIQUE | Lower-cased, trimmed |
| `name_company_key` | TEXT UNIQUE | `lower(first \|\| last \|\| company)`, the fallback only |
| `resolution_state` | TEXT CHECK IN (`resolved`,`conflict`) | |

`contact.lgm_identity_id` FK. Resolution runs before enrolment and matches on **any** identifier in
LGM's priority order: find by `linkedin_slug`, else `email`, else `name_company_key`; attach if found,
create if not.

When a contact matches **two different identities** on different fields — A by LinkedIn, B by email —
the row is marked `conflict` and enrolment blocks. LGM's own behaviour in that case is undocumented,
so guessing which record it merges into risks corrupting whichever sequence guessed wrong.

```sql
CREATE UNIQUE INDEX one_active_sequence_per_lgm_identity
  ON outreach_sequence (lgm_identity_id)
  WHERE status IN ('pending_approval', 'approved', 'executing', 'paused');
```

A second contact resolving to an identity key already held by a live sequence is not always a
duplicate — it can be a genuine fractional executive at two accounts, or a data error. Both cases
surface at campaign pre-flight rather than being silently merged.

A partial unique index makes the bad state unrepresentable. A race between two concurrent campaign
promotions cannot slip through, and no future code path can bypass it by forgetting a check.

`outreach_sequence.status` therefore needs a clean terminal/non-terminal split:

| Non-terminal — holds the lock | Terminal — releases it |
|---|---|
| `pending_approval`, `approved`, `executing`, `paused` | `completed`, `stopped`, `cancelled` |

`paused` deliberately **holds** the lock: a paused sequence still has unsent touches whose copy sits in
the lead's attributes. Releasing on pause would let a second campaign overwrite them.

### Deferred enrolment

For the "queue them for automatic enrolment" option, a contact excluded by the lock is recorded rather
than dropped:

### `deferred_enrolment`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `campaign_id` | UUID FK | Campaign waiting to enrol them |
| `contact_id` | UUID FK | |
| `blocked_by_sequence_id` | UUID FK | The sequence currently holding the lock |
| `created_at` / `resolved_at` | TIMESTAMPTZ | |
| `status` | TEXT CHECK IN (`waiting`,`enrolled`,`abandoned`) | |

When the blocking sequence goes terminal, a worker enrols the waiting contact — subject to the same
approval gate as any other thread. Nothing sends unreviewed just because it was queued.
