> **IMPLEMENTED 2026-09-07.** `icp_profile` / `icp_profile_version` / `service_icp_link` /
> `account_list_service` / `account_list_icp` are live, with API, UI and tests. `org_profile.icp`
> is dropped and `service_icp` (the wrong shape from [10](10-service-icp.md)) is gone.
> The three-way ranking before enrichment is live — match / `out_of_persona` / `unknown_persona`,
> with the unknown bucket capped. What is **not** built is the *classifier*: `matches_persona` is
> a casefolded substring test over title, persona role, buying role and seniority, so "CTO" does
> not match "Chief Technology Officer". The structure is right and the judgement is crude.

# 11 — The ICP Model, Restated

**Supersedes [10](10-service-icp.md) entirely.** That document proposed an ICP *owned by* a service,
one each, cascade-deleted with it. This one is a different shape, and the difference is not a detail:
ICPs stand alone and are shared, and both services and account lists point at them.

Recorded plainly because it was got wrong twice. First as a shared library (right shape, argued
against on cost grounds), then as a service-owned column (wrong shape, built). The requirement that
settles it is **an account list targets an ICP** — a list cannot point at "the ICP belonging to a
service" without dragging the service along, so the ICP has to be a thing in its own right.

---

## One ICP concept, not two

There is no "house ICP" and no separate "industry ICP". Both were the same idea wearing two names.

An **ICP** is a named, versioned description of a kind of buyer: industries, regions, headcount,
exclusions, the signals that matter, the personas worth reaching. `org_profile` keeps `name` and
`description` — who CGVAK is — and loses `icp`, which was only ever one profile pretending to be
the only one.

---

## Cardinality

```
    ICP  ────────< many-to-many >────────  Service
     │                                        │
     │  a service has >= 1 ICP                │
     │  an ICP has >= 1 service               │
     │                                        │
     └──────< Account List >──────────────────┘
              targets one or more of each
```

* **A service must have at least one ICP.** A service nobody can describe a buyer for cannot be
  strategised, and its `target_personas` column was always a thin stand-in for exactly this.
* **An ICP must be linked to at least one service.** An ICP that sells nothing is a note, not
  configuration — and nothing downstream would ever read it.
* **Many-to-many in both directions.** Two services genuinely can share one buyer profile, and one
  service genuinely can sell to two different kinds of buyer.

---

## The pipeline, in dependency order

Each step is unreachable until the one above it exists. This is the order the UI should enforce and
the order the build should follow.

| # | step | needs | why it cannot come earlier |
|---|---|---|---|
| 1 | **Services** | — | Nothing else means anything without something to sell |
| 2 | **Proof points** *(optional)* | a service | Approved proofs sharpen every later prompt; absence is allowed |
| 3 | **ICPs**, linked to services | ≥1 service | An ICP with no service is unreadable by anything |
| 4 | **Account list intake** | ≥1 service **with** an ICP | The list records *which services and which ICPs it is for* |
| 5 | **Enrichment** | the list's ICPs | Targets contacts matching the intended persona — see below |
| 6 | **Signal types + research** | the list's services and ICPs | What to look for depends on what is being sold, to whom |
| 7 | **Strategy** | research output | Which service, which angle, per contact |
| 8 | **Cadence + content** | strategy | Shape selected from LGM; copy filled per invariant 6 |

---

## Enrichment stops being indiscriminate

Today `unverified_contacts` selects every unverified contact on a list, alphabetically, and pays a
metered provider for each. That finds a junior developer's address when the service needed the CTO,
and the list then *looks* enriched.

With the list carrying its ICPs, enrichment can ask the right question first: **does this contact
match the intended persona?** — judged from title, LinkedIn headline and seniority, which imports
usually carry.

The classification is an LLM call and the enrichment is an Apollo credit. The former is far cheaper
than the latter, so classifying before enriching **pays for itself** whenever it declines even a
modest share of a list. That is the argument for spending a model call here rather than a heuristic.

Ranked, not filtered:

1. **Matches an ICP persona** — enrich.
2. **Has a title, matches nothing** — skipped and *reported as out-of-persona*, never silently
   enriched.
3. **No title at all** — its own bucket with a cap, because spending to find out is the only option
   and it must not quietly drain credits.

Excluding outright would drop real buyers whose titles read oddly; enriching everything is the
present behaviour and the thing being fixed.

---

## Personas: a buying role plus the titles that fill it

A persona on an ICP is **two things together**, not one:

```json
{ "buying_role": "technical_buyer", "titles": ["CTO", "CIO", "IT Head", "VP Engineering"] }
{ "buying_role": "economic_buyer",  "titles": ["CEO", "CFO", "Managing Director"] }
{ "buying_role": "champion",        "titles": ["Head of QA", "Engineering Manager"] }
```

The two halves are read by different stages, which is why neither alone is enough:

* **Titles are what enrichment matches on.** A CSV carries "VP Engineering", not a buying role, so
  title strings are the only thing available before a contact has been enriched or classified.
* **The buying role is what strategy reasons with.** An economic buyer wants the business case, a
  technical buyer wants the architecture, a champion wants to look right internally. That is the
  context the strategy stage has been missing.

`buying_role` is a closed set **already in the schema** — `economic_buyer`, `technical_buyer`,
`champion`, `influencer`, `blocker` (`contact.buying_role_valid`). The ICP uses that set rather than
inventing a parallel one. `blocker` is worth keeping even though nobody would *target* one: naming
who obstructs is useful to strategy, and an ICP is the natural place to say so.

This also fixes something currently unowned. `contact.buying_role` is populated in seed data and by
nothing else — no import path or enrichment step sets it. With personas defined this way, the
classifier that decides "does this contact match the ICP?" produces the buying role as a by-product
of the same judgement, so one call fills both.

Note `contact.persona_role` is a **third** thing — functional area (`engineering`, `finance`,
`data`, `operations`) — and stays as it is. Title says what they are called, persona role says which
department, buying role says what they do to a purchase.

### What this replaces

`service_catalog.target_personas` holds two taxonomies at once today: `['CEO','CTO','CIO','IT head']`
on `EIA` and `['technical_buyer','champion']` on `qa_engineering` — job titles beside buying roles,
in one column, with nothing to say which is which. Folding it into the ICP is the moment that stops
being ambiguous rather than being carried across.

---

## Schema

```
icp_profile           id, name, description, definition JSONB, version, is_active
                      versioned per name - exactly one active row per profile

service_icp_link      service_id, icp_profile_id            (M2M, PK on both)
account_list_service  list_id, service_id                   (M2M)
account_list_icp      list_id, icp_profile_id               (M2M)
```

**To undo first:** `service_icp` (table, model, two endpoints, migration `b7d4e9a1c260`) is the wrong
shape and is dropped. Two rows exist, both written by my own API test; no screen ever wrote one and
nothing reads them. `org_profile.icp` migrates to a single `icp_profile` seeded from its current
contents — `industries, regions, employees, exclusions, signals_that_matter` — so nothing is lost.

Minimums are enforced at the **API**, not by a constraint. A row-level rule cannot express "at least
one link" without making the first insert impossible; the endpoint that creates an ICP takes its
service links in the same call, and refuses an empty list.

---

## Consequences to handle

**`industry_multipliers` loses its source.** Shipped earlier today, it derives its rows from
`org_profile.icp.industries`. With industries living on ICP profiles, rows come from the **union of
industries across active ICP profiles**. Orphan handling is unchanged: an industry no longer named
by any ICP is struck through and kept, never dropped on save.

**`service_catalog.target_personas` is superseded.** Personas belong to the ICP, which is the thing
that describes a buyer. The column holds two taxonomies today — `['CEO','CTO','CIO','IT head']` on
one service and `['technical_buyer','champion']` on another, job titles beside buying roles. Folding
it into the ICP is the moment to settle that, not carry it across.

**`account.icp_match_score` becomes ambiguous** — several ICPs now. It holds the *best* match, plus
the profile that won, so list sorting keeps working on one column and the score is explainable.

---

## Decided

**A list picks services first, then ICPs.** Two steps, not one: choose the services this list is
for, and the ICP picker then offers only the ICPs linked to them. Rejected the alternative of
picking ICPs and inferring the services — a rep thinks in terms of what they are selling, and
narrowing the second list by the first keeps the choice small without hiding it.

**Personas are a buying role plus titles** — see above.

## Open decisions

1. **Must a list have an ICP at intake, or can it be added later?** Proposed: **later is allowed,
   enrichment is blocked until set.** Import itself is not gated — a list is cheap and harmless;
   enrichment is what spends money against the wrong people.
2. **What happens to a list whose ICP is later edited?** An ICP is versioned, so a list could pin
   the version it was enriched under, or always follow the active one. Pinning makes "why were these
   contacts chosen?" answerable; following means one edit re-targets every list at once. Proposed:
   **pin at enrichment, record which version ran** — the same reasoning that versions every other
   config table here.

---

## Revised 2026-09-10 — personas live on the ICP only

Three changes, decided with the rep who uses these screens:

* **A service says who signs off; it no longer says who to reach.** `service_catalog.target_personas`
  became `economic_buyer` — one line of text ("CIO / Head of IT"), carried into prompts as context and
  never used as a filter. Existing values were copied across as text (migration `a8d3f5c27e19`).
* **Buyer personas are set on the ICP and nowhere else.** `verification.target_personas` reads ICP
  definitions only, and enrichment **refuses** an ICP that names no personas instead of enriching
  everyone. The ICP editor has a *Buyer personas* section writing `{buying_role, titles}` rows.
* **A service needs no ICP.** The ICP picks the *products/services to sell* (the link table is
  unchanged; only the direction of the choice is). Deleting a service's last ICP is allowed.
  Readiness now asks for at least one ICP that is for an active service and names buyer personas.

*Signals that matter* stays one list on the ICP, shown split into **company** and **contact** groups
by the scope each type carries on the Signal types screen — the split belongs to the type, so it is
not stored twice. This is what the research plan reads: company signals drive the company pass,
contact signals the per-person pass.
