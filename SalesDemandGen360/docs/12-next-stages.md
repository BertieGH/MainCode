# 12 — Documentation Audit and Next Stages

Written after the ICP rework ([09](09-vocabulary-rework.md), [11](11-icp-model.md)) landed, because
the specification is the context manifest every future session reads. A stale spec is worse than no
spec: it is read with the same trust as a correct one.

---

## Part 1 — What the documentation now gets wrong

Audited against the running code, not from memory. Each row was checked.

### Actively misleading — fix first

| Where | Says | Actually |
|---|---|---|
| `CLAUDE.md` | `docs/schema/*.sql` is **the schema reference**, prefer it over the markdown tables | The directory holds **one file**, `signals.sql`. The database has **48 tables**. A session told to prefer this reference gets 1/48th of the schema and no warning |
| `CLAUDE.md` | Python 3.12 · PostgreSQL 16 | Python **3.14.3** · PostgreSQL **17.9** |
| `CLAUDE.md` | `docs/01`–`07` is the specification | `01`–`11` now |
| `docs/05` §screens | `/settings/profile` — "Org profile and ICP definition" | That route is **deleted**. Its identity fields moved onto ICP profiles; the ICP moved to its own screen |
| `docs/05` §401 | "New industry → Settings → Org profile" | Industries live on ICP profiles; that path leads nowhere |

The `docs/schema` pointer is the dangerous one. It does not merely omit — it *redirects* a reader
away from the markdown tables, which are more complete, toward a file that covers one domain.

### Built but undocumented

Nothing in the specification describes these, and all three are load-bearing rules:

| Not written down | Where it lives now |
|---|---|
| **The capability gate.** `workable` (llm + enrichment) gates the menu; `ready` (all three) is the whole-installation answer; `requires(*kinds)` gates each route on what it uses. LGM blocks sending and nothing else | `api/deps.requires`, `readiness.WORKABLE_KINDS`, `tests/test_capability_gate.py` |
| **Email grading.** A provider's own verdict is carried, not assumed: Apollo's `guessed` becomes `risky` and does **not** satisfy the send gate. `APOLLO_LOCKED_EMAIL` is a paywall marker, never an address | `enrichment_clients.APOLLO_EMAIL_STATUS`, `ContactRecord.email_status` |
| **ICP tables.** `icp_profile`, `icp_profile_version`, `service_icp_link`, `account_list_icp`, `account_list_service` | Migrations `c81a3f60d4e7`, `d4b28e15a903`. Absent from `docs/03` |
| **New routes.** `/config/icp-profiles` (×4), `/lists/{id}/targeting` (×2), `verify-contacts` | Absent from `docs/04` |

### A real divergence between doc and code

**`docs/11` says persona matching is an LLM call. It is not.**

The document argues: *"The classification is an LLM call and the enrichment is an Apollo credit. The
former is far cheaper than the latter, so classifying before enriching pays for itself."*

`verification.matches_persona` is **case-folded substring matching** over title, persona role, buying
role and seniority. No model is involved.

That is not necessarily wrong — the substring version is cheaper still, deterministic, needs no
credential, and returns the three-way `True / False / None` the ranking depends on. But the
specification currently promises something the code does not do, and a future session reading
`docs/11` would either re-implement it or assume it exists. **Decide, then make one of them true**
— see Stage C.

### Plans that read as future work but are finished

`docs/09` and `docs/11` are written in the imperative — "to undo first", "becomes". Both are fully
built: archetype is gone from every file, `industry_multipliers` and `size_multipliers` are live,
`sizing.band_for` is wired into promotion and cadence, and the ICP tables carry real rows. Left as
they are, a session could reasonably start implementing them again.

---

## Part 2 — Next stages, in the order they should happen

### Stage A — Reconcile the specification *(one session, no code)*

Cheapest and highest leverage: every later session's accuracy depends on it.

1. Fix the five `CLAUDE.md` and `docs/05` errors above. For `docs/schema`, either generate the full
   DDL or **delete the claim** — a pointer to a partial reference presented as authoritative is
   worse than no pointer.
2. Fold the ICP tables into `docs/03` and the new routes into `docs/04`.
3. Write the capability gate and email grading into `docs/02` — they are architecture, not detail.
4. Stamp `09` and `11` as **implemented**, with the migration ids, so neither is re-done.

### Stage B — Finish Phase 9's outstanding screen

`docs/08` marks Phase 9 as ◑ — backend done, the arc review screen outstanding. It is the only
partial phase, and the frontend work this session (ICP profiles, targeting, list index) means the
surrounding screens now exist to hang it from.

### Stage C — Settle persona matching

Substring matching is live. Three options, and the choice belongs to whoever knows the lists:

- **Keep it, correct `docs/11`.** Free, deterministic, no credential. Fails on "Head of Platform
  Engineering" versus a target of `technical_buyer` — different vocabularies, no shared substring.
- **Add the LLM classifier the doc describes**, with the substring pass as a pre-filter so the model
  only sees what the cheap test could not decide.
- **Both, behind a config flag.**

The cost argument in `docs/11` still holds and is worth measuring rather than assuming: an LLM call
is roughly two orders of magnitude cheaper than an Apollo credit, so the classifier pays for itself
if it declines even a small fraction of a list.

### Stage D — Phase 12, Sales Prep

Held on 2026-09-05 "to finish the frontend first". That reason has largely expired — the frontend is
substantially further along. Not blocked by anything external.

### Stage E — Phase 13's promotion flow only

Learning needs outcomes and there are none. But the **promotion guard** — a detected pattern must
never reach live config without human review (`02 §8`) — is worth existing *before* the first
candidate appears rather than after. That part needs no data.

### Stage F — Phase 11, when LGM access lands

Still blocked on `docs/07` **Q3** (LGM auth and signature scheme) and **Q2** (CGVAK CRM API spec).
Guessing at a signature scheme produces a receiver that either rejects real callbacks or accepts
forged ones.

**One credential unblocks three things at once**: Phase 11, the `outreach` readiness slot, and the
two empirical LGM tests noted on Phase 10. It is the single highest-value external dependency in the
project.

---

## Recommended order

**A → B → C → D → E**, with **F** slotted in whenever the LGM account appears.

A first because it is cheap and everything after it is read through the specification. F is not
last by priority — it is last by availability, and it jumps the queue the moment the credential
exists.

---

## G · `ats_boards` earns its place or goes — **low priority**, owner's note (2026-10-08)

`ats_boards` is `status='active'` and has produced **no evidence in 31 attempts across two books** —
26 on the insurance brokerages, 5 on the enterprise sample. Both measurements say the same thing: a
fifteen-person brokerage runs no Greenhouse board, and even the EV and apparel companies in the
enterprise list expose nothing this reader can find. §96 measured why from the other side —
individual job postings appear in **0 of 35** sitemaps, and department paths in 0 of 35.

The owner's instruction is not to delete it but to give it a different shape:

* **A waterfall rather than one reader.** Greenhouse/Lever/Ashby detection is the current single
  path; a waterfall would try the ATS, then a jobs RSS or Atom feed, then the careers page the
  sitemap reader now finds reliably.
* **A jobs feed search.** Many boards publish RSS even where the API is hidden, and a feed is dated,
  which is the property this book is short of — §102's sample showed signals track the *dated*
  count, not the raw one.
* **IT roles only.** The value is never the headcount, it is the stack: a job advert asking for
  three years on a named platform is evidence that platform is running. A general hiring sweep buys
  warehouse and retail adverts at the same token cost and tells us nothing about an IT estate.

Note the one thing that already works here and should not be rebuilt: `engineering_team_expansion`
produced a signal for KORE Power from a **Lead Controls Engineer** advert, found through
`linkedin_index`, not through `ats_boards`. So the job-advert idea is sound and the route is wrong —
which is the argument for a waterfall rather than for more of the same reader.

Deliberately unsequenced. It is behind everything in A–F and the owner said so.
