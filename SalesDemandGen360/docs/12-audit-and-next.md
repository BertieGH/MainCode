# 12 — Where This Actually Stands, and What Comes Next

An audit of the specification against the code, and the sequence that follows from it.

Written because the specification had drifted from the build in both directions: some documents
described things that no longer exist, and the build contains decisions no document records. Every
later session reads through these files, so a wrong one costs more than a missing one.

---

## Part 1 — What the audit corrected

| file | was | now |
|---|---|---|
| `CLAUDE.md` | Python 3.12, PostgreSQL 16 | **3.14 / 17.9** — verified against the interpreter and `show server_version` |
| `CLAUDE.md` | "`docs/schema/*.sql` — the schema reference" | pointed at a real generated dump; `signals.sql` alone covered 1 of 47 tables |
| `CLAUDE.md` | no gate section | the `workable` vs `ready` split, which nothing recorded |
| `docs/02` | `org_profile.icp` feeds multipliers | union across active ICP definitions; new §5.0a on carrying a provider's verdict; new §11.4 on per-capability gating |
| `docs/03` | `org_profile.icp`, no ICP tables | five tables documented — `icp_profile`, `icp_profile_version`, `service_icp_link`, `account_list_service`, `account_list_icp` |
| `docs/04` | no ICP or targeting routes | seven routes added, with the `422`/`409` semantics that make them safe |
| `docs/05` | `/settings/profile` — "Org profile and ICP definition" | the real nav, dependency-ordered, and where company identity went |
| `docs/09`, `docs/11` | read as plans | stamped **IMPLEMENTED**, with what is genuinely still missing |
| `docs/schema/` | `signals.sql` only | `full-schema.sql` — all 47 tables, generated, with the command to regenerate it |

Two things the audit got wrong on the first pass and corrected on evidence, recorded because the
same mistakes are easy to repeat:

* **"Org identity is unreachable in the UI."** It is not — name and description are editable at the
  top of the ICP profiles screen. A grep for the wrong identifier said otherwise.
* **"The persona classifier is outstanding."** The *ranking* is built. The *classifier* is not — see
  below, and the distinction matters.

---

## Part 2 — Where the build actually stands

**831 backend tests, 216 frontend, all passing.** Phases 0–10 are real: configuration, credentials
and probes, account lists and CSV import, contacts and enrichment, signals and evidence, scoring,
queues, campaigns, cadence registration, drafting and approval.

### The thing worth knowing

`app/services/stages.py` defines **twelve** LLM call sites. Two have a caller:

| stage | callers |
|---|---|
| `research_family` | 1 — via `pipeline.run_research` |
| `evaluate` | 3 |
| `signal_scan`, `extract_signals`, `read_context`, `assess_dimensions`, `synthesise_strategy`, `draft_arc`, `generate_prep`, `revalidate_before_send`, `structure_manual_intel`, `enrich_decision_makers` | **0** |

And `pipeline.run_research` — the orchestrator that drives the research fan-out — **has no API
route**. It is written, tested, and unreachable from the application.

So the honest summary is: *the parts are built and the machine is not assembled.* That is a
different kind of remaining work from what has come before, and it should be planned as such rather
than treated as more of the same.

---

## Part 3 — What comes next

Ordered so each stage is usable when it lands, rather than by which is most interesting.

### Next — make research reachable

`POST /lists/{id}/run-research`, driving `pipeline.run_research` over a list's accounts, with the
list's services and ICPs deciding what the agents look for. Everything it needs exists; nothing
calls it.

This is the first stage where the app *does the thing it is for*, and it is one endpoint plus a
progress surface. It also proves the ICP work end to end: a list targeted at an ICP should research
differently from one targeted at another, and until research runs nothing demonstrates that.

**Watch:** research spends tokens per account. The same rule enrichment follows applies — explicit
action, never automatic on import.

### Then — the persona classifier

`matches_persona` is a casefolded substring test. It works and it is crude: "CTO" does not match
"Chief Technology Officer", "Head of QA" does not match "QA Lead". Every miss is a real buyer
counted as `out_of_persona` and never enriched.

[11](11-icp-model.md) argued for an LLM judgement here, and the economics hold: a classification is
far cheaper than an Apollo credit, so it pays for itself the moment it declines a modest share of a
list. It also produces `buying_role` as a by-product — a column currently populated by seed data and
nothing else.

**Do this after research**, not before: research output gives the classifier more to judge on than a
CSV title, and building it first means building it twice.

### Then — signals and qualification

`signal_scan` → `extract_signals` → `read_context` → `assess_dimensions`. Four stages, one chain,
and the point at which the six-dimension score becomes real rather than configured. Invariant 1
(no signal without evidence) is already enforced in `extraction._reject_reason`; this is what
finally exercises it.

### Then — strategy, drafting, approval

`synthesise_strategy` → `draft_arc` → `evaluate` → approval. The stages exist; the queue and
campaign machinery exists; the approval gate exists. This is assembly, not invention.

### Last — La Growth Machine

Deliberately last, and it is the one slot that cannot be verified: **every probe route returns 404**,
so `outreach` has no live credential check. Sending is also the only irreversible thing this system
does, which argues for it being the last thing wired and the most carefully tested.

Per §11.4 nothing else waits on it: `workable` covers llm + enrichment, so the whole pipeline up to
approved drafts runs without an LGM key at all.

---

## Part 4 — Debts, recorded so they are not rediscovered

| debt | cost if ignored |
|---|---|
| `matches_persona` is a table, not a judgement *(was a substring test; replaced 2026-09-11 by phrase + function + rank matching over ICP personas only — see `personas.py`)* | Genuinely odd titles still mis-sort; the LLM classifier remains the deeper fix |
| No LGM probe (all routes 404) | The outreach slot can never report `valid`; readiness stays partly unknowable |
| ContactOut response mapping unconfirmed | Routes were probed with an invalid key; the field mapping is inferred and logs `unrecognised_response` rather than guessing |
| `service_catalog.target_personas` still exists | Superseded by ICP personas; two sources for one idea, and the old one holds two taxonomies at once |
| `industry_key` normalises but does not alias | Apollo's `"information technology & services"` will not match `"IT Services"` when account enrichment lands — [09](09-vocabulary-rework.md) calls this Phase 2 and it is now due |
| `full-schema.sql` is generated | It drifts the moment a migration lands without a regenerate |

---

## Part 5 — What the specification still does not decide

`docs/07` remains the register of open questions. Nothing in this audit closes one; two are now
closer to needing an answer:

* **Q12 — runtime-editable query families.** The `runner` field added in [09](09-vocabulary-rework.md)
  is half of the shape `07` sketched. The rest becomes due when research agents run for real, which
  is the very next stage.
* **Retention of evidence snapshots.** Untouched, and it stops being theoretical the first time
  research stores a page.
