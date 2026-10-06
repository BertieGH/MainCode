# 13 — Corrections Log

Everything corrected since the build moved from specification to a working app, grouped by area.
Each entry says **what was wrong**, **why**, **what changed**, and **where**. Newest areas first.

Status at the time of writing (2026-09-11): backend suite passing (live-API Gemini tests excluded),
frontend unit tests **275 / 275**, both databases at migration `c7e2a9b4d153`.

---

## 1. Feedback on every screen

The plan: one confirm box, a working state on every action, outcomes in one place, real progress for
slow actions, reasons given before the click, and no premature "sent N" line.

| # | Problem | Cause | Fix | Where |
|---|---|---|---|---|
| 1.1 | Deletes, removes and rejects silently did nothing | The in-app browser suppresses `window.confirm` — it returned `false` in 45 ms without drawing anything | One in-app confirm box. It names the consequence ("Delete Test1? Its 12 accounts stay on their lists"). Escape cancels; **Enter confirms**; a focused Cancel still cancels | `shared/confirm.service.ts`, `shared/confirm-host.component.ts` — wired into all six former native dialogs |
| 1.2 | Promote gave no response, then failed | The server needs La Growth Machine; the refusal was shown above the fold and the card closed | Promote is disabled until LGM is connected, with "connect it in API settings" beside it. It reads "Promoting…" while running, and on failure the card stays open with the reason in the corner | `shared/readiness.service.ts`, `queues/queue-detail.component.ts` |
| 1.3 | Outcomes were missed | Error boxes and report lines were pinned at the top of the page, out of sight once scrolled | Corner notices. Success clears itself; partial results and errors stay until dismissed and carry the server's reason; **Retry** appears only where safe (a network or server fault on an idempotent action) | `shared/notify.service.ts`, `shared/toast-host.component.ts` |
| 1.4 | Buttons could be double-clicked, with no sign of work | No working state | Shared `.btn.busy` spinner. The table's bulk bar and row menu disable while an action runs, the running button reads e.g. "Deleting…", and a "Working…" strip shows even with nothing selected | `styles.css`, `shared/data-table.component.ts` (`busyKey`, `busyText`) |
| 1.5 | Resolve, enrich and research showed a spinner that never moved | One request for the whole selection | Runs one account at a time in the browser: "Researching 3 of 8… 0:42", a bar, results so far, and **Cancel** (stops before the next account, never mid-request) | `shared/sequential-run.ts`, `shared/run-progress.component.ts`, `lists/list-detail.component.ts` |
| 1.6 | "Sent N" appeared before the confirmation was answered | The table announced the bulk action itself | Removed. The screen reports what actually happened | `shared/data-table.component.ts` |
| 1.7 | Execute, Stop sequence and Stop campaign had no confirmation | Never added. All three are irreversible | Confirmations that say what cannot be undone, plus working states and notices | `campaigns/campaign-detail.component.ts` |
| 1.8 | An identity save error appeared in the targeting band | Wrong error signal reused | Corner notice naming the account | `lists/list-detail.component.ts` |

**Working state per screen**

| Screen | Actions covered |
|---|---|
| Account lists | New list (both buttons), Delete |
| List detail | Save targeting, Resolve, Accept / Reject / Edit / Change identity, Enrich, Research, Rerun research, Add to queue, Remove from list |
| Queues / queue detail | New queue, Clone, Delete, Add accounts, Remove members, Promote, Delete queue |
| Outreach / campaign | Delete, Approve, Reject, Redraw, Approve sample, Execute, Stop sequence, Stop campaign |
| Settings | Services edit, Research reuse window |

Page-load failures still show at the top of the page. They are the page's state, not an action's
outcome. Form mistakes still show next to the field.

Dead code removed along the way: `queues.remove/clone`, `queue-detail.addSelected/remove`,
`campaigns.remove`. All of it was unreachable, and all of it wrote to the old top-of-page box.

---

## 2. Research

| # | Problem | Cause | Fix | Where |
|---|---|---|---|---|
| 2.1 | The Research column said `not_started` beside "1 researched" | The pipeline wrote runs and coverage but never `account.research_status` | Set to `complete` / `partial` / `failed` from the families' outcomes | `services/pipeline.py` |
| 2.2 | "1 researched · 0 evidence rows" when nothing had been looked at | An account was counted as researched unless it halted, even when every family failed | Honest counts: researched, partial, failed, halted. Each reason is given once, not once per family | `api/lists.py` |
| 2.3 | Evidence had no run to trace back to | The route built the family runner without the run id | One id shared by the run and its evidence | `api/lists.py` |
| 2.4 | Research on Gemini found nothing and reported "empty" | The Gemini adapter sent no web tools, so the model answered from memory | **Google Search grounding.** An answer counts only if it can be shown to have searched (a search-result link, or prompt tokens clearly above the request's own count). Evidence is kept only if its link came from a search result, resolved to the real page. A recitation refusal is retried once with shorter quotes | `services/gemini_grounding.py`, `services/gemini.py` |
| 2.5 | An empty family said only "nothing found", and a family could not be opened | Coverage did not keep what was searched; evidence did not record its family | `research_coverage.not_found` and `evidence.family`. Coverage rows expand to show passages with links and "searched, not established" | migration `e5b1c08d7a42`, `api/intelligence.py`, `accounts/account-detail.component.ts` |
| 2.6 | A second list paid again for the same company facts | No reuse | **Reuse window**: 30 days by default, adjustable. Fresh families are skipped, a fully fresh account is reported "reused" at no cost, and **Rerun research** ignores the window after a confirmation. Coverage shows the latest result per family with its date | migration `b3e9d7c41a58`, `services/research.py`, `settings/research.component.ts` |
| 2.7 | Accounts beyond 5 per click were silently skipped | A per-request cap that nothing reported | Reported as "not started — over the per-run cap" (and gone in practice now, since research runs one account per request) | `api/lists.py` |

---

## 3. ICPs, services and personas

| # | Problem | Fix | Where |
|---|---|---|---|
| 3.1 | Services held a persona list, in two vocabularies (titles on one service, buying roles on another), and it fed matching alongside the ICP | Replaced by **Economic buyer**, one line of context. Existing values were copied across as text. Services can now be edited | migration `a8d3f5c27e19`, `settings/services.component.ts` |
| 3.2 | A service had to have an ICP | Not any more. The ICP picks **Product/services to sell**. Readiness asks for one ICP that is for an active service and names personas | `services/readiness.py`, `api/config.py` |
| 3.3 | Buyer personas had no home | A **Buyer personas** section on the ICP (buying role plus titles). Enrichment refuses an ICP that names none. Default was given v2: economic buyer CEO; technical buyer CTO, CIO, IT head | `settings/icp-editor.component.ts`, `services/verification.py` |
| 3.4 | Signals that matter were one flat list | Shown as **Company** and **Contact** groups using each type's scope from the Signal types screen. Still stored once | `settings/icp-editor.component.ts` |
| 3.5 | VP of Sales, VP of Business Development and a Chief Security Officer counted as CEO-level buyers; Managing Director did not | Matching works on phrases ("vice president", "managing director", "business development" as one unit). Running the company is its own function; a different function never matches; buying roles match only a contact's buying role | `services/personas.py` |

---

## 4. Earlier corrections (lists, tables, identity, import)

| Problem | Fix |
|---|---|
| Apollo not usable; an invalid key stored and shown as valid | `ApolloProvider` built. Invalid credentials are shown as invalid and can be deleted; credentials never reach a prompt or log |
| No simple way to start or stop the app | `RunDemandGen360.bat` and `CloseDemandGen360.bat`. Both bind 127.0.0.1 so the browser origin matches |
| Company size typed freehand | Selectable bands 1–50 … >1000, stored as one range |
| Archetype multipliers were a fixed, drifting set | Replaced by industry and size multipliers derived from the ICPs |
| Enrichment ran over everyone | Gated on a service and an ICP, and ranked by persona |
| Research could run on the wrong company | Tier-0 identity resolution (Apollo, then web fallback), a curation screen (Accept / Edit / Reject / pick a candidate), and research refused until confirmed |
| An xlsx file could not be read; a website column was missed | xlsx parser with header sniffing, and a column-mapping screen |
| A fixed nine-column table and a separate filter panel | Shared table on every list screen: Refine view, column picker, resize, filter on any column, row selection, bulk bar that counts eligible rows, pinned row actions |
| "Remove from list" deleted accounts | Now removes membership only. List delete removes orphaned accounts and reports how many were kept |
| Queue bulk add aborted on a stale id | Existence checked first. Queue eligibility enforced server-side, naming each refusal |
| Refine view would not collapse; list pages were narrow | Global `[hidden]{display:none!important}`; page width limit removed |
| Sorting some columns returned 422 | Sort allowlists widened; per-account contacts join added |
| The row menu would not close | Outside click, Escape and scroll close it |
| A 409 named every capability, not the missing one | The message names only what is missing |

---

## 5. Contact research (built 2026-09-11)

Research looked at companies only, so the ICP's contact signals could never be found.

* **Plan from the list's ICPs**: their company signals decide the company families, their contact
  signals the families run about people (fallback: the whole registry when an ICP names none).
  `research.plan_for_list`.
* **Who**: per account, up to 3 contacts matching the ICP's buyer personas **with a verified
  email**, LinkedIn first, then seniority. Nobody eligible → the company part still runs and the
  report says "run Enrich contacts first". `research.contacts_to_research`.
* **One run, two passes**: one search call per contact family for all chosen people; every passage
  tagged with whose it is — an id we did not send is **dropped**, never guessed (a namesake's job
  change is worse than no evidence). Own instructions demand the person and company appear
  together. `pipeline._contact_pass`, `pipeline.llm_contact_runner`, `stages.research_contacts`.
* **Stored per person**: `evidence.contact_id`, coverage per (run, family, person) with NULLS NOT
  DISTINCT, the reuse window per person, `run.icp_version_ids` for traceability. Migration
  `c7e2a9b4d153`.
* **Seen**: the account's Research coverage tab has a table for the company and one per person;
  the research notice counts contacts researched.

## 6. Signal extraction, wired (2026-09-11)

`extract_signals` was written, tested and called by nothing: research stored evidence and stopped,
so every account read `Signals 0` beside a coverage table full of passages.

* **Runs last in the research run**, on everything held for the account (newest 80 rows), not only
  what this run found — a funding round found last week is part of what this week's hiring means.
  `pipeline._extract_signals`, `pipeline.llm_signal_extractor`.
* **Offered only the ICP's signal types** (`ListPlan.type_keys`), so a type whose family was never
  run cannot be extracted from evidence nobody looked for.
* **Contact signals can name a person**: the stage is given the people researched, and each
  evidence row says who it is about (`about_contact_id`).
* **Dropped signals are recorded, not only logged.** A conclusion citing evidence that does not
  exist is refused by the guard (invariant 1) and written to `evaluation` against the run —
  `warn` when some were stored, `fail` when none were. A rising drop rate is the earliest sign an
  extraction prompt has drifted.
* **A failure costs the signals, never the research**: the run goes `partial`, the evidence stays,
  and a rerun reuses the families inside the window so only the reading is paid for again.
* Also corrected: `CLAUDE.md` described the app as calling Claude. Every stage runs **Gemini**
  (`llm_config`); the section now says so and names the dialect gaps that matter.

## 7. Qualification, wired (2026-09-11)

`scoring.py`, the six-dimension contract, `context.py` and both model stages were written and
called by nothing. The chain now ends: evidence -> signals -> context -> six dimensions -> a score
computed in Python.

* **Order.** A context *version* is written first (immutable — a strategy, a draft and an approval
  all cite one). The model's narrative overlay is merged into it, with any theme citing a signal
  outside the context dropped. Then the six dimensions are judged against that context and the
  evidence, and **never** asked for a priority score: the roll-up is deterministic over a versioned
  `scoring_config` (invariant 7). `services/qualification.py`.
* **A citation that does not resolve costs its dimension, not the account.** Unknown ids are
  stripped; a dimension left standing on nothing scores 0 and is marked `unsupported` — a different
  word from `no_evidence`, because "nobody contacted them" and "the model claimed this and could
  not back it" are different facts. Recorded in `evaluation`. Refusing the whole qualification was
  rejected: it blocks nothing (an unscored account still queues) and hides the reason, while a
  scored one carries a proportional penalty — one unsupported dimension took a worked example from
  61.95 to 51.75, two to 40.20, all of them to 0.
* **Runs twice over.** At the end of a research run, and as a **Qualify** action for accounts that
  already hold signals (two model calls, no provider credits). An account with no live signals is
  not scored at all — zeros would rank it against a judged one.
* **A failure costs the score, not the research**: the run goes `partial`, evidence and signals stay.
* **The queue gate.** `scoring_config.min_queue_band` (migration `d1f4b7a92c60`), default `low` =
  no restriction. Above it, `promotion.queue_ineligibility` refuses a weaker band by name — and an
  account with no qualification at all, saying "not qualified yet". Set on the Scoring screen.
* **Seen**: a sortable **Priority** column on the account list (unjudged accounts sort last, not
  first, which is what the `coalesce` in `_account_sorts` is for); the Qualification tab shows each
  dimension's basis, including `unsupported`, plus the narrative — themes, what changed, and what
  is still unknown.

## 8. Reuse skipped the reading (2026-09-12)

An account researched before extraction existed held evidence nobody had read, and could not catch
up: its families were inside the 30-day window, so **Run research** reported it `reused` and
skipped the account entirely — including the interpretation, which costs no search at all. Seen on
BlueWave: 15 passages, 0 signals, and no way to change that for thirty days.

Reuse now skips the paid search only. When an account holds evidence newer than its newest signal
(or has none), the run proceeds with every fresh family still skipped: no provider call, and the
evidence is read into signals and scored. `research.has_unread_evidence`, `api/lists.py`.

## 9. The outreach gate was wider than the dependency (2026-09-12)

A missing La Growth Machine credential shut **Campaign Queues** and **Outreach** in the menu, and
`POST /campaigns` required it. None of that work touches LGM: a queue is built from lists,
promotion locks the queue and copies strategy threads, drafting and approval are model and rep
work. Only `execute` enrols leads — as the route's own comment already said: "the only place a
missing LGM credential should stop anybody."

So the gate now sits on the send alone. Promote requires `llm`; the menu locks only on the setup
gate (`workable`); the queue screen and the campaign's Execute tab each say plainly that sending
needs LGM and that everything before it does not. `api/campaigns.py`, `app.component.ts`,
`queues/queue-detail.component.ts`, `campaigns/campaign-detail.component.ts`.

## 10. Research was reading less than it could (2026-09-12)

Two gaps, both cheap to close.

**Three families never ran.** The plan is derived from the active signal types' `produced_by`, and
with five types configured nothing claimed `news`, `tech_stack` or `reviews`. Four types now do —
`product_launch`, `partnership`, `tech_adoption`, `delivery_quality_theme` — added by
`scripts/enable_more_families.py` (idempotent, dry run by default) along with a Default ICP v3 that
names them. The Test Data plan went from **3 company families to 7**.

**Nothing read the company's own site.** New family `company_site`, and a new runner kind —
`fetch` — for work that needs no model: discover the feed a site advertises (or the conventional
paths), parse RSS or Atom, keep the newest ten entries inside eighteen months, and store each as
evidence with the company's own words, its own date and a link. `robots.txt` is honoured, because
this product sends email from the same domains it reads. `services/site_sweep.py`.

Live on bluewave.net: **10 announcements in 1.2s**, newest 10 Sep 2026 — against an account whose
only signals were leadership changes that expired in August. stripe.com has no feed at any
conventional path and records `empty` with that reason in 0.9s.

*Defect found by running it:* the first cut fetched `robots.txt` before every candidate URL and
tried ten paths at a 15-second timeout — over two minutes for one family on a site with no feed.
Now: robots fetched once per host, five candidates, eight-second timeout.

*Not attempted:* LinkedIn. All API access is partner-gated and its terms ban using member data to
identify prospects or enrich records; company posts need admin of the page. The legitimate routes
are La Growth Machine's own enrichment (the user's session, ~28 data points) and whatever Google
has indexed, which grounded search already reaches.

## 11. Retrieval is by source, not by signal type (2026-09-12)

Research asked one search per signal type. The evidence against that came from its own numbers,
after a day of running it: `funding` had been searched 16 times and produced 2 passages,
`hiring` 16 times for 5 — while `company_site`, a single undirected read of a company's own feed,
produced **10 from one attempt**. Narrow queries about a company with a thin web presence return
nothing, and we were paying per narrowness.

The change separates two questions that had been answered by the same object:

* **Retrieval** is decided by **sources** — places worth reading. Configuration now, in
  `research_source`, seeded from the ten shipped families under their original keys so every
  coverage row already written still resolves.
* **Interpretation** is decided by signal types and reads **everything**. A document costs the same
  to digest whether one conclusion is drawn from it or twenty, so a leadership change mentioned in
  a job posting is a leadership change. `ListPlan.type_keys` now returns every type the ICP asked
  for rather than only the ones each source was expected to feed, and the research prompt says so
  in as many words: the listed conclusions are context for what counts as notable, not a filter.

**Where each decision lives.** A signal type names the sources its fact usually appears in — a
class of place, never a URL, because that is true for every account. An **ICP** names the set that
actually runs, which is the plan of record: the same places read for every account on its lists,
which is what makes "nothing found at Apex" a fact about Apex rather than about what somebody
decided to look for that day. It is versioned with the ICP, so a run in August stays explainable
after somebody edits sources in October. Both are drafted by the model and neither is applied by
it — `POST /config/signal-types/suggest-sources` fills a form a rep is already typing into, and
`POST /config/icp-profiles/{id}/suggest-sources` assembles the ICP's set with a reason per source.
Keys the model invents are dropped; somewhere genuinely worth reading comes back under
`new_sources` for a person to add on purpose.

**The exception stays.** `search_instruction` on a signal type is now an *extra* search run
alongside the sources rather than instead of them — for what a sweep of the ordinary places
reliably misses, like a filing found only by name. Claiming a source and writing an instruction
both run; the previous cut silently dropped the instruction, which would have lost the thing it
was for.

**What the design gives up, and what pays for it.** Per-conclusion absence: "we looked for funding
and found nothing" becomes "we read these places and nothing supported funding". That is weaker,
and the exception searches are where it is bought back for the conclusions worth it. The cost
arithmetic is on both screens, because a registry only ever grows.

**Two things that keep the registry honest.** `sources.health` reports reads and passages per
source across 90 days and flags one tried five times that produced nothing — a prompt to look, not
a verdict. `sources.quarantined` stops reading a source at an *account* after three consecutive
failures, per account because a site blocking our agent blocks it for that company only; the run
records those as `skipped` **with the reason** rather than dropping them, since a source that
silently stops being read is a hole that looks like a quiet prospect.

*What did not change:* an unknown source key is still refused. That check moved from a Pydantic
validator over a code constant to `sources.validate` over the table, because the failure it
prevents is silent — a claimed source nothing runs reports forever as a coverage gap on a prospect
who is perfectly well covered. The old `query_families.validate` was deleted rather than left
beside it: two validators would mean a key retired in the registry still passing one of them.

Migration `a3c6e820f7d1`. `services/sources.py`, `services/research.py`, `services/stages.py`,
`api/config.py`, `settings/research.component.ts`, `settings/signal-types.component.ts`,
`settings/icp-editor.component.ts`. 1107 backend tests, 284 front-end.

## 12. Fit was a coin toss, a pain point had no type, and country never arrived (2026-09-13)

A rerun on BlueWave moved its priority from 69.75 to 54.50 with nothing new learned. Three causes.

**Fit was judged by the model, and the model was inconsistent.** 75 one run, 0 ("no evidence") the
next, from the same headcount and the same passages, one of which the same run cited for
*commercial*. Fit needs no model: size, industry and country are columns, and the ICP states what it
wants. `services/fit.py` compares them and the model's fit is replaced whenever a list's ICPs are
known, stored under basis `firmographics` with a reason naming both sides of every comparison.
Unknowns are named and not counted; an excluded industry is 0; the best ICP of a list wins. Industry
matching makes no leaps (see `scoring.normalise_industry`), so a mismatch caused by the ICP's
vocabulary is visible rather than silently mapped. BlueWave's fit is now **50** on every run: 160
people is inside 50-500, *information technology & services* is not one of SaaS, Logistics,
Fintech, Insurance, and there is no country to check. Priority 63.50. Note the old 75 was also wrong
— the industry was never in the ICP.

**A company-stated pain point had nowhere to go.** `public_pain_statement` is contact-scoped, so
extraction filed a company statement under it and the guard dropped it for having no person. Added
`company_pain_statement` (company scope, sources `company_site` and `news`) to Default ICP v6, gave
`public_pain_statement` the description it lacked, and told extraction that who said it decides
scope — and that a vendor describing its *customers'* pain is marketing, not its own need. On the
rerun BlueWave's AI-spend statement became `public_focus`, which is what it was.
`scripts/add_company_pain_type.py` (idempotent, dry run by default).

**Country never reached a prompt.** The account block read `hq_location`, which the account does not
have; the columns are `hq_country` and `hq_region`. Every research, extraction and qualification
prompt was told nothing about where a company is. `services/stages.py`.

`services/fit.py`, `services/qualification.py`, `services/research.py` (`ListPlan.icps`),
`api/lists.py`, `services/instructions.py`, `accounts/account-detail.component.ts`. 1132 backend
tests, 284 front-end.

## 13. One fact from one page was stored once per quote (2026-09-13)

A BlueWave rerun wrote CBTS's 2024 partner award as a second signal. Dedupe matched on type, date and
a **shared citation** — but evidence dedupes on the exact passage, so the same page quoted differently
on two runs is two passages, and the two signals shared none.

Now a new reading is the same fact when type, date **and person** match and either it shares a passage
(as before) or it comes from **the same page with a summary that says the same thing** — word overlap of
0.6 or more. The threshold was set from the real pairs: the $75m round worded twice is 0.73 and the CBTS
award 0.93, while "appointed Drew Cather as CRO" beside "acquired CloudZen and appointed executives",
one release on one day, is 0.25 and stays two signals. A different wording that falls below 0.6 is
stored twice: the cheaper mistake, since collapsing two facts loses one. Two other gaps closed on the
way: the person is part of the key, so one article naming two new VPs is two role changes rather than a
duplicate; and a fact repeated inside one batch is now caught, not only one repeated across runs.

**History.** `scripts/supersede_duplicate_signals.py` applies the same rule to signals already stored and
points each later copy at the original through `superseded_by` — never a delete, since a signal can be
cited. Stricter than extraction: it only marks rows whose summaries also agree, so the Drew Cather /
CloudZen pair, which share a passage but say different things, was left alone. **2 marked on BlueWave**
(the 2022 funding round and the CBTS award). Superseded rows no longer appear on the Signals tab;
`context.live_signals` already skipped them.

*Test changed:* `test_one_bad_citation_drops_only_that_signal` stored three "good" signals reading one
passage on one date — one fact, now correctly counted as duplicates. They carry a date each, keeping the
test on its subject.

`services/extraction.py`, `api/intelligence.py`, `tests/test_extraction_guard.py`. 1143 backend tests.

## 14. Intent cited signals as if they were evidence (2026-09-13)

A BlueWave re-read scored intent 0, `unsupported`, and priority fell to 50. The reason text was
unchanged from the run before; all three citations had been stripped. The context showed why: it listed
exactly three live signals, and its narrative theme "Sustained AI Infrastructure Thought Leadership"
cited those three by `signal_ids`. Intent's reason was that theme, and it had copied the theme's three
signal ids into `evidence_ids`. The assessment payload lists signals by `id` and evidence by
`evidence_id`, and nothing told the model the two are different things.

**The guard resolves a signal id through its evidence.** `qualification.resolve_citations`: an id that is
one of *this context's* signals becomes the evidence rows behind that signal, provided the assessment was
shown them. Invariant 1 is untouched — every id that survives is still an evidence row — and a signal from
another account, or one no longer live, is not in the map and is stripped like any unknown id.

**The ids are recorded.** The evaluation row now names, per dimension, the ids that resolved to nothing
and the signal ids resolved through their evidence (`qualification-guard-2`,
`scores.citations_via_signal`). The first diagnosis here had to be reconstructed from the stored context;
the next one can be read off the row.

**The prompt says it.** `qualification_assessment`: `evidence_ids` take `evidence_id` values only; a
signal's `id` and a theme's `signal_ids` are not evidence.

On the next re-read intent scored **90** citing three real BlueWave passages directly, with no evaluation
row written, and priority is **68.25**. The fallback was not needed on that run; it is covered by tests,
including a signal of another account that must not resolve.

`services/qualification.py`, `services/instructions.py`, `tests/test_qualification.py`. 1149 backend tests.

## 15. The remaining dimensions: facts computed, judgements held steady (2026-09-13)

With fit computed, five dimensions were still whatever the model said that run. Across BlueWave's six
qualifications opportunity read 70-85, buyer 65-75 and commercial 75-85 over near-identical evidence.
Two different problems were hiding in that, and they get two different fixes.

**Buyer and engagement are facts, so they are computed** (`services/dimensions.py`). The spec asks buyer
"can we reach someone who can say yes?" — contacts, seniority, verification — and the model had scored
BlueWave 75 from leadership news while not one of its contacts had an email or LinkedIn profile. Buyer is
now, per ICP buyer persona, the most reachable matching contact (verified email 1.0, risky 0.6, LinkedIn
0.5, unverified email 0.4, name only 0.15, nobody 0), averaged, best ICP wins. BlueWave: **7.5** —
"economic buyer (CEO): Marcus Chen, Managing Director — no working email or LinkedIn yet; technical buyer:
nobody at the account matches". Engagement is outreach history: touches sent through sequence → thread →
contact, and a reply when a sequence stopped on one (75; meetings are not recorded yet). Sending alone is
0, said as such. Both are recomputed on every run.

**Opportunity, commercial and intent stay judgements, held steady two ways.**
*Steps:* the prompt now carries a written rubric — 0 / 25 / 50 / 75 / 100 with what each means, and what
each dimension asks (opportunity is read against the service catalogue, not generic good news) — and
Python rounds whatever comes back to the nearest step, ties up. *Unchanged inputs are not re-asked:* each
qualification stores a fingerprint of everything the model would be shown and how (evidence ids, live
signal ids, account facts, the prompt prefix, the model, `RUBRIC_VERSION`). When a later run matches, the
judged dimensions are carried forward and no call is made — the only real guarantee that the same inputs
give the same judgement, and a cheaper run. A previous qualification with an unsupported dimension is never
carried forward.

**Live on BlueWave, three re-reads.** Run 1 judged afresh: **46.13**. Run 2 extracted one new signal, so
it judged again: **42.38**. Run 3 found nothing new and kept run 2's judgement unasked — *"nothing changed
since the last run, so its judgement was kept"* — at an identical **42.38**. BlueWave moved from medium to
**low**: buyer 75 → 7.5, and the model, now asked against the catalogue, puts opportunity at 25 on both
runs — "their primary business is technology advisory and MSP services rather than product engineering".
That agrees with fit (IT services is not a Default industry).

*What this does not stop:* commercial read 100 then 75 across runs 1 and 2, when the only new input was an
unrelated signal. Any change to the inputs re-judges every judged dimension, and a judgement can still
move one step. *And a gap it exposed:* that new signal was a fourth `public_focus` about the same run of
BlueWave blog posts, dated 11 Aug where the others are 13 Aug, 25 Aug and 10 Sep. Dedupe keys on the date,
and an ongoing theme gets whichever post's date the model picked — so re-reads keep adding it, which also
keeps the inputs changing.

*Tests changed:* three `test_qualification.py` assertions on exact judged scores (82, 45, and the 68/77
penalty) now expect their steps. `services/dimensions.py`, `services/qualification.py`,
`services/context.py`, `services/instructions.py`, `api/lists.py`, `accounts/account-detail.component.ts`.
1193 backend tests, 284 front-end.

## 16. An ongoing theme was stored once per re-read (2026-09-13)

BlueWave held four live `public_focus` signals about one run of blog posts, dated 11 Aug, 13 Aug, 25 Aug
and 10 Sep, and nearly every re-read added another. Dedupe keys a fact on its date, which is right for an
event — two funding rounds are two facts — and wrong for a theme: what a company keeps publishing about has
no single date, so the model dated each reading by whichever post it picked. Every new copy also changed
the inputs, which stopped a qualification's judgement from ever being kept (section 15).

**A signal type is now an `event` or a `theme`** (`signal_type.kind`, migration `b8d2f4a61c93`; editable
on the Signal types screen). Events keep the old rule. A theme keeps **one live signal per account and
person**: a reading dated no later than the one held is a duplicate, whatever it says; a reading dated
later is stored and every older live reading is superseded by it — so the theme moves forward with its
newest post and its expiry runs from there instead of lapsing while the posting continues.
`public_focus` and `delivery_quality_theme` are themes by their own descriptions; everything else stays
an event. `extraction._current_themes`.

**History.** `scripts/supersede_duplicate_signals.py` gained a theme pass: the newest live reading stands
and the older ones point at it. **3 marked on BlueWave**, keeping 10 Sep. A re-read afterwards added no
`public_focus` at all (5 duplicates caught); its one new signal was a genuine fact — the November 2025
Technology Navigation acquisition.

**Found on the way.** `SignalTypeOut` never returned `search_instruction` or `search_group`, so the Signal
types screen showed every type as having no extra search whatever was saved, and the ICP's extra-search
count was always 0. Both are returned now, with `kind`.

*Still true:* when the inputs change, the judged dimensions are asked again and can move a step — on that
re-read opportunity went 25 → 0 and priority 42.38 → 37.38.

`models/config.py`, `schemas/config.py`, `services/extraction.py`, `scripts/supersede_duplicate_signals.py`,
`scripts/enable_more_families.py`, `settings/signal-types.component.ts`, `core/config.service.ts`.
1202 backend tests, 284 front-end. Schema dump regenerated.

## 17. Research could not see a company's open roles (2026-09-13)

Hiring is the trigger this product leans on hardest, and research saw it least clearly. A careers page
renders its openings with a script from the applicant-tracking system, so what a search brought back was
the container: BlueWave's careers page came back as *"Embedded script required to load and display active
corporate job openings from Greenhouse"*, and `engineering_scaling` — described and made a theme the same
day — had nothing to read.

**New source `job_board`** (`services/job_boards.py`, migration `c4e1a7d9f2b5`, a builtin `fetch`
source beside `company_site`). It finds the Greenhouse board the company's own site names — the embed
script, a hosted board link or an API call on the homepage, the careers pages it links, then conventional
paths, four pages at most, robots honoured — and reads every open role through Greenhouse's public API:
title, team, location, the opening of the description, **dated by `first_published`**, not `updated_at`
(BlueWave's associate role opened 29 Jan and was edited 1 Sep; it is not a September hire). One evidence
row per role, 25 at most, newest first. No model call.

**A board is never guessed from a company name.** A guessed token would sooner or later read a namesake's
openings as this account's hiring — the wrong-person failure contact research already guards against. No
board named means `empty` with the reason, and "the board has no open roles" is recorded as the finding it
is.

The pipeline used to send every `fetch` source to the feed reader. Each now has its own reader, and a fetch
source with none fails by name rather than being read by the wrong one.
`scripts/add_job_board_source.py` added `job_board` to the Default ICP (v7) and to what
`engineering_scaling` expects.

**Live on BlueWave:** the board read in 1.2 s — 3 open roles: Solution Advisor, Cloud & Infrastructure
(4 Sep); Business Development Director, Regional Healthcare (30 Mar); Corporate Development Associate
(29 Jan). None is engineering, so no `engineering_scaling` signal — the right answer, now from the company's
complete list rather than inferred from its absence. A research run read only the new source and reused the
other eight inside the window. stripe.com, which runs its own jobs site: *"no Greenhouse job board found on
stripe.com — read 4 pages"*.

*Not covered yet:* Lever and Ashby publish the same kind of API and fit the same shape — each needs its own
token pattern and parser.

`services/job_boards.py`, `services/pipeline.py`, `services/query_families.py`,
`scripts/add_job_board_source.py`, `tests/test_job_boards.py`. 1224 backend tests.

## 18. The job board reads Lever and Ashby too (2026-09-13)

`job_board` read Greenhouse only. Lever and Ashby host the other large share of software companies' boards
and publish the same kind of unauthenticated API, so one source now reads all three — which system a
company uses is a fact about the company, not something a rep chooses. `services/job_boards.py`.

* **Lever** — `api.lever.co/v0/postings/{company}?mode=json` (and `api.eu.lever.co` for an EU board): a bare
  list; title from `text`, team and department and location from `categories`, dated by `createdAt`
  (milliseconds — Lever keeps no "updated"), `descriptionPlain` or else `openingPlain`.
* **Ashby** — `api.ashbyhq.com/posting-api/job-board/{board}`: title, department and team, location,
  dated by `publishedAt`. A job with `isListed: false` is skipped — reachable by link but not advertised,
  so the company has not said it is hiring for it.

Discovery is unchanged in principle — only a board the company's own site names, never a guessed one — and
now finds any of the three, in the order the page names them. Each API's shape was taken from its live
answer, not recalled. Linear links its board as `jobs.ashbyhq.com/Linear/…` where the API wants `linear`,
so a board that does not answer under the spelling on the page is asked once more lower-cased.

**Live:** Palantir (Lever) 311 open roles, newest 25 kept and the rest noted; Linear (Ashby) 30, found
through the capitalised link; Ramp (Ashby) 145; BlueWave (Greenhouse) unchanged at 3. Of the twelve Test
Data accounts only BlueWave runs one of the three.

**Found by running it: a dead site cost 40 seconds.** Three Test Data domains do not answer, and discovery
made five requests to each at an eight-second timeout before concluding "no job board". The robots.txt it
fetches first is now also the reachability check: no answer, and it stops with *"… did not answer — no
careers page could be read"*; an answer is kept for the robots check, so a live site pays nothing extra.
40 s → 8 s on each.

**`company_site` had the same walk, and now the same check** — shared as `site_sweep.answers` rather than
copied, so both readers ask once. The three dead domains: *"… did not answer — no feed could be read"* in
8 s. BlueWave's feed is unchanged: three requests (robots.txt, the homepage, `/feed`), 10 announcements,
about a second.

`services/job_boards.py`, `services/site_sweep.py`, `tests/test_job_boards.py`, `tests/test_site_sweep.py`,
migration `d7a3b5c8e2f6` (the source's description, updated only if still as seeded). 1244 backend tests.

## 19. LinkedIn, reached only through what points at it (2026-09-13)

Research held no evidence from linkedin.com at all. The rep-made `linkedin_profile` source asked it to
"browse direct", and in fifteen runs it stored nothing. Browsing direct is also the one thing this
product may not do: LinkedIn's robots.txt forbids automated access without permission, its user
agreement bans scraping, hiQ ended in a $500,000 judgment and Proxycurl shut down after being sued. The
official APIs do not help either — page posts need admin of the page, and Sales Navigator's partner
programme is closed. Decided with the user: no paid search API and no licensed data vendor for now.

**`services/linkedin.py` understands a LinkedIn URL without fetching it.**
* *When a post was published* — a LinkedIn activity id's top 41 bits are milliseconds since the epoch,
  so the date is in the URL. Applied wherever evidence is stored, when the source gave none. Verified on
  a real post URL: Proxycurl's shutdown notice decodes to 16 Jul 2025.
* *Whose it is* — company page, profile or post author, by slug. A LinkedIn passage from a different
  company page or person is dropped and counted (`pipeline.keep_own_linkedin`, and per person in the
  contact pass); an unanswerable case — no page on record, an article with no owner — is kept.
* *Which page a homepage links* — `company_site` now reports the LinkedIn company page the homepage
  links, and the pipeline records it on an account with none. Exactly one, or nothing: a site linking
  two is ambiguous.

**A builtin `linkedin` search source** (migration `e2b9d4a7c1f3`) with a brief that can be followed —
what search engines show of the company page, its posts, and each person's profile and posts, identified
by the LinkedIn URL on record — and **search only**: it carries web search without the fetch tool, so
the model cannot open a linkedin.com page on its own say-so. `scripts/use_linkedin_source.py` paused
`linkedin_profile` (not retired), put `linkedin` in its place in Default ICP v8, and added it to what
`public_focus` and `public_pain_statement` expect.

**A rep can paste what they saw** — `POST /accounts/{id}/pasted-evidence`, and a box on the account's
Coverage tab. Stored as `manual` evidence, attributed (author `rep` — there is no sign-in yet — capture
`other`), about the company or a contact at it, dated as given or from the post link or not at all,
never today. Refused: a contact at another company, the same passage twice, a future date. It becomes
signals on the next Re-read & score.

**Live, and honest about what it gave.**
* BlueWave research ran the new source: `empty` — it searched `site:linkedin.com/company/bluewavetg`
  and `site:linkedin.com/posts/bluewavetg` and Gemini's grounded search surfaced nothing from LinkedIn.
  Without a search API that indexes LinkedIn well, this rung will mostly be empty; the paste box is the
  reliable route today.
* Homepages: BlueWave's links *two* company pages (`company/bluewave` and `company/bluewavetg`), so none
  was taken. vanguardtech.com now redirects to argylesg.com, whose page is `argyle-solutions-group`
  where the record says `argyleit` — left alone, since a page on record is never overwritten, but one
  of the two is wrong.
* **La Growth Machine:** its API has a Search Lead action and an "enriched lead" webhook, but no public
  documentation lists what a lead returns, and no LGM key is stored. Not built on guessed field names;
  one read-only call with a key settles it.

`services/linkedin.py`, `api/pasted.py`, `services/pipeline.py`, `services/evidence.py`,
`services/site_sweep.py`, `services/stages.py`, `accounts/account-detail.component.ts`. 1283 backend
tests, 284 front-end.

## 20. Enrichment never looked anyone up, and dropped the LinkedIn it was given (2026-09-13)

Asked why enrichment fills no LinkedIn links: none of the twelve Test Data contacts had an email, a
provider record or a LinkedIn URL. Three causes, the first of which explains all of it.

**Apollo was never asked.** `_verify_one` read the contact's account as
`contact.awaitable_attrs.account if hasattr(contact, "awaitable_attrs") else None`. `awaitable_attrs` only
exists on models mixing in SQLAlchemy's `AsyncAttrs`, and ours do not — so the account was None for every
real contact, the company domain was never sent, and the Apollo client, correctly refusing to match a
bare name, returned nothing without making a call. **No contact without a LinkedIn URL has ever been
looked up** — which is every contact on the list, and why no email arrived either. The account is now
loaded by `account_id` (`verification._account_of`). Confirmed without spend first (Apollo would now be
asked `Marcus Chen · bluewave.net`), then live: `providers_called: ['apollo']`.

**A LinkedIn profile Apollo returned was thrown away without an address.** Title and LinkedIn are meant to
be collected, not gated on, but were written only after the address gate — so a person Apollo recognised
with no usable email came back "not found" with the profile discarded. They are now kept whenever the
provider recognised the person.

**Nothing filled a company's LinkedIn page during enrichment.** It was set only at identity matching.
Now, for an account with none: from Apollo's organisation for a recognised contact, *only when that
organisation's domain is the account's own* (a person can be matched at a former employer or a parent);
otherwise from the company's own website.

**The website pass** (`services/site_links.py`, `verification.fill_linkedin_from_sites`) runs after the
providers for every contact in the pass still missing a link — free, one read per account: the homepage
and the usual about, team and leadership pages, robots honoured, a dead site asked once. Only an
unambiguous link is taken: a company page when the site links exactly one; a person's profile when exactly
one profile matches their name by its address (`/in/seth-penland`) or the link's own text or title —
never by the name printed near an icon, since on a team grid that is often the previous person's. Live on
BlueWave's leadership page: Seth Penland and Kevin Burke match their own profiles; Marcus Chen, not on the
site, matches nothing; the company page is not taken because the site links two. Argyle's single page
would be. The enrichment report says what was filled and from where, and the list screen's notice names
the LinkedIn links added.

*Found by running it:* the website pass first read the account the same broken way and raised
`MissingGreenlet` — which is how the enrichment defect above came to light.

`services/verification.py`, `services/site_links.py`, `services/providers.py`,
`services/enrichment_clients.py`, `api/lists.py`, `lists/list-detail.component.ts`. 1307 backend tests,
284 front-end.

## 21. Enrichment only looked up people the spreadsheet named (2026-09-13)

**Whole-list enrichment found nobody.** Seven of twelve contacts were checked and Apollo recognised none:
the names came from a CSV nobody had verified, and `people/match` can only confirm a person you already
have. Country and LinkedIn were mostly empty for the same reason — nothing but a CSV ever wrote a country.

**Now enrichment can start from the company.** Four steps on the list screen, in cost order:

1. **Check company** (`services/company_check.py`). The website is read for free: does it answer, does it
   redirect elsewhere, which LinkedIn company pages does it link. Apollo's organisation record (one credit)
   is asked only while country or LinkedIn page is missing, and kept for 90 days. What agrees is filled —
   country and state from Apollo; a LinkedIn page the site links alone, or Apollo's when it is one of
   several the site links. What disagrees is a conflict with its candidates beside it — a redirect
   (`vanguardtech.com` → `argylesg.com`), Apollo filing the company under another domain, a different
   country on record. A rep settles it on the screen; the answer is remembered on `account.company_check`.
   Apollo's facts are never used when its record is for another domain (often a parent).
2. **Find contacts (Apollo)** (`services/contact_suggestions.py`). Apollo's People API Search, **free**, one
   request per account per ICP persona — the organisation in a result has no domain, so domains cannot be
   batched. Titles with similar titles on, or the buying role's seniorities when a persona names no titles.
   Every result is read again through `personas.matches_any`, and titles that only support the role are
   dropped — similar titles returned *Chief of Staff to the CEO* for a CEO search on apollo.io, and the
   matcher agreed. At most `enrichment_config.suggestions_per_persona` (default 5, Setup) per persona per
   account. A result is matched to a contact already there by Apollo id, or first name plus the visible
   letters of the obfuscated surname (`Pe***d`); one who already has a verified address and a profile is
   `known` — nothing to buy.
3. **Accept or reject** in the *Suggested contacts* panel. Nothing is revealed without it.
4. **Reveal accepted** — `people/bulk_match` by Apollo id, ten per call, one credit per person found,
   confirmed first with the credit ceiling. Never personal emails, never phones. The contact is created or
   filled in: name, title, seniority and persona from the title, email with Apollo's own grade (`guessed`
   stays `risky`), LinkedIn profile, city, country, `apollo_person_id`. An address another contact at the
   account already holds is not moved. The account's country and page are filled only when Apollo places
   the person at the account's own domain.

**Found by running it — three corrections before it was done.**

* *Titles alone missed company heads.* A CEO title search at apexsoftware.com returned nobody; its senior
  people are an Owner and a President. When titles leave room under the cap, the persona's buying role is
  now searched by seniority too (still free).
* *…and seniority alone let in anyone senior.* That second search offered BlueWave's Chief Legal Officer as
  a CEO and its FP&A Director and VP Controller as technical buyers: the matcher reads a title naming no
  function it knows on rank alone. A result found by seniority must now name the persona's function.
* *Corporate development read as engineering.* `personas.tokens` dropped `corporate` as noise before
  collapsing phrases, leaving `development` → tech. Phrases are now read before and after noise is
  dropped, and `corporate development` is business development. This is the shared matcher, so the Buyer
  dimension reads that title correctly too.

A search also drops undecided suggestions it no longer keeps, so a tightened rule does not leave stale ones.

**Live, on the Test Data list.** Check company on BlueWave: country United States and region filled for one
credit, no conflicts (the page on record is one the site links). Find contacts over twelve accounts: 48 free
searches, four suggestions — Seth Pe\*\*\*d (Founder & CEO, BlueWave), the Owners of Apex Software and
of Argyle (vanguardtech.com), and Omnitech's National Head of Technical Support. Apollo holds people at only
four of the twelve domains (apexsoftware.com 4, bluewave.net 119, omnitechglobal.com 239, vanguardtech.com
10); the other eight have nobody, which is why the list stays mostly empty whatever enrichment does. None of
the four is a contact already on the list. Nothing was revealed: that is the rep's call.

`alembic f5a2c8e1d4b6` (`contact_suggestion`; `contact.city/country/apollo_person_id`;
`account.company_check`; `enrichment_config.suggestions_per_persona`), `services/apollo_people.py`,
`services/company_check.py`, `services/contact_suggestions.py`, `api/contact_finding.py`,
`lists/list-detail.component.ts`, `shared/account-columns.ts`, `settings/setup.component.ts`.

## 22. A worked list could never be deleted (2026-09-13)

**Deleting Test Data was refused:** *"holds accounts with 64 piece(s) of evidence. Evidence is never
deleted, so this list cannot be either."* Deleting a list deleted the accounts only it held, and deleting an
account cascades to its evidence — so any list that had been researched was permanent, and the Lists
screen could only grow.

**The decision:** a list is a workspace for organising accounts into campaigns, not what decides whether an
account's data lives. Campaigns already guard themselves — a campaign that reached La Growth Machine cannot
be deleted, and a queue that fed a campaign is locked.

**Now** (`services/anchoring.py`) an account is *anchored* while it is on at least one list or in at least
one campaign queue. Deleting a list is always allowed; each of its accounts is assessed as though the list
were gone:

* **on another list, or in a campaign queue** — untouched;
* **on nothing else, with work behind it** (evidence, signals, context, a score, a run, a company check,
  provider-found or verified contacts, decided suggestions, strategy or enrolment) — **dormant**:
  `account.dormant_at` and `dormant_reason` set, hidden, nothing deleted;
* **on nothing else, never worked on** — deleted, which is how a bad import is still undone.

The same assessment runs wherever an anchor is lost: removing accounts from a list, removing a queue member,
deleting a draft queue — those make dormant and never delete. `GET /lists/{id}/delete-preview` answers
without writing, and the delete confirmation says it: *"2 stay live through a campaign queue · 1 stay on
other lists · 8 go dormant — research and contacts kept · 1 deleted — nothing was done with them"*.

**Coming back.** An import whose domain matches a dormant account brings it back (the row says *brought back
dormant account … its research and contacts are kept*), as does **Add to list** from the new *Show dormant
accounts* panel on the Lists screen. Research then reuses what is inside the freshness window; rescoring for
the new list's ICP is free. Undecided suggestions go with a deleted list; rejected and revealed ones outlive
it (`contact_suggestion.list_id` set null), so a rejected person is not suggested again. Contacts on dormant
accounts are kept indefinitely.

**Verified addresses age.** `contact.email_verified_at` dates each verified grade (existing ones took their
row's last update). After 90 days (`verification.EMAIL_RECHECK_DAYS`) the address shows *verified ·
re-check* and enrichment offers it again, so a revived account does not carry "verified" from a check
nobody remembers. It is not blocked from sending — only flagged and re-checked.

`alembic a8c4e2f6b1d9`, `services/anchoring.py`, `api/lists.py`, `api/campaigns.py`,
`services/csv_import.py`, `services/verification.py`, `lists/lists.component.ts`,
`lists/list-detail.component.ts`, `shared/contact-columns.ts`.

## 23. Resolve identity confirmed nothing, and did not say why (2026-09-13)

**Every account on the re-imported Test Data list ended at "check this" or "not identified".** The domains
looked right on the list. Checked live, they were not: eight of twelve had **no DNS record at all**, three
were registered with nothing answering (parked), and `apexcybersecurity.com` redirected to
`apexcyber.ca` — another company's site. Apollo held none of them.

So the resolver was right not to confirm — but for the wrong reasons, and silently:

* It never looked at the website. Apollo confirms a domain from its database; the model may not confirm a
  domain it was shown (§ the echo cap). So a **real** company on a correct domain that Apollo happened not
  to hold could never be confirmed at all.
* A domain that does not exist was reported as *"no source could identify this company"*.
* The model offered **other companies' domains** — `brightbyte.software`, `hypernode.com` — at 0.95 without
  anyone checking they existed, so *"check this 0.95"* read as nearly certain.

**Now** a free `website` source (`services/site_identity.py`, `WebsiteResolver`) runs after `apollo_org`
(which still supplies industry and headcount for companies it knows) and before `llm_web`. One DNS lookup
and one homepage read, robots honoured:

* **no DNS record** → *"… does not exist — it has no DNS record"*;
* **registered but nothing answering, parked, or an error page** → said;
* **redirects to another domain** → the landing domain becomes the candidate and goes to review (the row's
  domain is never replaced);
* **answers and its homepage names the company** (`og:site_name`, `application-name`, the title before its
  separator) → **confirmed at 0.9**, with the LinkedIn page taken when the homepage links exactly one;
* **answers but names someone else** → 0.4, and the model is asked.

Names are compared by their distinctive words: legal suffixes and descriptors (*Software, Solutions, Cloud,
AI…*) are dropped, and when they were, the site may not add a distinguishing word of its own — *BrightByte*
fits *BrightByte Software*, *Apex Fitness* does not fit *Apex Cloud*. Page text is data: only names and links
are read from it.

**The model's other domains are checked the same way.** One that does not exist is dropped and said (*"the
model suggested brightbyte.software, which does not exist"*); one with no working website is capped at 0.3;
one whose homepage does not name the company at 0.6.

**Findings reach the note**, for review and for not-found alike. **Re-check identity** (a new row and bulk
action, for accounts waiting for review) runs the waterfall again with `recheck=true`, since *Resolve
identity* deliberately skips accounts already with a person.

The active enrichment configuration took a new version (6) with `website` inserted after `apollo_org` —
configuration is versioned, not edited.

**Replayed on Test Data** (free — the model's stored answers put through the new checks, nothing saved): 5
*not identified* with the reason (four *no DNS record*, one parked), 7 *check this* each saying why — e.g.
*"hypernodecloud.io does not exist — it has no DNS record; llm_web says hypernode.com"*, and Apex's
*"website says apexcyber.ca, list says apexcybersecurity.com"*.

`alembic b3d7f1a9c5e2`, `services/site_identity.py`, `services/resolution_clients.py`,
`services/resolution.py`, `api/lists.py`, `shared/account-columns.ts`, `lists/list-detail.component.ts`.

## 24. An Excel import never reached the mapping step (2026-09-14)

**Uploading a spreadsheet to a new list did nothing visible.** Three uploads answered HTTP 400: *"that .xlsx
could not be read (KeyError)"*. The file was a real `.xlsx`; the reader was wrong about where its sheet was.

**Cause.** The reader found a sheet through the workbook's relationships but treated every `Target` as
relative to `xl/`. Excel writes `worksheets/sheet1.xml`; many exporters write the absolute
`/xl/worksheets/sheet1.xml`, which became `xl/xl/worksheets/sheet1.xml` — a part that does not exist.
Reproduced on an exported workbook on this machine. Two more gaps turned up in the same pass: an `.xls`
(Excel 97–2003) was refused outright — and the file picker did not even offer one — and a workbook whose
first tab is empty read as *"appears to be empty"*.

**Fix** (`services/spreadsheet.py`):

* relationship targets resolved as the format defines them — absolute from the package root, relative from
  the declaring part's folder; the workbook found through `_rels/.rels`, shared strings through the
  workbook's relationships;
* elements matched by local name, so Strict Open XML namespaces read the same;
* the first tab **with data**, in tab order; error cells (`#N/A`) read as blank; phonetic hints left out of
  shared strings;
* `.xls` read through `xlrd` (added to `pyproject.toml`) — numbers whole where whole, dates as ISO dates;
  the upload box accepts `.xls`.

Of the 31 spreadsheets on this machine that can be opened locally, every one now reads except a SWOT report
whose content is text boxes rather than cells — correctly *"none of its 3 tabs holds data"*.

`services/spreadsheet.py`, `lists/csv-import.component.ts`, `pyproject.toml`,
`tests/test_spreadsheet_formats.py`.

## 25. Suggested contacts had none of the standard table's tools (2026-09-14)

**The suggestions were a hand-built table** above the accounts: two buttons per row, no filters, no sorting,
no selection, no column choice — with 86 suggestions across a handful of companies there was no way to
narrow to the CTOs or act on twenty at once.

**Now they are a third tab, *Suggested*, beside Accounts and Contacts**, in the same `app-data-table`: filters
on every column (Decision, Persona and Email held as pick-lists), sorting, the column picker (Location held,
Buying role, Domain, Apollo refreshed and Note off by default), row selection, and bulk or row actions —
**Accept**, **Reveal (Apollo credit)**, **Back to undecided**, **Reject** — each offered only to the rows it
applies to. Every status is loaded, so rejected and revealed people can be filtered back into view. *Reveal
all accepted* and the credit ceiling sit above the table; a reveal still asks first. Find contacts opens the
tab when it proposes anyone.

`shared/suggestion-columns.ts`, `lists/list-detail.component.ts`, `styles.css`.

## 26. "Reveal failed: HTTP 422" meant Apollo was out of credits (2026-09-14)

**Revealing 66 accepted suggestions failed with *"Apollo returned HTTP 422 for /people/bulk_match"*.** The
request was well-formed; replayed, Apollo's body said *"You have insufficient credits! Upgrade your plan…"*.
Nothing was revealed or charged, but the screen gave no way to know that.

**Now** a refusal from Apollo carries its reason: an out-of-credits answer reads *"Apollo has no credits left
on this plan, so nothing was revealed or charged. Add credits or upgrade the plan in Apollo, then reveal
again."*; any other refusal appends Apollo's own `error` text, markup stripped, trimmed, and with the key
removed should it ever be echoed. 401/403 bodies are still never read.

**And a LinkedIn column** on the Suggested tab: the profile of the contact a suggestion became — after a
reveal, or when the person was already on the list — linked; otherwise *on reveal* (Apollo's free search
returns no profile) or *none found*. Filterable.

`services/apollo_people.py`, `api/contact_finding.py`, `shared/suggestion-columns.ts`,
`lists/list-detail.component.ts`.

## 27. "Email held" read as enriched, and a revealed person could be paid for twice (2026-09-14)

**Rejected suggestions showed an *email* badge**, which read as though they had been enriched. It is Apollo's
free-search flag — Apollo holds an address — and nothing had been revealed: on the `test` list 0 suggestions
had ever been revealed, and Apollo's own usage counter showed today's 8 `people/bulk_match` calls, every one
refused for insufficient credits, so none charged. The column is now *Apollo has email* (*has email* / *no
email*), and the tab says the address arrives on reveal.

**A person already revealed is never sent to Apollo again.** Before a reveal, any accepted suggestion whose
Apollo person id is already on a contact holding an email or LinkedIn profile is settled from that contact —
status *revealed*, note *already revealed — stored details used, no credit spent* — and only the rest are
bought. The reveal notice counts them. (A verified address is still re-checked after 90 days, §22, which
does call Apollo.)

`services/contact_suggestions.py`, `api/contact_finding.py`, `shared/suggestion-columns.ts`,
`lists/list-detail.component.ts`.

## 28. People paid for were never saved in Apollo, so Apollo could charge for them again (2026-09-14)

**Apollo's rule**, from its documentation: a person enriched through the API and never saved as a contact
is a new request next time; *"A contact is a person saved to Apollo, which means their data becomes
permanently accessible to your organization."* Nothing here saved anyone, so every repeat lookup — a
second reveal, the 90-day re-check — could be charged again.

**Now** (`services/apollo_contacts.py`, agreed before building: write to the Apollo account, label *Gen360*,
re-check from saved contacts first):

* **Saved after paying.** Everyone revealed, and every contact Apollo enriched on an enrichment pass, is
  saved with `contacts/bulk_create` — free, `run_dedupe` so an existing contact is returned rather than
  duplicated, labelled `Gen360`. The Apollo contact id and time are kept on the contact
  (`apollo_contact_id`, `apollo_saved_at`). A refusal to save is reported and never undoes a paid reveal.
* **Looked up before paying.** A reveal first settles anyone this installation already revealed (§27), then
  anyone saved in the Apollo account — one free `contacts/search` per company, matched on Apollo's person
  id — and buys only the rest. Those are marked *saved in the Apollo account — no credit spent*.
* **The 90-day re-check reads the saved contact first.** An aged verified address whose saved Apollo contact
  Apollo still grades `verified` is re-stamped for free (*re-confirmed from the saved Apollo contact*);
  only the rest go through the paid waterfall.

`contacts/search` has no person-id or exact-email filter, so matching is done on the results: person id for a
reveal, exact email for a re-check. Mobile numbers (8 credits) are never requested.

`alembic c9e4a2d7f1b3`, `services/apollo_contacts.py`, `services/apollo_people.py`,
`services/contact_suggestions.py`, `services/verification.py`, `api/contact_finding.py`, `api/lists.py`,
`lists/list-detail.component.ts`.

## 29. Revealing 2 people with 7 credits left failed, and "Reveal all" read like the selection (2026-09-14)

**Reported:** three suggestions selected, Reveal clicked, Apollo said it was out of credits while the account
showed 7 left — as though all 66 accepted were being revealed.

**Checked without spending anything** (the request blocked in the browser before it left the page): the
bulk bar's *Reveal (Apollo credit)* on that selection asks *"Reveal 2 accepted contacts?"* and sends exactly
those two ids, once. But Apollo's counters showed 24 saved-contact searches — one per company for all 12
companies, twice — so two earlier requests, sent at the same moment, came from **Reveal all accepted**,
which sits beside the bulk bar and did not say how many it meant.

**And a batch was all-or-nothing.** Reveals go ten at a time; Apollo refuses a whole batch when the account
holds fewer credits than it asks for, so seven credits against a batch of ten revealed nobody.

**Fixes:**

* A batch refused for credits is retried **one person at a time**, so the credits that are left are spent;
  the first single refusal stops it (`OutOfCredits`, carrying what was revealed). Those revealed are kept and
  saved to Apollo; everyone not reached **stays accepted** — not *not found* — and the notice says how many.
  With nothing revealed at all it still fails and changes nothing.
* The button reads **Reveal all 66 accepted**, and the confirmation says *selected* or *all*.
* A second reveal cannot start while one is running.

`services/apollo_people.py`, `services/contact_suggestions.py`, `api/contact_finding.py`,
`lists/list-detail.component.ts`.

## 30. Run messages and errors disappeared and could not be traced (2026-09-14)

**Reported:** *"the run message/error go away and not able to trace."* Every outcome went through
`NotifyService`: at most four notices in the corner, successes cleared after five seconds, a fifth pushed the
oldest out — and nothing was kept anywhere.

**Now an Activity accordion sits at the top of every page** (`shared/activity-bar.component.ts`,
`shared/activity.service.ts`). Collapsed it shows unseen errors, how many things happened today and the
latest message; open, every outcome newest first in its own scrolling box, filterable to *errors and
warnings*, with Clear.

* **Everything is recorded** — `NotifyService` writes each notice to the log, so all existing call sites are
  covered without changing them. Each entry keeps the time, kind, message, the server's reason, and where it
  happened (*List · test*, or the section of the app).
* **Runs keep each account's result.** `SequentialRun` notes every item — the list screen describes resolve,
  check company, find contacts, enrich, research and re-read results in a line (*"Figma — Apollo rate limit
  reached"*); a failed request records the server's message — and the run's items attach to the summary
  message that follows, as a fold-out under it with *completed of total* and elapsed time.
* **Notices stay, and link to it:** *View in activity* opens the panel on that entry.
* **Kept in this browser** (`localStorage`, last 200), so it survives reloads and navigation. It is a trace of
  what this person ran, not a shared record.

`shared/activity.service.ts`, `shared/activity-bar.component.ts`, `shared/notify.service.ts`,
`shared/sequential-run.ts`, `shared/toast-host.component.ts`, `app.component.html`,
`lists/list-detail.component.ts`.

## 31. A contact could not be put in a campaign queue — only companies could (2026-09-14)

**Reported:** the one enriched contact on the list could not be promoted; only companies could be queued.
Queues held accounts, and promotion turned each account's pursued *strategy threads* into sequences — so
there was no way to choose who a campaign reaches, and nobody could be promoted until a strategy existed.

**Decided:** enrichment stays company-wide; **campaigns are built from the people selected**. A person is
queueable with a **verified email or a LinkedIn profile**; whole companies can still be queued alongside;
**a strategy is needed only before executing outreach**.

**Now:**

* `campaign_queue_contact` holds the people chosen for a queue (their company and source list with them).
  `promotion.add_contact` applies the company's queue rule and the reachability rule, naming the person in
  any refusal; `POST /queues/{id}/contacts/bulk`, `GET /queues/{id}/contacts`, `DELETE …/contacts/{id}`.
* **Promotion** gives each chosen person a sequence — LGM lead resolved, cadence selected, the enrolment
  lock intact — with no strategy required. A person also covered by a queued company gets one sequence.
  Clones carry the people.
* **`outreach_sequence.contact_id`** records the person (backfilled from threads); `thread_id` is optional
  and linked when a strategy is pursued for them (`promotion.person_of`, used by approval, arc, pre-flight
  and execution).
* **Pre-flight** has a new blocking check, *Every person has a strategy* — *"no strategy yet for Enrico
  Bergamo — build it before executing"*.
* A queued person keeps their company live (`anchoring`).
* **Screens:** the Contacts tab selects people and *Add to queue* (refused without a verified email or
  LinkedIn); the queue page lists **People** (removable while a draft) above Accounts, counts both, and its
  *Add* panel picks **People or Accounts** from a list.

`alembic e7a1c5d3b9f2`, `services/promotion.py`, `services/preflight.py`, `services/execution.py`,
`services/anchoring.py`, `api/campaigns.py`, `api/intelligence.py`, `lists/list-detail.component.ts`,
`queues/queue-detail.component.ts`, `docs/03-data-model.md`.

## 32. No strategy could be built — and it belonged to the company, not the campaign (2026-09-14)

**Reported:** Datadog showed no strategy for Enrico Bergamo after research, reveal and promotion. Could a
strategy be forced for a contact whatever the qualification — and shouldn't qualification and strategy
belong to the campaign, since they depend on its ICP and service?

**Cause:** the strategy stage was never wired. `strategy.build_matrix`, `select_threads` and
`stages.synthesise_strategy` existed and were tested, but nothing called them — so no strategy was ever
written, and every person promoted by name sat at *strategy needed*. Both qualification and strategy were
also keyed to the company alone: one score whichever ICP a campaign targeted, one argument per person
whatever they were being sold.

**Decided:** the **service and ICP are chosen when the campaign queue is created**, and apply to everyone in
the campaign. **Qualification is scored separately per campaign** (ICPs differ). **Defaults follow the sales
rules**, with a per-person override: *pursue anyway* for someone below the persona threshold or over the
thread cap, and *allow without a live signal* where nothing live is known. Qualification is not required to
build a strategy. Old strategies are not migrated.

**Now:**

* `campaign_queue` and `outreach_campaign` carry `service_id`, `icp_profile_id` and `icp_version`; the
  queue form requires both (only ICPs linked to the service are offered). Promotion copies them and refuses
  queues built for different ones; clones keep them. A campaign promoted before this can have them chosen
  on its *Qualify & strategy* tab while it is a draft.
* `qualification.campaign_id` (+ ICP): **Score for this campaign** runs the six-dimension qualification
  against the campaign's ICP only. Company-wide reads (lists, account page, queue rule) ignore campaign
  scores.
* `services/campaign_strategy.py` — the rules' default per person (weight vs `persona_weight_threshold`,
  `max_concurrent_threads`, reachability, live signals), then **Build strategy** — one model call per
  company for the people chosen, triggers checked against the live set, hypotheses checked for
  differentiation. The strategy is stored against the campaign, the sequences are linked, and a rebuild
  supersedes the previous version and unlinks anyone it leaves out.
* `strategy_thread.chosen_by_rep` and `without_live_trigger` record the overrides; the database still
  requires a cited trigger unless a thread is marked as built without one. **Approval flags both**, so
  those sequences are read, never sampled.
* `pursued_thread_for` prefers the campaign's strategy, falling back to a company-wide one from before.
* **Screen:** the campaign page opens on **Qualify & strategy** — each person's score for this campaign,
  the default with its reason, the override checkboxes and the strategy built. Signals past their shelf
  life are counted — *none live (4 expired)* — so a researched company with only old news says why it
  has nothing to cite, and the bulk bar's counts follow a ticked override.

`alembic a4d9e2b7c1f6`, `services/campaign_strategy.py`, `api/campaign_strategy.py`,
`services/promotion.py`, `services/approval.py`, `api/campaigns.py`, `api/intelligence.py`, `api/lists.py`,
`schemas/strategy.py`, `services/instructions.py`, `campaigns/campaign-strategy.component.ts`,
`queues/queues.component.ts`, `docs/03-data-model.md`.

## 33. Strategy and cadence drafts live in Outreach; qualification stays with the company (2026-09-15)

**Asked:** show strategy and cadence drafts under Outreach, against each contact, and take them out of
the company and contact pages — a person can be argued for differently per service and ICP. Keep
qualification on the company. Once each contact's cadence is edited and saved, the campaign is approved
and executed.

**Found on the way:** drafting was never wired (as strategy had not been) — no route called
`stages.draft_arc` — and approval accepted a sequence with no touches, which is how *test campaign* read
"1 approved" with nothing written.

**Now:**

* **Qualification stays with the company, read per ICP** (`services/icp_scores.py`). The model judges
  opportunity, commercial and intent once; fit and buyer are recomputed in Python for each ICP and the
  roll-up re-run — no model call. The account page's Qualification tab shows a score per ICP; the queue
  rule reads the band for the queue's ICP; Outreach shows the score for the campaign's ICP, read-only.
  The per-campaign scoring from §32 is removed and its columns dropped.
* **Outreach tabs:** Strategy → **Cadence drafts** → Approval → Threads → Execute. Clicking a person on
  either of the first two opens a side panel with their **Qualification**, **Strategy** (default decision,
  overrides, trigger signals, versions) and **Cadence drafts**.
* **Cadence drafts** (`services/campaign_drafts.py`, `api/campaign_drafts.py`): *Write drafts* fills the
  person's cadence in one model call from their strategy (a rewrite adds a version to every touch);
  *Edit* saves the rep's words as a new `rep_edit` version, checked against the cadence, the attribute
  budget and approved proof points; *Save for approval* moves the sequence to `pending_approval`. Any change
  after saving returns it to `draft`.
* **Approval** lists only saved people (the rest are named as waiting); approving needs saved drafts; a
  rejection sends the person back to drafting; edited cadences are flagged *"drafts edited by you —
  approve them as read"*, never sampled. An approval counts only while the sequence is approved and has
  content (`campaign_drafts.approved_ids`, used by approval, the arc and pre-flight). Sequences approved
  with no touches were returned to `draft`.
* The account page's Strategy tab is now **Outreach**: each campaign the company's people are in, with
  the ICP score and each person's strategy and draft state, linking to the campaign.

`alembic b8e3f1c6d2a4`, `services/icp_scores.py`, `services/campaign_drafts.py`, `api/campaign_drafts.py`,
`api/campaign_strategy.py`, `api/campaigns.py`, `api/intelligence.py`, `services/preflight.py`,
`services/execution.py`, `campaigns/campaign-person.component.ts`, `campaigns/campaign-drafts.component.ts`,
`accounts/account-detail.component.ts`.

## 34. A contact row could be queued and nothing else (2026-09-15)

**Problem.** The Contacts tab had one action, *Add to queue*. Everything a rep noticed while
reading a person — this address is stale, this company needs research, there must be more people
here, this person asked us to stop — meant leaving the tab, finding their company on the Accounts
tab, and acting there. Deleting a bad contact had no answer at all.

**Cause.** Contact-level work had no server side: enrichment took a list and optionally accounts,
research took accounts, and there was no way to say "these people".

**Fix.** The Contacts tab now carries the actions the rows imply.

* **Enrich / re-check** takes `contact_ids`, so picking three people at a company with twenty
  contacts does not pay for the other seventeen. Still one provider call per company.
* **Research this person** narrows `run-research` to named people: their company families are not
  planned at all, and their reuse window is ignored — picking somebody by name is an explicit ask.
  *Research their company* and *Find more people there* act on the companies behind the selection,
  deduplicated.
* **Copy email address** puts the addresses on the clipboard; a rep's own mail client is outside
  the sending path.
* **Mark do not contact**, with a required reason, and **Allow contact again**. It is not a delete:
  the person's signals, evidence and history stay, and `verification`, `research`,
  `promotion.contact_ineligibility` and a new pre-flight check (`do_not_contact`, the ninth) each
  refuse them. Pre-flight matters most — somebody is usually marked *because* of a campaign that
  already holds them.

`alembic c4f8b2e6a1d7`, `api/lists.py`, `services/verification.py`, `services/research.py`,
`services/promotion.py`, `services/preflight.py`, `shared/contact-columns.ts`,
`lists/list-detail.component.ts`, `core/lists.service.ts`, `tests/test_contact_suppression.py`.

## 35. The rating appeared on companies and nowhere else (2026-09-16)

**Problem.** A score showed on the list's Accounts tab (as *Priority*), on a queue's accounts, and
on the campaign's own tabs. Every table whose rows are **people** showed nothing: the list's
Contacts tab, Suggested, and a queue's People. So "is this person worth a credit, a draft, a
queue?" could not be answered where the decision is made.

**Cause.** Those tables predate per-ICP scoring, and a person-level rating needs a service and an
ICP to mean anything. Inside a campaign both are fixed; on a list they come from *Worked for*, and
nothing read them.

**Fix.** One definition, shared.

* `icp_scores.as_rating` / `best_rating` — the company's rating read for the ICPs a screen works
  for, best across them as fit already is, with the ICP named in the hover text. Arithmetic over
  one stored qualification: no model call, whatever the table's length, and computed once per
  account rather than once per row.
* `shared/rating-columns.ts` — **Company rating**, **Band** and **Qualify gate** as one column set,
  used by the list's Contacts and Suggested tabs, a queue's People, and the campaign's Strategy and
  Cadence drafts tabs. The two narrow columns start hidden.
* *Priority* on the Accounts tab is renamed **Company rating**: it is the same number, and two
  names for it was the reason it read as two different things.

`services/icp_scores.py`, `api/lists.py`, `api/campaigns.py`, `api/contact_finding.py`,
`shared/rating-columns.ts`, `shared/account-columns.ts`, `shared/contact-columns.ts`,
`shared/suggestion-columns.ts`, `queues/queue-detail.component.ts`.

## 36. La Growth Machine: a real client, and what its API actually does (2026-09-19)

**Problem.** The send path was a stub. `docs/07` Q3 — LGM's auth scheme — was the reason, and the
provider was marked unverifiable, so the outreach slot could never be satisfied.

**What the published API says**, and what it cost us to assume otherwise:

* Base `https://apiv2.lagrowthmachine.com/flow`, key as `Authorization: Bearer`, **50 calls per 10
  seconds**. `/members` authenticates, reads nothing, changes nothing — so `lgm` now has a probe and
  is `runnable`.
* **There is no enrol call.** A campaign runs over an *audience*; writing a lead into that audience
  is the enrolment. Our adapter assumed `enrol(lead, campaign)` — it now confirms the campaign is in
  a state that sends and returns a reference, and `upsert_lead` carries the audience name. A shape
  therefore registers two things: the campaign whose steps it describes (`lgm_campaign_id`) and the
  audience that campaign reads (`lgm_audience_name`), and pre-flight blocks a shape missing the
  second one.
* **The first launch has to happen in the LGM app.** The API pauses and resumes; it cannot start a
  campaign that has never run. A `READY` campaign is now a named block, not a silent no-send.
* **1000 characters per custom attribute**, truncated silently. `validate_arc` refuses a longer
  touch: a truncated message still sends, mid-sentence.
* `crm_id` is written with our contact id, so replies and conversations come back joinable without
  matching on an address that may have changed.

**Also.** `GET /campaigns/:id/messages` returns each step's template, so *Check against LGM* now
reads what each step actually sends and reports a map pointing our copy at an attribute nothing
reads — `verified_by` used to mean only that somebody had looked.

`alembic d5c1a8f3e7b2`, `services/lgm_client.py`, `services/lgm.py`, `services/cadence.py`,
`services/drafting.py`, `services/execution.py`, `services/provider_catalogue.py`,
`api/campaigns.py`, `api/intelligence.py`, `campaigns/campaigns.component.ts`,
`tests/test_lgm_client.py`.

## 37. A campaign could not be made smaller, and could not be read at all (2026-09-19)

Four faults, one screen, all found by a rep trying to execute a campaign of four people.

**Mixed cadences.** The rules pick a shape per person; execution enrols everyone into the
*campaign's* LGM campaign. Three people drafted for `nurture_4_21` were about to be enrolled into a
six-step sequence, leaving steps 5 and 6 sending whatever the lead already held. An LGM campaign is
one sequence, so **the campaign's cadence now wins**: promotion stamps it, drafting follows it, and
a new pre-flight check (`one_cadence`, the tenth) blocks anyone on another cadence or with a touch
count that does not match. `save` refuses a mismatched arc, and `write` replaces an arc whose
cadence changed rather than versioning copy onto steps that no longer exist.

**Pre-flight named counts, not people.** "2 of 4 thread(s) not approved" without saying *which two*
is a hunt. Each check now carries its people, shown as chips that open exactly the screen that can
clear it — the arc for approval, cadence drafts for content, strategy for a missing one. Six names,
then a link to the filtered list, because a hundred chips is not a list.

**The threads list could not show the people blocking it.** It was built from the approval payload,
which holds only what is saved — so filtering to "awaiting" returned nothing precisely when it
mattered. It now lists everyone, with the state that says what each is waiting on.

**No way out.** A promoted queue is locked forever, so a person could not be dropped. `withdraw`
sets the sequence `cancelled` with a required reason: drafts stay attached, the strategy stays, the
row stays visible and greyed, and nothing counts them. `cancelled` is outside the enrolment lock, so
they can be queued elsewhere at once. Reinstating returns them to `draft` — their approval is not
inherited.

`alembic e2b7d4a9c3f1`, `services/promotion.py`, `services/campaign_drafts.py`,
`services/preflight.py`, `services/execution.py`, `api/campaign_drafts.py`, `api/campaigns.py`,
`campaigns/campaign-detail.component.ts`, `campaigns/campaigns.component.ts`.

## 38. A dated claim was judged by its step number, not by its expiry date (2026-09-20)

**Problem.** Drafting refused step 5 of 6 for being `implied` in the last third of the arc, and the
same arc asked for 11 custom attributes against LGM's limit of 10. Both refusals were sound rules
applied where they did not fit.

**Cause.** `signal_dependence` was banded by position: `dated` early, `implied` in the middle,
`durable` late. That is a proxy for the real question, and a poor one. Copy is frozen at enrolment,
so the day a touch sends is known exactly, and every signal carries `expires_at` — the question is
answerable rather than guessable. Separately, the prompt said "subjects default to LGM-native"
without saying that a subject costs an attribute, or how many were left.

**Fix.**

* **`dated` is allowed anywhere, and checked against the send date**: each cited signal must still
  be live on `today + day_offset`, or the touch is refused naming both dates. A signal that never
  expires dates any touch; a superseded one dates none, whatever its expiry says, because it is no
  longer the current reading of that fact.
* **A cited signal nobody has is refused** (`unknown_signal`) — a dated claim has to be
  re-checkable before it sends, and pre-send revalidation has nothing to check without it.
* **`implied` and `durable` are unconstrained.** An implication does not announce news, so it does
  not go stale the way an announcement does. The thirds remain only as the fallback shape.
* **The subject budget is stated in numbers**: the cadence payload carries `attribute_budget` and
  `custom_subjects_allowed` (`10 − touch_count`), and the refusal says how many of the touches may
  carry their own subject.

`services/drafting.py`, `services/instructions.py`, `services/campaign_drafts.py`,
`tests/test_drafting.py`.

## 39. Outreach was write-only (2026-09-20)

**Problem.** We enrolled a lead and never heard anything again. No sends, no replies, nothing a
dashboard could show and nothing a later campaign could learn from — the one thing outbound exists
to produce was invisible.

**Fix.** `outreach_event`: one row per thing LGM reports, from either of the two routes it offers,
stored identically by both.

* **The inbox webhook.** `POST /lgm/inbox/{token}` receives LinkedIn and email events as they
  happen. LGM signs nothing, so the token *is* the credential: minted server-side when the webhook
  is registered, stored encrypted, compared in constant time, and a wrong one gets a bare 404 that
  tells a prober nothing. Registration refuses a non-https URL.
* **Polling.** `POST /campaigns/{id}/sync` reads `/conversations/search` from the newest event held
  and walks each conversation's messages. It needs no public URL — which is what makes it the
  honest default for a laptop install — and it is the reconciler after a webhook outage.
* **One row either way.** `external_id` is unique per source, so the same message pushed and then
  polled is stored once. Proven in tests from both directions.

**Matching is by our own id first.** `crm_id` carries the contact id onto the lead at enrolment, so
a reply joins exactly and survives an address changing; then the lead id, then an address — and an
address matching two people is not a match. How it was matched is recorded on the row, and an event
matching nobody is **still stored** and counted: a gap a rep can see beats a reply that vanished.

`first_reply_at` and `last_event_at` sit on the sequence so a list does not aggregate every event to
say "replied". The Replies tab shows the feed with sent/received/replied counts and a **Sync now**
button. Message text is a prospect's words: quoted, never followed (invariant 10).

`alembic f3a6c9e2b1d8`, `services/lgm_events.py`, `services/lgm_client.py`,
`api/outreach_events.py`, `models/execution.py`, `campaigns/campaign-detail.component.ts`,
`tests/test_outreach_events.py`.

## 40. A schedule nobody here owns was being invented twice (2026-09-20)

Registering a cadence asked a rep for `span_days`, and the drafting schema asked the model for a
`day_offset` per touch. Validation then measured the second against the first and reported
agreement. Neither number came from anywhere: **La Growth Machine schedules its own steps and
publishes the schedule nowhere.** Checked against the live account rather than assumed —
`/campaigns/:id` carries no delay, `/campaigns/:id/settings` answers **404**, and
`/campaigns/:id/messages` gives each step's order, channel and template and nothing about time.

It surfaced from the rep's side, not ours: *"if api doesnot expose step timing. Should DemandGen360
bother? the control is with LGM ... If we try to configure here that will lead to confusion."* That
is invariant 6 — Gen360 never authors a cadence — and a schedule is part of one. Two guesses
checking each other had been passing for a control.

* `cadence_shape.span_days` and `touch.day_offset` are **nullable**, not dropped: rows written
  before this hold real history, and a touch that already sent on day 3 sent on day 3 (invariant 2).
  New rows leave them NULL, which reads as "LGM decides", and the screens say so.
* Registration takes a campaign and a name. Steps, the attribute each one reads, channels, audience
  and status are read from LGM's templates.
* `cadence.durable_from_step` is **gone**. It derived a drafting rule from the typed span, which
  made policy look like a derivation.
* The expiry check splits in two. `signal_expired` — already untrue on the day of writing, and the
  copy has to change. `signal_expires_before_it_sends` — only decidable where a day was
  volunteered, so nothing new can raise it. What stops a stale claim leaving is the pre-send
  freshness check, which runs against the real calendar.
* Promotion re-ordered. A list now becomes a **queue** and stops there; the LGM campaign is chosen
  when the queue is promoted to outreach, and it carries the cadence and the schedule with it.
  Before, a list became a campaign in one step and asked for a cadence before anyone had looked at
  who was in it.

Timing is still *observable* after the fact — `/statsleads` and our own `outreach_event` rows carry
real send times once a campaign runs. Reading it back as evidence is worth doing; it is not the
same thing as configuring it, and nothing depends on it.

`alembic a7e4d2c9b5f3`, `models/campaign.py`, `models/content.py`, `schemas/draft.py`,
`services/drafting.py`, `services/cadence.py`, `services/campaign_drafts.py`,
`api/intelligence.py`, `lists/list-detail.component.ts`, `campaigns/campaigns.component.ts`,
`tests/test_drafting.py`, `tests/test_promotion_lock.py`.

## 41. The first launch was a deadlock (2026-09-20)

A campaign registered from LGM but never launched there was refused everywhere. `check_enrolment`
blocked on `never_launched`, so pre-flight failed, so `execute()` never ran — and `enrol()` raised
the same refusal a second time, telling the rep to go and launch the campaign in La Growth Machine.

**They could not.** LGM will not launch a campaign whose audience is empty, and a campaign there
runs over an audience: writing a lead into that audience *is* enrolling them. So the write Gen360
was refusing is precisely what makes the launch possible. Both ends waited for the other, and the
error message named the way out as the thing it was preventing.

It surfaced from the rep's side, against a live account and a real campaign: *"with passing the list
as audience i cannot launch campign in lgm."*

* `EnrolmentBlock` gains a `severity`. `never_launched` becomes a **warning**: it does not stop the
  write, and it states what is true — the copy is in the audience and nothing sends until a person
  launches it in LGM.
* `enrol()` returns `…:awaiting_launch` for a `READY` campaign rather than raising. Archived and
  deleted still refuse: nothing makes those send, so the write would be pointless. Paused still
  refuses — it has been launched, and a pause is somebody's decision.
* Pre-flight passes on warnings and still prints them, because silence there reads as "sending has
  started".
* Execute answers `awaiting_launch` and the audience name, and the screen says so rather than
  reporting "enrolled": a rep who believes sending has begun waits for replies that cannot come.
* Every screen that judged a shape by `blocks.length` now asks `blockersOf()`.

The order that works: register the shape → point the LGM campaign at a **dedicated** audience →
Execute, which writes the people and their copy into it → launch once in LGM → replies come back
through the webhook.

`services/cadence.py`, `services/lgm_client.py`, `services/preflight.py`, `services/execution.py`,
`api/campaigns.py`, `api/intelligence.py`, `core/pipeline.service.ts`,
`campaigns/campaign-detail.component.ts`, `tests/test_lgm_client.py`, `tests/test_promotion_lock.py`.

## 42. What a live audience taught us in four calls (2026-09-20)

One throwaway lead, written into a purpose-made audience on the live account, settled four things
the documentation had wrong or silent. The whole sequence — create the audience, write the lead,
read it back — is the enrolment path, so this was the integration test as much as an experiment.

* **The audience is named, not identified.** `POST /leads` with `audience: "Gen360 · BertieTest"`
  put the lead exactly there, and the 329-lead audience two campaigns share was untouched. Writing
  a lead into an audience *is* the enrolment; there is no other call.
* **`GET /audiences/:id/leads` exists**, and it is the only way to see what LGM actually holds for
  a person — `GET /leads/:id` is a 404. It is now `audience_leads()`, and it is how "did our copy
  arrive" gets answered *before* a launch rather than after someone receives the wrong thing.
* **The attribute cap is 20, not 10, and overflow is refused rather than dropped.** Attributes 11,
  15 and 20 all store and read back; a 21st is refused. Both halves of the documented behaviour
  were wrong, and the wrong half that mattered was "dropped silently" — the stub imitated it, so
  tests taught a failure mode LGM does not have. At ten, a six-step cadence could not give every
  step its own subject line. At twenty it is no longer the binding constraint.
* **`crm_id` cannot be read back on this account.** A lead written with one reads it back empty on
  `GET /audiences/:id/leads`, while an unrecognised spelling (`crmId`, `externalId`) is refused
  outright — so the field is real and accepted. Whether it is *stored* is still unknown: the
  documented way to check, `GET /leads/search?crmId=`, answers 404 here for every parameter, so the
  route is not available to this account. ("Accepted and discarded" was the first conclusion and
  went further than the evidence.) Either way our reply matching cannot rely on it, and what
  actually matches a reply is the lead id recorded at execution.

One more, found while tidying up: **an empty string does not clear an attribute.** LGM reads `""`
as "leave it alone", so copy from an earlier enrolment stays on a lead until something overwrites
it. Harmless as things stand — every enrolment writes one attribute per step of its own shape —
but it is a trap for anything that ever writes a shorter arc over a longer one.

`alembic b1c7f4a9d6e2`, `services/lgm.py`, `services/lgm_client.py`, `services/lgm_events.py`,
`services/cadence.py`, `services/drafting.py`, `services/preflight.py`, `models/campaign.py`,
`tests/test_drafting.py`, `tests/test_execution.py`.

## 43. The write succeeded and the reply failed (2026-09-20)

"Could not draft Enrico Bergamo's cadence. Internal Server Error" — about an arc that was already
in the database, complete and correct.

`touch.day_offset` became nullable when timing went back to LGM (§40). The route's `TouchOut` still
declared it `int`. So `POST /sequences/{id}/drafts/write` did the work, committed it, and then blew
up serialising the response it returns by re-reading the arc. The rep saw a failure, believed the
copy was lost, and would have paid for a second model call to produce what was already there.

Two things made it invisible. Every drafting test calls the service directly, so nothing exercised
the route; and the failure was in the response, after the commit, which is the one place a "did it
work" check does not look.

Fixed by typing the field honestly, and by a route-level test that drafts an arc with no days and
reads it back through the API. The test was checked against the old type first: it fails there, so
it is testing the thing it claims to.

`api/campaigns.py`, `core/pipeline.service.ts`, `campaigns/campaign-detail.component.ts`,
`campaigns/campaign-person.component.ts`, `tests/test_campaign_drafts.py`.

## 44. A registration outlived the campaign it registered (2026-09-20)

`BertieTest` was registered from LGM, then deleted there. Gen360 went on offering it: the cadence
picker listed it, a campaign was promoted onto it, drafts were written and approved against it, and
**pre-flight reported the whole campaign ready to execute.** Ten checks passed. Executing would have
written real people and their approved copy into the audience of a campaign that does not exist.

Nothing stored could have caught it. The row said verified, two steps, an audience named — every
one of those facts true when written, and a deletion leaves no trace in any of them. The rep saw it
before the checklist did: *"bertie test was from previous api exchange. then bertie test was deleted
in lgm, then in gen360 it shouldnot show."*

The rule this breaks is one the codebase already states — a `cadence_shape` is a **mirror of LGM,
not a source of truth** — and mirrors have to be looked at.

* `lgm_status = "missing"`, ours rather than LGM's, and a **blocker**: a warning would let approved
  copy go nowhere.
* `check_shape` returns that verdict instead of letting the 404 escape, because the caller learning
  of it is no use if the stored row still says "verified". The verdict clears the verification.
* `GET /cadence-shapes?live=true` reconciles every registration against one listing of the account.
  The three screens that *choose* a cadence pass it.
* Pre-flight asks before it judges, defaulting to on. It is the gate immediately before people are
  written to a provider, and it was the one reporting ready.

Failure to reach LGM changes nothing in either path — no key, no answer, or an empty account leaves
the stored status alone. A network problem is not evidence that somebody deleted a campaign.

`services/lgm_client.py`, `services/cadence.py`, `services/preflight.py`, `api/intelligence.py`,
`core/pipeline.service.ts`, `tests/test_lgm_client.py`, `tests/test_promotion_lock.py`.

## 45. Two routes we had ruled out, and one we never looked for (2026-09-20)

Asked whether Gen360 could set the audience itself, the honest answer was "LGM publishes no route
for it" — inferred from a `GET /campaigns/:id/settings` answering 404. That inference was wrong.
The route exists; it only accepts **POST**. Reading the published Postman collection as data rather
than probing endpoint by endpoint turned up 39 documented endpoints, several of which change what
Gen360 can do:

* **`POST /campaigns/:id/settings`** takes `audienceId`, "only while the campaign has not been
  started yet (status READY)". So the audience *can* be set from here, and the moment a shape is
  registered is exactly the window in which LGM allows it. Registration now creates and attaches
  one; there is a row action for shapes that already exist.
* **`POST /campaigns/:id/status`** pauses and resumes — and their own documentation confirms the
  thing that had been inferred: *"This endpoint does not launch a campaign for the first time: a
  READY campaign must be launched from the LGM app."* Inferred correctly, now documented.
* **`POST /leads/removefromaudience`** is the un-enrolment that was thought not to exist. Absence
  from the audience un-enrols exactly as presence enrolled; the lead and its history stay.
* **`GET /leads/:leadId/logs`** returns per-step `campaignId`, `stepId`, `channel`, `status` and
  `createdAt` — the observed schedule §40 said could only be recovered after the fact. It is the
  place to read it.
* `GET /audiences/:id/leads` pages with `skip`/`limit`, which our reader ignores.

The lesson is narrow and worth keeping: **a 404 from one verb is not evidence about a route.** LGM
answers 404 for validation errors, for wrong methods, and for endpoints a plan does not include —
three different facts wearing one status code. Twice now that has been read as "no such thing".

`services/lgm_client.py`, `api/intelligence.py`, `core/pipeline.service.ts`,
`campaigns/campaigns.component.ts`, `tests/test_lgm_client.py`.

## 46. Every enrolment had always failed, and every test passed (2026-09-21)

The first real execution against a live LGM campaign enrolled nobody. `POST /leads` answered 404 —
LGM's validation error — for every lead. Two faults, both at the same boundary.

**The attribute names were never translated.** Everything inside Gen360 says
`custom_attribute_1`; LGM's lead payload only knows `customAttribute1`. One unknown field makes it
reject the entire lead, so body, subject and person were all lost together. The write path had
never once succeeded against the real API.

**The subject had nowhere to go.** A custom subject was written to `<body attribute>_subject` —
`custom_attribute_1_subject` — a field that does not exist. A subject is a separate template in
LGM and can only carry our words if *its own* template names an attribute. Nothing recorded which
one, so `subject_attribute_map` now does, read from `subjectHtml` at registration, and pre-flight
refuses a campaign whose written subject has no slot rather than dropping the line in silence.

**Why no test caught it.** `StubLgmAdapter` accepted any key it was handed, so
`assert sent["custom_attribute_1"] == "Hello"` passed for months while asserting the wrong wire
format. A fake that accepts more than the real thing proves nothing. The translation now lives in
`lgm.py` beside the protocol, and **the stub validates through it** — the same names are refused in
tests as in production.

A third thing surfaced while fixing it: `check_shape` treated `ready` as a finding, which made the
check unsound, which withheld `verified_at`, which blocked enrolment for never having been
verified — so a campaign awaiting its first launch could never be filled, and therefore never
launched. §41's deadlock wearing a different hat, one layer up. `ready` is reported and is not a
finding; enrolment already says plainly that nothing sends until somebody launches it.

Verified live, end to end: Enrico Bergamo written into `Gen360 · BertieTest9-20` with
`customAttribute1` and `customAttribute2` carrying his approved copy, read back from
`GET /audiences/:id/leads`.

`alembic c9e3b7d1a482`, `services/lgm.py`, `services/lgm_client.py`, `services/execution.py`,
`services/preflight.py`, `api/intelligence.py`, `models/campaign.py`, `tests/test_lgm_client.py`,
`tests/test_execution.py`.

## 47. The error named its own fix, and nobody could see it (2026-09-21)

"can u check why it is not building strategy". The button did nothing visible; the API answered
**500 Internal Server Error**. The exception behind it said:

> Gemini hit maxOutputTokens before finishing — raise max_tokens for this stage

`strategy_synthesis` runs at `effort=xhigh` with `thinking_mode=adaptive`, capped at 16000 output
tokens. On Gemini **thinking counts against that budget**, so a company with five live signals and
a full context thought its way out of room before emitting the JSON. Raised to 48000 (v4, through
the versioned config route, not by hand); the same build then succeeded first try.

The configuration was a mistake anyone could make. The 500 was the real defect: `build_strategy`
caught `NotReadyError`, `EgressBlockedError` and `DifferentiationError`, and **every LLM-backed
route had the same shape** — each catching its own domain errors while `LlmUnavailableError` and
`NoAdapterError` fell through to a bare 500. A stage that cannot run is not a malformed request,
and it has something useful to say: no key, a provider unreachable, or a budget too small for what
was asked.

Both are now handled once, in `create_app`: **503** with the message for a stage that cannot run,
**409** for a provider with no adapter. Registered on the app rather than per route, because the
per-route version is exactly what was missing eleven times over.

The lesson generalises past this one: a diagnostic that only exists in a stack trace is not a
diagnostic. It cost an hour of live debugging to read a sentence the code had already written.

`app/main.py`, `config/llm_config` (strategy_synthesis v4), `tests/test_llm_failures_surface.py`.

## 48. A withdrawn person looked like anybody else (2026-09-21)

"jon did not create strategy even after pursue anyway." He had been withdrawn from that campaign
half an hour earlier, with the reason "strategy issue". Nothing on the Strategy tab said so.

`campaign_strategy.py` did not contain the word *withdrawn*. `people_of` selected every sequence in
the campaign regardless of status, so a cancelled one appeared as an ordinary row — same decision,
same override checkbox, same enabled action. Ticking "pursue anyway" put him into the ask, the
model declined to argue for somebody it was given no reason to argue for, and the failure surfaced
as **"the model returned no case for them — try again"**. Two AI calls were spent on that advice.
The withdrawal was the answer the whole time.

The Threads tab had shown withdrawals greyed with their reason since the feature was built. The
Strategy tab, one tab across, had never been told.

* `people_view` carries `withdrawn` and `withdraw_reason`; the row reads "Jon O · withdrawn" and
  the Default column gives the reason.
* `build()` excludes them **first** — before the threshold test — so the reason returned is the
  withdrawal rather than a rule they also happen to miss.
* An override cannot pull them back. Withdrawal is a decision, not a score, and `pursue_anyway` is
  for scores. Reinstating is its own deliberate act on the Threads tab.
* Both row actions and the drawer's new Build button refuse, and say why.

The general fault is worth naming: a state that gates behaviour was known to one screen and
invisible to the next, and the code path that acted on it had no idea it existed. The cost was not
the wasted calls — it was an error message that sent a rep to look at the model.

`services/campaign_strategy.py`, `core/pipeline.service.ts`, `campaigns/campaign-strategy.component.ts`,
`campaigns/campaign-person.component.ts`, `tests/test_campaign_strategy.py`.

## 49. Spend was invisible, and a stage was quietly running away with it (2026-09-21)

"how much it costed?" — and there was no answer to give. The `run` table carries `input_tokens`
and `output_tokens`; **none of its 54 rows had either**, and the two dearest stages, strategy and
drafting, never wrote a run row at all. Nothing anywhere recorded what a model call used.

That blindness had already cost a day. `strategy_synthesis` was configured `effort=xhigh` with
adaptive thinking against a task that writes one to three short arguments. On Gemini, thinking is
charged against the output budget, so the same request for the same person returned:

| | output tokens | result |
|---|---|---|
| Jon, 12:40 | 3,986 | no threads |
| Jon, 13:10 | 411 | one sound thread |
| Gabe, 13:10 | 790 | no threads |
| either, at a 30,208 cap | the whole budget | truncated, raised |

The variance *was* the bug, and it presented as "the model returned no case for them" — a sentence
about the person, for a failure of the provider, which sent a rep looking for their own mistake.

* **`llm_call`**, one row per call, written in `stages._run` where every stage already funnels
  through. Failures are recorded too, and they matter most: a call that burns its budget and raises
  is the one nobody would otherwise count.
* **Tokens, not currency.** A price is a fact about a contract with a vendor and changes without
  notice; a rate invented here would read as authoritative and be wrong.
* `GET /config/llm/spend` groups by stage and model and reports `worst_output` beside the average,
  because a runaway stage has an ordinary mean and a ruinous maximum — which is exactly the shape
  this one had.
* Bookkeeping cannot fail the work it measures: the write is guarded, and so is the guard's own
  logging, which threw on its first test for reading the very config that had just broken.
* An empty proposal is **retried once** and then reported as a provider failure.
* `strategy_synthesis` moved to `effort=high`, `max_tokens=48000` (v6). The next live build
  succeeded first try on **463 output tokens** — against a 30,208 cap that a single call had been
  exhausting.

`alembic d4b8f2c6a913`, `models/config.py`, `services/stages.py`, `services/campaign_strategy.py`,
`api/config.py`, `tests/test_llm_spend.py`, `tests/test_campaign_strategy.py`.

## 50. The binding was invisible, and the map went stale unwatched (2026-09-22)

Gen360 writes every touch into an LGM `customAttributeN`, and LGM's step template decides which one
it reads. That binding is the whole integration, and a rep reviewing a cadence draft could see none
of it: not where a body landed, not whether a subject line would appear at all.

Asked whether the attribute names set in LGM could be read: **no.** Templates still read
`{{customAttribute3}}`, lead payloads still key on `customAttribute1..20`, and no route exposes
labels — `/customAttributes`, `/attributes`, `/leads/attributes` are 404 and `/audiences/:id/detail`
returns name and size. So Gen360 derives its own from what each slot is used for — `email 1 body`,
`email 1 subject`, `linkedin 2 body` — which is the same naming the rep had chosen by hand, and
stays right when a template moves because it comes from the template.

**A registration read once is wrong by the next edit.** `BertieTest9-21`'s templates changed twice
during one conversation (slots 6/5 → 3/2). Its stored map still said step 1 wrote to
`custom_attribute_1` — which is what **step 2** reads. Executing would have sent the wrong message
to the right person at a plausible time. `check_shape` detected it and nothing ran: the
`changed_in_lgm` blocker keys off `lgm_updated_at`, which only moves when somebody presses the
check that would have found it.

* **One reader.** `lgm_client.read_templates` returns body, subject and channel per step, and both
  registering and re-checking use it. Two readers drift, and this mapping is the same fact the send
  path writes against.
* **Verification adopts what it reads.** It reported the mismatch and left the map wrong, so the
  only cure was delete-and-re-register — refused once a campaign uses the shape. A moved slot is no
  longer a *finding* but a *change*: the check re-read the templates, so it is the better
  authority. A shape that sequences were **drafted** against still withholds its verification,
  because their copy was written for the old slots.
* **Subjects are bound.** `subject_attribute_map` is populated at last. Drafting is told per step
  whether a subject is `allowed` rather than given a count, the prompt says to write one only
  there, and `validate_arc` refuses one that has nowhere to go — it used to be dropped in silence
  at execution, so the arc a rep approved and the message that sent were different things.
* **The screen says it.** Each body and subject carries a chip with its slot and label, in the
  person drawer and the approval arc alike, plus a count against the twenty available.

One thing fell out of showing it: the row contradicted itself. Step 1 was drafted
`linkedin_connect` and labelled `email 1 body`, because the model proposes a channel and LGM
decides one. `step_channels` now carries LGM's, the badge shows it, and a disagreement is flagged
rather than hidden — the drafted channel was never the one that sends.

`alembic e7d1c4b8a256`, `services/lgm_client.py`, `services/drafting.py`,
`services/campaign_drafts.py`, `services/instructions.py`, `api/intelligence.py`,
`api/campaigns.py`, `models/campaign.py`, `shared/lgm-slot.ts`,
`campaigns/campaign-person.component.ts`, `campaigns/campaign-detail.component.ts`.

## 51. Step 1 was never step 1, and the two steps were not a sequence (2026-09-22)

Showing each draft's attribute made a second thing visible: an **email** step's body labelled
`linkedin 2 body`. The label was right and the binding was stale — a touch's `lgm_attribute` is a
copy of the shape's mapping taken when the arc was drafted, and the mapping had since been
corrected. The words would have sent, to the right person, in the wrong message.

* **A touch follows its shape.** Re-pointed for everything not yet written to LGM, on
  verification and on every rewrite. The rewrite path updated the words, the day, the channel and
  the subject source and left the slot, so redrafting would never have fixed it — which is exactly
  what the rep asked ("or when i draft cadence again it will take care of it?").
* **Enrolled sequences keep their slots.** LGM holds that copy in the old attribute; changing our
  row would describe a sequence that is not the one running. Verification says how many are frozen.
* Verification reconciles on **every** run, not only when something moved: a shape corrected before
  re-pointing existed would otherwise never catch up.

Then, chasing "I presume LGM linkedin activity is first", `/campaigns/:id/steps` turned up —
undocumented, and it answers what `/messages` cannot:

```
position 4  GOOGLE_SEND_EMAIL        "Not Accepted - Email"
position 5  LINKEDIN_DIRECT_MESSAGE  "Accepted - DM"
```

Two facts Gen360 had wrong. The message templates sit at **positions 4 and 5**, so three earlier
steps — a profile visit, a connection request, a wait — carry nothing of ours and `/messages`
cannot see them: **"step 1" here was never step 1 there**, and the rep's instinct about LinkedIn
running first was correct where our screen implied otherwise. And the names say these are not a
touch and its follow-up but **two branches of one moment**: email if the invite was not accepted,
DM if it was. Copy that reads as a follow-up is wrong whenever the other never sent — drafting is
now told the names and told to make each branch stand alone.

Position and name are shown on every touch. A subject on a step that cannot carry one is struck
through with "will not send" rather than displayed as though it will.

`alembic e7d1c4b8a256`, `alembic f8c2a5d9e134`, `services/lgm_client.py`,
`services/campaign_drafts.py`, `services/instructions.py`, `api/intelligence.py`,
`api/campaigns.py`, `models/campaign.py`, `shared/lgm-slot.ts`,
`campaigns/campaign-person.component.ts`, `campaigns/campaign-detail.component.ts`.

## 52. Three minutes a company, and a ceiling that made failure expensive (2026-09-23)

"why does it take 3 minutes to run one strategy... as per this timing if u have 100 contact, it
will take 3000 minutes."

`effort=high` maps to Gemini `thinkingLevel: high`, and thinking is charged against
`maxOutputTokens` **and** runs on the clock. So a derailed call did not fail — it thought until one
of the two ceilings stopped it: 48,000 tokens, or the 180-second client timeout. A sound call on
the same stage took **9 seconds**. The variance was the whole problem; the average never showed it.

The arithmetic was worse than the rep's: strategy is per company, drafting is per person at ~25s
each, and `SequentialRun` issues them one at a time by design. A hundred contacts meant an hour.

* **The ledger was blind to exactly the calls that mattered.** `_record_call` flushed onto the
  caller's session, so a failed call wrote a row and lost it when the route never committed. The
  test passed by asserting inside that same session, before any rollback — it proved less than it
  claimed. Now written in its own transaction, bound to the caller's engine rather than the app's
  global factory, with a test that rolls back and then looks in a fresh session.
* **A stage gets its own clock.** 60s for strategy, 75s for drafting, against the 180s default that
  research genuinely needs.
* **A derailed call is retried one thinking level quieter** rather than identically. A timeout and
  a budget blowout are the same failure wearing two faces, and both qualify.
* **Concurrency moved to the server.** `POST /campaigns/{id}/strategy/batch` and
  `/campaigns/{id}/drafts/write-many` run five at a time behind a semaphore, each unit in its own
  session so one failure costs one company.
* **The ceiling came down, and that was the fix.** Measured good calls use 82–916 output tokens.
  At 24,000 a runaway burned 108 seconds before failing; at **8,000** it fails early enough for the
  quieter retry to land. The account that had failed every attempt for three days built in 23.6s,
  then in 12.8s alongside another.

Two experiments failed and are recorded because the next person will have the same idea:

* **`maxItems` on the threads array** — the obvious way to stop a call writing threads until the
  budget ends. Gemini answers **HTTP 400** to a schema carrying it, despite `_KEPT` listing it as
  supported. Every call broke until it was reverted.
* **`maxLength` on the strings** — same idea, same 400.

The bound that worked was not in the schema at all. It was the token ceiling: make failure cheap
and the retry does the rest.

Measured, before and after, on the campaign that prompted this:

| | before | after |
|---|---|---|
| Snowflake | failed at 180s | built, 6.4s |
| Workday | failed at 180s | built, 23.6s then 12.8s |
| both together | ~6 min, both failed | **12.8s, both built** |

`services/stages.py`, `services/llm.py`, `services/gemini.py`, `services/gemini_schema.py`,
`api/campaign_strategy.py`, `api/campaign_drafts.py`, `core/pipeline.service.ts`,
`campaigns/campaign-strategy.component.ts`, `tests/test_llm_budget.py`, `tests/test_llm_spend.py`.

## 53. Still open

* **La Growth Machine**, last, as `docs/12` orders it.
* The research reuse window records nothing on the run itself about which window applied. The
  config history answers it; a column on `run` would make it direct.

## 53. What 138 model calls bought (2026-10-03)

Researching three contacts took **138 model calls, 305k input tokens and 3m37s**, and produced
**three passages and one signal**. Four things were wrong, and one of them was mine.

* **The dedup hash let near-duplicates through.** It normalised whitespace but not case or trailing
  punctuation, so the same line from the same page was stored twice, one full stop apart:
  `"Christian DeKnock. Design & Communications Manager"` and the same again with a period. Folded
  now; only *trailing* punctuation goes, because "we raised $4M." and "we raised $4M?" are not the
  same claim.
* **`not_found` was carrying two different meanings.** The site sweep wrote volume remarks into the
  field meant for "searched for this, it is not there", so a sweep that found thirty entries and
  kept ten reported `ran · 10 evidence · 1 not established`. Nothing had failed. `notes` now holds
  remarks about the shape of what came back, `not_found` holds misses, and the screen leads with
  the former. Same split applied to the job-board reader.
* **A family unknown to the registry ran in every scope.** `job_board` is `scopes: ["company"]` and
  the filter honouring that only applied to families the registry *knew* — so with the row absent
  it ran once per person, searching for the company's Greenhouse board under each of their names.
  An unknown family is now company-scoped until something says otherwise.
* **`linkedin` has produced nothing, ever**: 16 runs, 0 evidence, while all 57 accounts already
  hold a `linkedin_url` from Apollo. We may not fetch linkedin.com (invariant 10's neighbour) and
  search engines index almost none of it. Paused.

The third one needs owning: the registry row was missing **because of the wipe earlier that day**,
when a hand-written keep-list missed three configuration tables. So the measurement that exposed
the latent bug was inflated by a mistake of mine, and the first diagnosis — "company families run
per contact by design" — was wrong. The guard is still worth having: it is exactly the condition a
missing row creates.

`services/evidence.py`, `services/site_sweep.py`, `services/job_boards.py`, `services/research.py`,
`services/pipeline.py`, `api/intelligence.py`, `models/research.py`, `alembic a2d6f9b4c813`,
`accounts/account-detail.component.ts`, `tests/test_research_scope.py`.

### Efficiency, deferred until the app says it is needed (2026-09-23)

Three changes assessed against a proposed architecture and held back deliberately: §52 already took
the run that mattered from six failing minutes to 12.8 seconds, and these are worth doing only if
that stops being fast enough. Each is small, measurable against `llm_call`, and independent.

1. **Cap the array in the prompt, not the schema.** "Return at most N" in `instructions.py`. The
   schema route — `maxItems` on `StrategyProposal.threads` — is the obvious version and Gemini
   answers **HTTP 400** to it (§52). The prompt is the one lever left.
2. **Bring `outreach_drafting`'s ceiling down.** Still `max_tokens=24000` against a measured 644.
   Strategy's drop to 8,000 is what finally let a derailed call fail early enough for the quieter
   retry to land; drafting has not had the same treatment, so its failures stay expensive.
3. **Try drafting with thinking off.** `gemini.build_request` already takes `thinking: bool` and
   nothing ever passes `False`. Drafting fills a structured contract from a strategy that has
   already been reasoned through, so it may not need to think at all. Cheap to test, trivial to
   revert, and the ledger will say whether it cost quality in output tokens or latency.

Assessed and **not** taken from the same proposal, so nobody re-litigates them:

* *Compress the input context to ~1.5k tokens* — inputs are already 2,219–2,680 and the failures
  had `in=0`. Output is what runs away; this aims at the wrong half.
* *Fall back to a template draft when the model fails twice* — produces copy nobody approved on the
  one path where a human reading it is the point. A failed draft stays failed and says so.
* *Match prompt key order to schema key order* — plausible, no evidence either way. Measurable if
  it ever matters: same input, both orders, compare output tokens.
* *Avoid live web search during strategy* — already the architecture. Tools attach to
  `company_research`, `signal_scan` and `decision_maker_enrichment` only.

## §54 — A signal could be born already expired (2026-10-04)

**The report.** A `mgt_change` for Champion Risk, observed **1 April 2021**, expired **28 September
2021**, still stored and on screen in October 2026. The question asked was whether to keep a maximum
retention age — "three times the signal life" — and delete past it.

**What measuring found.** Every signal held, aged at the moment it was stored:

| signal | observed | ttl | age when stored |
|---|---|---|---|
| `mgt_change` Kristy Neal | 2021-04-01 | 180 | **2011 d** |
| `mgt_change` Brown & Brown | 2021-05-17 | 180 | **1965 d** |
| `partnership` Simplicity | 2023-04-26 | 180 | **1256 d** |
| `mgt_change` Simplicity | 2023-04-26 | 180 | **1256 d** |
| `mgt_change` Mick Jordan | 2025-01-03 | 180 | **638 d** |
| `tech_adoption` RFP360 | 2025-02-28 | 365 | 582 d |
| `public_focus` Champion | 2026-08-29 | 90 | 35 d |

**Five of eight were already past `expires_at` on the day they were created.** `expiry_for` is
`observed_at + ttl` and nothing compared its answer to today. `_reject_reason` checked evidence,
scope and `contact_id`; not age.

**What the intake gate is worth, and what deletion is not.** `context.live_signals` already filters
on `expires_at`, and `drafting` refuses a stale citation — so those five signals were in **zero
prompts** and changed no outreach. Deleting them would have reclaimed rows and altered no behaviour,
while colliding with invariant 2 and with the `trigger_signal_ids` / `cited_signal_ids` that make an
approved sequence explainable. The cost they imposed was that a rep could see them. So: gate at
intake, do not delete.

**`durability_days`** (`alembic b5e9a3c7d241`) is the second question's answer, nullable, defaulting
to `3 × default_ttl_days`. `default_ttl_days` had been carrying two jobs — *when does this stop
being a hook* and, by omission, *is this still worth reading at all*. An acquisition is permanently
true and permanently useless as an opener.

**Three gates, and why the obvious simplification is wrong.** The tempting version is one window per
family. It is a regression: *a source says what research opens; signal types say what is read out of
it*, and every document a source returns is interpreted against every active type. `news` feeds
`mgt_change` (540 d), but a `news` document at 700 days can still produce a `tech_adoption` signal
(1095 d). So the research and intake window is the **widest durability across all active types** —
1095 d today — and the exact per-type cut happens at extraction:

| gate | window | catches, on the live data |
|---|---|---|
| research prompt (`ignore_published_before`) | widest = 1095 d | asks for nothing older |
| evidence intake (`StoreOutcome.stale`) | widest = 1095 d | the 2021 ×2 and 2023 ×2 rows |
| extraction (`_reject_reason`) | `3 × ttl` per type | Mick Jordan, 638 d vs 540 |
| neither | — | RFP360 kept: 582 d, durability 1095 |

Two details that are not incidental:

* **The cutoff in the prompt is a month, not a day.** A date that moves daily moves the prompt
  daily, and a prompt that differs byte-for-byte never hits cache — the same trap as a timestamp in
  serialised config. `cutoff_for_prompt` renders "October 2023".
* **Undated evidence is admitted, not refused.** 51% of the rows held carry no `observed_at` at all
  — every provider and job-board passage. Treating undated as stale would have thrown all of it
  away. The gate refuses a date that is too old; it never infers one.

**Four tests were lying, and the new query is what exposed it.** `store_found` now runs a second
query, and four fake sessions answered every query with one canned list — handing `durability_of` a
hash string. The failures were oblique (`AttributeError: 'str' object has no attribute
'durability_days'`, an `IndexError` on `outcome.stored[0]`) and none pointed at the fake.
`conftest.LongLivedSignalType` / `is_signal_type_query` are now shared, following the
`__tablename__`-matching convention `test_llm_call_sites.FakeSession` already documented. Separately,
`TestWhereTheDateLands` asserted against `evidence._to_row`, which no longer derives the date — the
derivation moved to the caller so the gate tests the date the row actually carries. Left alone,
those two tests would have passed while the real path did nothing.

A front-end test read its cell as `td.mono + td.mono` and began asserting about Durability when the
column landed between TTL and Weight. The cells now carry `data-col`.

**Not done, deliberately.** The expired-signal display grouping — a rep still sees a 2021
appointment beside a current one with only a date between them. And the snapshot purge
(`raw_status='purged'`) that a real retention policy would hang off: every row reads `unavailable`
because nothing is snapshotted to object storage yet, so there is nothing to purge.

`services/durability.py` (new), `services/evidence.py`, `services/extraction.py`,
`services/stages.py`, `services/instructions.py`, `services/pipeline.py`, `models/config.py`,
`schemas/config.py`, `api/config.py`, `alembic b5e9a3c7d241`, `core/config.service.ts`,
`settings/signal-types.component.ts`, `tests/test_durability.py`, `tests/conftest.py`,
`tests/test_extraction_guard.py`, `tests/test_evidence_dedup.py`, `tests/test_linkedin.py`,
`tests/test_llm_call_sites.py`, `tests/test_job_boards.py`.

## §55 — Expired signals read as news (2026-10-04)

The item §54 left open. A `mgt_change` from **2021** sat on the signals tab beside a current one
with only a date between them. It was in zero prompts the whole time — `context.live_signals`
filters on `expires_at` — so the screen was the only place it could mislead anyone, and it did.

**Found while building it: `superseded_by` was never exposed.** `SignalOut` carried `expires_at` and
`lifecycle_state` and stopped there, so a theme that a newer reading had replaced rendered as
`validated` — indistinguishable from live. `drafting` refuses to cite a superseded signal exactly as
it refuses an expired one, which makes that the worse of the two bugs: the only symptom is a signal
a rep expected to see quoted in a draft and never did. So **live** on this screen now means what it
means in `drafting` — not expired **and** not superseded.

Piper Jordan, before and after: "4 signals", three of them stale and unmarked → **1 live, 3
background** (`tech_adoption` 2025-02-28, `mgt_change` 2025-01-03, `mgt_change` 2021-05-17).

The group is a collapsed `<details>` — the clutter was the complaint — labelled "Background — no
longer a trigger", with "Still true. Past its durability as a hook, so it is not cited in outreach."
Three details that are decisions rather than styling:

* **The open state is a signal, not left to the element.** Switching tabs destroys the `<details>`
  and would silently re-collapse a group the rep had opened.
* **Receded, not faded.** `.sig-bg` is a dashed border, not reduced opacity: opacity would take the
  evidence excerpts down with it, and those are the only reason to open a background card.
* **"Nothing live" is distinct from "no signals yet".** Research ran and found things, all of them
  history. One empty state for both would read as never having looked — the same confusion §53 fixed
  in coverage.

The card markup is one `ng-template` used by both groups. Two copies drifted apart the last time a
badge was added to only one of them.

`account-detail.component.spec.ts` is **new** — the screen had no spec at all, and the partition is
the kind of claim that should not go untested. 13 tests, including the superseded-but-unexpired case
and the precedence of "superseded" over "expired" when a signal is both.

`api/intelligence.py`, `core/pipeline.service.ts`, `accounts/account-detail.component.ts`,
`accounts/account-detail.component.spec.ts` (new).

## §56 — "900d ×3" read as 2700 days, and the editor covered half the row (2026-10-04)

Two corrections to the signal type registry, both reported from the screen.

**The marker beside the number.** §54 rendered a derived durability as `900d ×3`, meaning *this 900
is three times the 300-day TTL*. It was read the other way — as a multiplier still to apply, 2700
days — which is the obvious reading when a `×` sits next to a figure. The number now stands alone
and the derivation moved into the tooltip: *"The default: three times the 300-day TTL."* A type with
an explicit value says so instead, and names what the default would have been.

**The editor was never finished.** The row editor covered TTL, durability, weight, kind, and the
extra search — but not `label`, `description` or `produced_by`, all three of which `SignalTypePatch`
has always accepted. So the three fields that decide what a type *means* could be set when it was
created and never afterwards, and `description` goes straight into the extraction prompt.

Label edits in the Type cell; description and the source grid in a full-width row that opens beneath
while editing — prose and a dozen checkboxes do not fit in a column, which is how they came to be
uneditable. The key and scope stay read-only, with the key's tooltip saying why: it is in the output
schema and in every stored signal's `signal_type`.

Three details that are decisions:

* **`edit.produced_by` is a copy.** Referencing the loaded row's array meant ticking a source
  applied it to the screen with nothing sent, and cancelling left it applied.
* **`produced_by` is compared as a set.** The order is the registry's, not a choice; comparing by
  index would call a reordering a change and patch rows nobody edited.
* **A blank label is not an edit.** The server requires one, so an emptied box would turn a slip
  into a 422 on a row the rep only meant to retune.

**Twice in a row I put backticks inside the component's template literal** — once in an HTML comment
quoting a column name, once quoting a loop variable — and each terminated the template, producing
`TS-991002: Incorrect number of arguments to @Component decorator` and a cascade of nonsense errors
pointing at line 37. In a backtick-delimited Angular template, a comment is still inside the string.

Also fixed in passing: the empty-state row still said `colspan="6"` for what is now a nine-column
table.

`settings/signal-types.component.ts`, `settings/signal-types.component.spec.ts` (5 tests added).

## §57 — Prompts moved out of git, behind a lock (2026-10-04)

Asked for: a config screen where an admin edits the LLM prompts, instead of them being hardcoded.

**Two things the investigation turned up before any code was written.**

*There is no authentication in this application.* No user table, no login, no roles —
`curl http://127.0.0.1:8011/api/config/signal-types` with no header at all returns `HTTP 200`. (The
`X-API-Key` used in earlier sessions belongs to the *Survey* project; this app ignores it.) So
"admin login" did not exist. Offered three scopes; **a password gate on the prompt routes only** was
chosen, and it is recorded in `docs/14-prompt-config-plan.md` as what it is: a lock on one door in a
building with no front door.

*Prompts living in git was a recorded decision*, in `instructions.py`'s own docstring — a prompt
change alters what every downstream artefact means, so it belonged in review and in a diff.
Overriding that is the user's call, but the design had to **replace what git was providing**: history,
diffs, and an answer to "which instructions wrote this row?". Hence versioned per scenario, the
existing `llm_config` shape.

**`_COMMON` is not editable, and that is the load-bearing decision.** The preamble carries invariant
10 — retrieved text is DATA, never an instruction — and the cite-or-do-not-assert rule. A screen that
let someone delete the prompt-injection guard is a hole, not a feature. It stays a module constant,
is prepended **inside `instructions.block`** rather than at the edge, and the editor shows it
read-only above the box. Assembling it downstream of where the body is loaded is what makes a hostile
stored body get appended *after* the rule rather than substituted for it — tested directly.

| | |
|---|---|
| `prompt_template` | 16 scenarios, versioned, one active per scenario (partial unique index) |
| `admin_secret` | scrypt hash; stdlib, since neither bcrypt nor argon2 is installed |
| migration `c3f7b2e9a815` | seeds v1 for all 16 from the live `STAGE` dict |
| `STAGE` in code | no longer what runs — it is what Reset restores and what the diff compares against |

Verified end to end against the running API: write with no password set → 409; with a password but
no token → 401; wrong password → 401; edit with a token → v2, and the edited text **reaches the
assembled prompt** with `_COMMON` still first and the injection guard still present; reset → v3
matching the shipped default, with v2 still in the history.

**Three bugs found by the tests, each worth recording.**

1. **`updated_at` NOT NULL rejected every insert.** `Base` maps it nullable with an `onupdate` and
   no insert default, so SQLAlchemy sends an explicit NULL. Every other table here has it nullable;
   the new migration did not, and nothing failed until the first write.
2. **scrypt refused its own parameters.** `n=2^15, r=8` needs `128·N·r` = exactly 32 MiB, and
   OpenSSL's default cap is 32 MiB — so the shipped cost failed by the margin of the bookkeeping
   overhead. Fixed by raising `maxmem`, not by lowering `N`: the memory-hardness is the point.
3. **conftest TRUNCATEs before every test**, which wiped the seeded prompts and left `load_prefix`
   silently falling back to the shipped text — a suite that passes while the feature it tests is
   bypassed. Re-seeded alongside the existing research-sources hook, for the same reason.

The settings nav order is pinned by a test that explains its own sequence. "Prompts" went beside
"Model config" — how hard a stage thinks and what it is asked to do are two halves of one question —
and the test's reasoning was extended rather than the list quietly re-sorted.

`models/config.py`, `services/prompts.py` (new), `services/admin_gate.py` (new),
`services/instructions.py`, `services/stages.py`, `services/prompt.py`, `api/prompts.py` (new),
`main.py`, `alembic c3f7b2e9a815`, `core/config.service.ts`, `settings/prompts.component.ts` (new),
`shared/icon.component.ts`, `app.routes.ts`, `app.component.ts`, `tests/conftest.py`,
`tests/test_prompt_config.py` (new, 27), `settings/prompts.component.spec.ts` (new, 16).

## §58 — The prompt reference, as a document (2026-10-04)

Asked for: every prompt, including the one that cannot be changed, in one downloadable Word file.

Both halves exist — a **Download all as Word** button on the Prompts screen, and
`backend/scripts/export_prompts.py` for when a shell is nearer than a browser. Both call
`services/prompt_export.py`, because a document generated two ways becomes two documents.

**The preamble is the reason this is worth having.** Every stage is sent `_COMMON` + body, so a
reference containing only the bodies documents a system nobody runs — and it is exactly the part a
reviewer would not notice was missing. It gets its own section, labelled as not editable. Tested
directly rather than assumed.

Three judgements in the document itself:

* **The live text, not the shipped text.** Read from `prompt_template`, so an edit made in the UI is
  in the next export. An export that showed the shipped defaults would be confidently wrong.
* **The original alongside, only where something changed.** Printing it for all sixteen would double
  the length to say "unchanged" fifteen times.
* **Pipeline order, not alphabetical.** `instructions.STAGE`'s own order groups research, extraction,
  qualification, strategy and content. The screen sorts alphabetically and scatters them; a document
  read start to finish should not.

Prompts are rendered monospaced and line for line. The line breaks are load-bearing — several blocks
are lists the model reads item by item — and Word's default paragraph spacing turns them into
something that reads differently from what is actually sent.

**Route ordering is load-bearing.** `GET /prompts/export` is declared **before**
`GET /prompts/{scenario}`; FastAPI matches in declaration order, so the other way round "export"
arrives as a scenario name and the download 404s. Verified that `/prompts/evaluation` still resolves
and `/prompts/not_a_stage` still 404s.

The button is **not** behind the lock. Everything in the document is already readable on the screen;
collecting it into a file changes how convenient it is to review, not who may see it. It fetches
through `HttpClient` into a blob rather than pointing an `<a href>` at the route — one path in
development and production, and a failure surfaces on the screen instead of replacing the app with
a browser error page. The object URL is revoked immediately; the blob is a copy of the whole
reference and the handle would hold it for the life of the tab.

`python-docx` installed without trouble, which narrows the earlier diagnosis usefully: **PyPI is not
blocked on this machine, only git push egress.** Added to `pyproject.toml` as a runtime dependency,
not a script's — the API serves the document now.

`prompt-reference.docx` is generated, so it is in `.gitignore`.

`services/prompt_export.py` (new), `api/prompts.py`, `scripts/export_prompts.py` (new),
`pyproject.toml`, `.gitignore`, `core/config.service.ts`, `settings/prompts.component.ts`,
`shared/icon.component.ts`, `tests/test_prompt_config.py` (+5), `prompts.component.spec.ts` (+2).

## §59 — The fast sweep gate (2026-10-04) · Phase 1

One cheap, broad call before the per-family passes. Nothing found, nothing bought.

**What paid for it.** Three contacts cost **138 model calls, 305k input tokens and 3m37s**, and
produced three passages and one signal. Most of that was families reading pages that held nothing,
for accounts with nothing to find.

**`signal_scan` already existed and nothing called it.** Defined at `stages.py:699`, with its own
prompt, its own `llm_config` row (`gemini-3.5-flash-lite`, high effort) and zero callers. The
"Phase 1 fast sweep" asked for was a function already in the codebase, unwired.

**The gate is skipped, never silent.** Every planned family still gets a coverage row saying it was
not run and why — the rule this pipeline is built on is that recording only the successes turns a
gap into apparent completeness. "We looked quickly and there was nothing" is a finding a rep can
act on; a blank is not. The sweep gets its own coverage row under `fast_sweep`, so it reads
differently from "this source was read and was empty".

Four decisions that are not incidental:

* **It fails open.** A sweep that raised has not established that there is nothing here, and
  treating its failure as "nothing found" would skip a whole account on an infrastructure fault —
  the expensive kind of wrong, because it looks exactly like a quiet prospect. This also makes the
  90-second box safe: a sweep that overruns degrades to today's behaviour rather than wrongly
  gating.
* **Duplicates open the gate.** A sweep returning only passages already held has still established
  the account has something to read. The gate asks "is this worth reading?", not "is this new?".
  `SweepOutcome` carries `stored` and `found` separately for exactly this: coverage reports what was
  written, the gate tests what was turned up.
* **What the sweep finds is stored**, filed under `fast_sweep`. Discarding it would mean paying for
  the call and then paying again for a family to find the same sentence.
* **Opt-in, and switchable from the URL.** `run_sweep` is injected like the family runners, so every
  existing caller behaves exactly as before. `POST /lists/{id}/run-research?fast_sweep=false` turns
  it off — a query param rather than buried config, because the first thing anyone needs to do with
  a gate is run the same list both ways and compare the ledger.

**A no-op caught in my own change.** I first set `company_research: 180.0` in
`STAGE_TIMEOUT_SECONDS` as the document's "2–3 minute" box. `TIMEOUT_SECONDS` is **already 180.0**,
so it capped nothing while reading as a deliberate limit — and would have silently stopped tracking
the default if that moved. Removed; only `signal_scan: 90.0` is genuinely new. A test
(`test_an_unnamed_stage_keeps_the_long_default`) had encoded the old intent and failed, which is how
it surfaced.

`services/pipeline.py`, `services/gemini.py`, `api/lists.py`, `tests/test_research_pipeline.py` (+7).

**Still to come:** Phase 2 (seven Enterprise IT signal types, deprecation deferred until after a
measured run), Phase 3 (source mapping; both the `site:` operator route and the sub-path crawler,
measured against each other), Phase 4 (LinkedIn via Google index — never fetching linkedin.com),
Phase 5 (ICP track routing and the two buyer voices).

## §60 — Seven Enterprise IT signal types (2026-10-04) · Phase 2

The registry shipped built for technology companies. The book is 57 insurance brokerages, and the
measurement said so plainly: of thirteen active types, **five had ever produced a signal and eight
had produced nothing** — and the eight were the tech-company ones.

Migration `d7a4e1c93b26` adds the Enterprise IT equivalents. Not speculative for this book: three of
the eight stored signals were already acquisitions, filed under `mgt_change` and `partnership`
because nothing better existed. `mgt_change`'s own description reads *"If there is Top Management
change or Merger or Acquisition etc"*, which is exactly why they landed there.

| type | kind | ttl | durability | weight |
|---|---|---|---|---|
| `m_and_a_integration` | event | 365 | **3650** | 2.00 |
| `compliance_security_deadline` | event | 180 | 540 | 1.50 |
| `leadership_vendor_review` | event | 90 | 270 | 1.50 |
| `tech_debt_modernization` | theme | 365 | 1095 | 1.50 |
| `digital_transformation_mandate` | theme | 365 | 1095 | 1.25 |
| `hiring_bottleneck` | theme | 90 | 270 | 1.25 |
| `vendor_consolidation` | event | 270 | 810 | 1.25 |

**Only two carry a `search_instruction`, and they share a group.** The convention is that an
instruction is an exception — every source read is interpreted against every type anyway, so words
of its own earn their place only where a general sweep would reliably miss the fact. Giving all seven
one would have added seven searches per account to a change made for efficiency.
`compliance_security_deadline` and `tech_debt_modernization` qualify because their evidence lives
where nothing currently looks: `company_site` is a **feed reader** and will never open `/security`.
Grouped as `enterprise_it_estate`, verified to merge into one search carrying both.

**A coupling worth knowing about: the research intake window widened from October 2023 to October
2016.** `widest_durability` is the max across active types (§54 — a `news` document is read against
every type, so the sweep cannot be narrowed to the types that named the source), and
`m_and_a_integration` at 3650 days is now the widest. Setting one type's durability high widens what
research reads for *everything*. That is correct — a 2018 document can legitimately yield an
acquisition signal — and the per-type extraction gate still refuses stale signals for every other
type, so the 2021 noise is caught one gate later rather than admitted. But it costs extraction calls
to catch it there, and if the measured run shows research dredging, lowering that one number in the
Prompts-adjacent signal-types screen narrows it again with no deploy.

**Deprecation deliberately deferred.** The eight unproductive types stay active until a measured run
exists to compare against — one of them may be right for the technology track, and the comparison is
cheap to make once and impossible afterwards. That leaves **20 active types** in the interim, each
interpreted against every document. Real cost, temporary.

`leadership_vendor_review` overlaps `mgt_change` (company) and `role_change` (contact) on purpose,
and its description says so. If both fire on the same evidence it is the narrower reading; if it
never fires while they do, it is the one to drop. That is a question for the measured run.

`alembic d7a4e1c93b26`, `docs/schema/full-schema.sql`.

## §61 — Sources: the enterprise board and the page fallback (2026-10-04) · Phase 3

Two readers that were looking in the wrong places, and a second route kept deliberately so the
choice between them can be measured rather than argued.

### Workday

`job_board` produced **zero evidence across every run** and the reason was not that the accounts
are not hiring. The reader knew Greenhouse, Lever and Ashby — three boards that between them host
*startups*. A non-technology company of any size is on Workday, iCIMS or Taleo. Fifty-seven
insurance brokerages were read by a reader that could not see their job boards.

Workday is structurally unlike the other three and the differences are the work:

* **Its API answers a POST, not a GET.** A search endpoint taking facets, an offset and a limit. The
  wrong verb returns nothing, which reads exactly like a company with no open roles — so
  `Board.post_body` exists to make the caller branch, and a test asserts the verb.
* **Its address has three parts.** `acme.wd1.myworkdayjobs.com/en-US/External` is tenant, cluster
  and site; `wd1` and `wd5` are different machines and neither can be guessed from a company name.
  `Board` gained `cluster` and `site`, and the dedupe key gained the site — one tenant with
  `External` and `Internal` boards has two, and they must not collapse into one.
* **`postedOn` is prose.** "Posted 30+ Days Ago", not a date. Deliberately **not** parsed into
  `opened`: inventing a date from "30+" would put a guess in the field every expiry calculation
  trusts. It is kept in the excerpt instead, where it is the most useful sentence on the
  posting — a role advertised for thirty days is the `hiring_bottleneck` signal, stated by the
  employer. `startDate` is used when a tenant sends one, and only then.

### The sub-path fallback

`company_site` is a **feed reader**. `FEED_PATHS` is ten RSS/Atom locations and nothing else — so a
compliance deadline, which lives on `/security` or `/trust` and is never in a feed even on a site
that has one, could not be produced from it by any wording of any prompt.

When no feed answers, `PAGE_PATHS` is now read as HTML: `/news`, `/newsroom`, `/press`,
`/about/news`, `/security`, `/trust`, `/compliance`. A **fallback**, not the first choice — a feed
is dated, bounded and meant to be read by a machine, where a page is none of those.

Pages are stored **undated**. A page carries no publication date the way an entry does, and dating
it from the fetch would stamp today on a company's entire history. The intake gate admits undated
evidence precisely so this is possible (§54).

**Both routes to these pages now exist and are distinguishable.** The other is a grounded search
with `site:` operators, which costs a model call instead of four HTTP requests and produces evidence
under the signal type's own family. The fallback writes `read_pages` into its coverage notes. Which
is better is a query after the measured run, not an argument before it — which is how this was
asked for.

**A threshold that was wrong by inspection.** `MIN_PAGE_CHARS` started at 400 and a test fixture
landed at 386, which looked like a fixture problem and was not. A script shell measures **zero**
characters once tags are stripped, so the floor needs nowhere near 400 of headroom, while a terse
but genuine trust page runs to about 380 — the threshold was discarding real pages to exclude
emptiness that registers as nothing at all. Now 250.

`services/job_boards.py`, `services/site_sweep.py`, `tests/test_job_boards.py` (+14).

**Phase 3 remaining:** the `site:` operator instructions for the other signal types are config and
can be written from the Prompts-adjacent signal-types screen without a deploy. Phase 4 (LinkedIn via
the Google index) and Phase 5 (ICP track routing, two buyer voices) are untouched.

## §62 — LinkedIn: the brief was already right (2026-10-04) · Phase 4

Phase 4 was to rewrite `linkedin`'s search instruction with Google `site:` operators and unpause it.
**The premise was wrong.** The brief already had them:

> Search `site:linkedin.com/company/<slug>`, `site:linkedin.com/posts/<slug>` and
> `site:linkedin.com/in/<slug>`, using the LinkedIn URL given when there is one. Quote only what the
> search results show; never open a linkedin.com page.

That is doc 1's recommendation, already implemented, word for word. Everything else it needs was in
place too: `_account_facts` passes `linkedin_url`, `keep_own_linkedin` drops only a *definite*
mismatch, and `gemini_grounding` resolves redirects with `follow_redirects=False` reading the
`location` header — so unpausing would not have fetched linkedin.com.

So rather than rewrite correct config, three live probes:

| account | employees | evidence |
|---|---|---|
| Charity First Insurance Services | — | **0** |
| NFP Property and Casualty Services | 7,700 | **0** |
| Philadelphia Insurance Companies | 2,100 | **0** |

The first returned the queries it had run, which are exactly the ones specified:

```
site:linkedin.com/company/charity-first-insurance
site:linkedin.com "Charity First Insurance Services"
```

**Google's index holds almost nothing for these companies, and it is not a size effect** — a
7,700-employee account returned as little as a twenty-person broker. Sixteen runs of zero were the
system working correctly and reporting honestly. Re-enabling needs a different *retrieval route* — a
SERP API queries Google directly, a different posture from Proxycurl, which scraped LinkedIn and was
sued into shutdown — not a different instruction. It stays paused.

**The real defect was that none of this was recorded where the decision gets made.** §53 paused the
source on evidence; the database said only `paused`. Three sessions later the obvious next move
looked like "the instruction must be wrong", and it cost three model calls to rediscover a
conclusion already reached. `research_source.status_reason` (migration `e2b9f4c71d38`) now carries
the why, surfaced on the Research screen beside the status under a `why` disclosure — read by
someone about to turn a source back on, which is the only moment it matters.

`alembic e2b9f4c71d38`, `models/config.py`, `schemas/config.py`, `core/config.service.ts`,
`settings/research.component.ts`, `settings/signal-types.component.spec.ts`,
`docs/schema/full-schema.sql`.

## §63 — The buyer track (2026-10-04) · Phase 5

An ICP now says which buyer it is for, and the argument follows from it. Two tracks and only two:
`tech_company` is an ISV, SaaS or IT product company — software is what it sells — and `enterprise`
is everything else, a non-technology business running internal IT. Insurance brokerages sit *inside*
`enterprise` rather than beside it.

**No new plumbing.** The track rides in the ICP's `definition` next to `sources` and
`signals_that_matter`, because it is the same kind of statement — what this list is for — and
`load_prefix` already puts the definition in the cached prefix. Verified end to end: the track
reaches the assembled `strategy_synthesis` prefix, the instruction branches on it, and
`prompt_version` comes back as 2 for stamping.

`strategy_synthesis` and `outreach_drafting` gained the two registers. A CIO measured on nothing
going wrong does not read the argument written for a CTO measured on what ships — risk, continuity
and the cost of carrying what is fragile, against bandwidth and time to market. An ICP that states
no track means neither is established, and both prompts say so explicitly: argue from the evidence
rather than guess which buyer this is.

**Both halves of each prompt were updated, and that is the point.** `instructions.STAGE` is the
shipped baseline "Reset to shipped" restores; `prompt_template` is what actually runs (§57).
Changing only the table would leave Reset quietly restoring the older text months later; changing
only the code would leave the new words unused. Migration `f4c8d2a91e57` writes the new version
*from the code*, so the two cannot disagree — and it **skips any scenario whose live body is past
v1**, because someone edited that deliberately and a migration overwriting it would be the one way
this feature could destroy a rep's work.

**A typo had to fail loudly.** The definition is free-form JSON, so an unrecognised key is normally
harmless — but the prompts *branch* on `track`, and a value they do not know falls through to "no
track stated". Safe, and silent: `"enterprize"` would cost every draft on that list its register
with nothing anywhere saying so. `ICP_TRACKS` is validated in `IcpDefinitionIn`; the rest of the
document stays open.

**Two bugs found while wiring the editor**, both the same shape — a new field kind that the
read and write paths did not know about:

* `compose()` had no `choice` branch, so a track was read in and **silently dropped on the way back
  out**. Every save would have erased it.
* `hydrate()` would have shown an unrecognised value as selected, displaying "enterprize" as though
  it were one of the two — exactly the confusion the server-side validator exists to prevent. It now
  falls through to passthrough, where the JSON view can still reach it.

Radios rather than a dropdown: there are two, both need their explanation read, and a select hides
the one not chosen.

`alembic f4c8d2a91e57`, `services/instructions.py`, `schemas/config.py`,
`settings/icp-editor.component.ts`, `tests/test_icp_profiles.py` (+4),
`settings/icp-editor.component.spec.ts` (+4), `docs/schema/full-schema.sql`.

**Phases 1–5 are complete.** What remains is the measured run: the same list through
`?fast_sweep=true` and `?fast_sweep=false`, compared against the 138-call / 305k-token / 3m37s /
1-signal baseline — and with it the two deferred decisions, deprecating the eight unproductive
signal types and choosing between the `site:` operator route and the sub-path crawler.

## §64 — Correcting §62: it is the grounding tool, not the index (2026-10-04)

**§62's diagnosis was wrong**, and the error was reasoning from a sample that could not distinguish
two explanations.

Three company probes returned zero, and §62 concluded *"Google's index holds almost nothing for
these companies, and it is not a size effect"*. Both halves of that sentence came from the same
three brokerages. The half about size was sound — 7,700 employees returned as little as twenty. The
half about *these companies* was not tested at all, because every probe was a brokerage.

Asked directly whether LinkedIn post search was returning anything, two further probes settled it:

| probe | evidence |
|---|---|
| Mark Raby @ Champion Risk — contact scope, `/in/` queries | 0 |
| **Satya Nadella @ Microsoft** — the most indexed LinkedIn presence there is | **0** |
| `news` family, same Microsoft account, same call shape | **2** — blogs.microsoft.com, thenextweb.com |

The control is the whole argument. Grounding works; on the same account, in the same shape, a
general search returns cited evidence and the LinkedIn search returns nothing. **Gemini Grounding
with Google Search does not surface linkedin.com for anyone**, which is consistent with LinkedIn's
robots.txt forbidding crawling and the grounding corpus respecting it.

Also worth recording: the model resolves a truncated contact name itself. Given `Mark R` it searched
`"Mark Raby"`. The three stored contacts carry abbreviated surnames, which would have been the
obvious next suspect and is not the cause.

**What changes.** The conclusion — leave it paused — is unchanged, and so is the recommendation of a
SERP API, but the *reason* is now precise and actually strengthens it. "The index is thin" implied a
SERP API would find little either. The truth is the opposite: Google's public index does carry
LinkedIn profiles, and it is the grounding corpus specifically that excludes them. A SERP API reads
the public index, so it is not a long shot — it is the one route that addresses the actual cause.

Corrected in both places the wrong claim was written: `research_source.status_reason` in the
database, and the `LINKEDIN_REASON` constant in migration `e2b9f4c71d38` so a fresh install gets the
right text.

**The lesson is about the probe, not LinkedIn.** Three samples from one population cannot tell
"this population is unusual" from "this mechanism never works". A control outside the population
costs one call and was the difference between a wrong answer and a right one.

## §65 — The query document, tested (2026-10-04)

Asked whether a set of proposed per-signal search strings return anything. Most of them do. The
LinkedIn ones do not, and the split is clean.

**Tested on a real account** (Champion Risk, 41 people) and then — applying §64's lesson — **against
controls that certainly have the content**, so "the query does not work" could be told apart from
"this company has none of that".

| method | account | evidence | domains |
|---|---|---|---|
| careers sub-path | Champion Risk | **3** | championriskcareers.com, davidcareers.com, ziprecruiter.com |
| financial wire | Brown & Brown | **1** | businesswire.com |
| trust centre | Microsoft | **1** | learn.microsoft.com |
| review sites | Salesforce | **3** | g2.com, capterra.com, trustpilot.com |
| trust / wire / reviews | Champion Risk | 0 | — |
| **`site:linkedin.com/...` x-ray** | Champion Risk | **0** | — |

The three zeros on Champion Risk are **accurate findings, not query failures**: a 41-person
brokerage has no SEC filings, no trust centre and no G2 listing. The controls prove the method
works, which is the distinction §64 was written about.

**`championriskcareers.com` is the find worth noting.** A careers site on a *separate domain* —
which `job_boards` cannot reach, because it looks for an ATS on the account's own domain. That is a
direct data point for the route comparison Phase 3 set up: the search route reaches careers content
the crawler route structurally cannot.

LinkedIn is unchanged and now confirmed a third way. The document also recommends Proxycurl
endpoints (`nubela.co/proxycurl`); that company was sued by LinkedIn and shut down, so those calls
have no server to reach.

### Correcting §62 and §64 again: the size evidence was unsound

Both entries say the LinkedIn result "is not a size effect", citing "a 7,700-employee account
returned as little as a 20-person one". **Those employee counts do not exist in the database.** NFP
Property and Casualty and Philadelphia Insurance both have `employee_count = NULL`; the largest
account in the book is 42 people. An earlier probe printed 7700 and 2100 and I repeated the numbers
without checking them against the column.

The *conclusion* is unaffected, because it never rested on size: the Microsoft/Nadella control
versus a working `news` search on the same account is what established that grounding excludes
linkedin.com. But the size sentence should not be read as evidence — it was not measured, and two
log entries carried it as though it had been.

## §66 — Per-signal queries measured, and they lost (2026-10-04)

A curated query per signal type was written and run against the real pipeline, both arms through
the same extractor, on two real accounts. **The per-signal queries cost roughly twice as much and
produced less.**

| | Champion Risk | Piper Jordan |
|---|---|---|
| **Arm A** — families as configured, topic briefs | 7 calls · 4 evidence · 66s | 7 calls · 6 evidence · 69s |
| **Arm B** — one curated query per signal type | 13 calls · 3 evidence · 92s | 13 calls · 2 evidence · 101s |
| Signal candidates, A | `m_and_a_integration` | `leadership_vendor_review`, `mgt_change` |
| Signal candidates, B | **none** | **none** |

Arm B: about double the calls, half to a third of the evidence, 40–50% slower, and **not one signal
candidate across both accounts** against Arm A's three.

**Why, and it is not that the queries are wrong.** The same query shapes were measured earlier and
worked: a wire search found a Brown & Brown acquisition on the first call, a trust-centre search
found Microsoft's certifications, a review search found Salesforce complaints (§65). They work where
the content exists. A 41-person brokerage has never issued a wire release, has no trust centre and
no newsroom — so a query that demands `site:prnewswire.com` finds nothing, while a broad brief
("Launches, partnerships, expansions, incidents") lets the model find whatever *is* there.

**Narrow queries presuppose a footprint these accounts do not have.** That is the finding, and it
inverts the earlier conclusion drawn from controls alone — §65's controls were Brown & Brown,
Microsoft and Salesforce, none of which resembles this book. The same error as §62: measuring on a
population that cannot distinguish the hypotheses.

**A second finding, and possibly the more important one.** Both arms stored **zero** signals, but not
because nothing was found. Arm A produced three candidates and the durability gate dropped every one
as too old — a leadership change beyond its 270-day window, an acquisition beyond its 1000-day
window. The signals are not missing because research is weak. They are missing because **nothing
recent has happened at these companies**, and no query shape fixes that.

**What this does not settle.** One query option per signal was run, usually the first; several
primaries were `fetch` against own-site paths that small brokerages do not have. A fairer Arm B
would try each option until one returns. That is worth doing before the queries are discarded — but
it makes Arm B more expensive still, which is the opposite of the goal.

Scripts kept: `scripts/fill_signal_queries.py` writes the queries into the curation CSV;
`scripts/ab_query_test.py` runs the comparison. Both arms' evidence is stored under its own `run_id`
on the real account — genuine research, kept rather than discarded (invariant 2).

## §67 — Arm B with every option, and X-Ray measured per query (2026-10-04)

§66 ran one option per signal and was unfair to Arm B: a miss blamed the signal for whichever
retrieval path happened to be listed first. Re-run with full fallthrough — every option tried in
turn, stopping at the first that returns — and with the `serp` LinkedIn X-Ray options **included**
rather than skipped, plus the contact rows where `{person}` has a value.

| | calls | evidence | signal candidates | seconds |
|---|---:|---:|---|---:|
| **Arm A** — families as configured | 7 | 7 | none this run | 54 |
| **Arm B** — every option, fallthrough | **38** | 7 | `m_and_a_integration` | **277** |

**Fallthrough works.** Arm B went from 3 evidence and no candidates (§66) to 7 evidence and one
candidate. Five signals that found nothing on their first option found something on a later one —
`m_and_a_integration` on its second (filings, after wires returned nothing).

**It costs 5.4× the calls and 5× the time for the same evidence Arm A got in 7 calls.** Per unit of
evidence, the configured families remain far cheaper.

### LinkedIn X-Ray, measured per query

```
evidence by retrieval route, arm B:
  grounded     6
  fetch        1
  serp         0   <- every LinkedIn X-Ray query
```

Seven X-Ray attempts across five signal types, including `site:linkedin.com/in "{person}"
"{company}"` for a named real person at their real employer. **Zero evidence, seven out of seven**,
one of them erroring outright. This is the fourth independent confirmation and the first at
per-query granularity: it is not an aggregate claim about a corpus, it is seven specific queries
returning nothing.

`contact_profile_headline_change` has **only** X-Ray options, so it found nothing and structurally
cannot — which settles that type.

### The finding that changes something

**Contact research works without LinkedIn.** `contact_content_activity` returned `serp:0` then
`grounded:2` — the "spoken or written elsewhere" query (podcasts, panels, webinars, bylines) found
two passages about a named person that X-Ray could not. Per-person research is not blocked on a SERP
API after all; it is blocked on asking somewhere other than LinkedIn.

### Still zero stored signals

Both arms again stored nothing. Arm B's `m_and_a_integration` candidate was dropped as **beyond its
1000-day durability**. The constraint on this book is unchanged and is not retrieval: the facts that
exist are old.

## §68 — The registry reconfigured from the curation sheet (2026-10-05)

Two migrations, because one half was safe and the other needed the owner's word.

### `a9c3e7f21b64` — labels, four sources, a SERP route, a profile

**Labels and descriptions**, from the curation sheet. The description is what reaches the extraction
prompt, so it is written as an instruction rather than a topic: "The company said, in its own words,
that something is difficult — a manual process, a bottleneck, work that takes days… An inference is
not this."

**Four new sources, each with measured evidence behind it** — `press_wire_aggregators`,
`regulatory_and_filings`, `careers_domain_direct`, `trust_security_portals`. Added *beside* the
broad briefs, not replacing them: §66 and §67 measured that narrow place-shaped queries **lose** on
this book, 5.4× the calls for the same evidence, because a 41-person brokerage has no newsroom to
point a query at. The full twelve-source restructure was not done, and the measurement is the reason.

**`linkedin_serp`, registered and paused.** The route is named so it stops being improvised, and
carries its recency rule: keep only what falls inside the signal type's durability window, because
an indexed post with no recoverable date is background rather than a trigger. Paused for want of a
credential. Fetching linkedin.com directly remains never an option.

**`account.profile`.** Proposed in the sheet as a `firmographic_baseline` signal type; it is account
metadata instead. Nothing about a company's size or description says *now*, and giving it a TTL
would mean expiring a fact that does not expire. The context builder reads it; the signal registry
does not carry it.

### `b4f8d1a27c95` — the keys themselves

The first migration deliberately left keys alone: `signal.signal_type` carries a composite foreign
key to `signal_type(key, scope)`, so renaming a key that has produced signals orphans their
citations. The owner confirmed the nine stored signals were test data and asked for the keys.

Nine renames applied — `partnership` → `strategic_partnership_alliance`, `funding` →
`funding_growth_milestone`, `role_change` → `contact_role_change` and so on. `mgt_change` was
**deleted rather than renamed**: it was doing two jobs at once, which is why three of its five
signals were acquisitions, and the two narrower types that replace it already exist.

**The evidence rows survive — all 80 of them.** Invariant 2 is not suspended by a reset: a passage
that was read is still a passage that was read, it is simply no longer cited. Only the
interpretations went, and interpretations are reproducible — the next extraction run reads the same
evidence against the new registry.

**Everything holding a key was remapped in the same transaction**, or the rename would have left the
ICP pointing at names that no longer exist: `icp_profile_version.definition -> signals_that_matter`
carried twelve keys, now eleven with `mgt_change` dropped and the rest renamed. Verified: zero
dangling references.

19 active types, 17 sources. Backend suite green, `ng build` exit 0, schema dump regenerated.

## §69 — Correcting the LinkedIn date claim, and giving the profile a shape (2026-10-05)

### A post does carry its date, and I said otherwise

§68 registered `linkedin_serp` with the line *"an indexed post with no recoverable date is
background, not a trigger"*, implying a SERP result cannot be aged. Challenged on it, and the
challenge was right:

```
a post (activity id in URL)    -> 2025-07-16
a company page                 -> None
a person profile               -> None
```

A LinkedIn activity id is a 64-bit number whose top 41 bits are milliseconds since the epoch, so a
**post carries its publication date inside its own URL**, exact to the day, with no page fetch.
`services/linkedin.post_date` has decoded it since the module was written — the capability was
already there and the migration I wrote described the system as if it were not.

So the recency rule is **fully enforceable for posts**, which is what was asked for: a SERP API
returns the URL, the URL yields the date, the durability window applies. It is company pages and
personal profiles that carry no date — which is why `contact_profile_headline_change` can be
retrieved but not aged, and why that type was always the weakest of the four. Corrected in the
database and in migration `a9c3e7f21b64`.

### `account.profile` now has a contract

The column landed in §68 with no shape, which made it a place to put anything. `schemas/profile.py`
defines it: what they do, services, **target customers**, industries served, size, locations,
current focus, ownership, founded, sources.

`target_customers` is the one worth naming. It is the field most often missing and most often
needed, because who a company sells *to* is what makes a pitch sound written for them rather than at
them. It is kept distinct from `industries_served`: one is a kind of buyer ("contractors",
"non-profits"), the other a sector.

Every field is optional and `is_empty()` tells "nothing established" from "not looked". A profile
that knows three things says three things — inventing the rest is how a draft ends up describing a
company that does not exist. `sources` alone still counts as empty: knowing where you looked is not
knowing something.

Exposed on `IntelligenceOut.profile`. **Still to do:** nothing fills it yet. The research stage that
writes a profile is not built, so the column is live and empty.

`schemas/profile.py` (new), `api/intelligence.py`, `alembic a9c3e7f21b64`,
`tests/test_prompt_config.py` (+3).

## §70 — The profile stages, and a dead link they exposed (2026-10-05)

Two research stages that write standing descriptions rather than signals:
`stages.company_profile` and `stages.contact_profile`, stored through
`services/profiles.py` onto `account.profile` and the new `contact.profile`
(migration `c8e2a4f71d03`).

**Undated and ungated, both of them.** Everything else research stores is checked against a
durability window. A description of a business has no date to check, and `linkedin.post_date`
returns None for a `/in/` URL — which is the correct answer, not a gap. Applying a window would
discard a standing fact for being old when it is simply still true. The dated events keep their own
types: `contact_role_change` for a person, the signal registry for a company.

**One person per call**, not three together. Company research shares a call across people because
the question is the same; here each answer is a different person's role, and one response covering
three invites the model to blur them — the wrong-person failure arriving by a new route.

**Contact details are stripped on the way in.** The prompt forbids them and the contract has no
field for them, but a model that writes an address into `summary` would have it stored and later
quoted. `_without_contact_details` scrubs anything shaped like an email or a phone number and logs
that it did.

### What it produces

Champion Risk, from its own site in one call:

```
target_customers: Transportation and logistics businesses · Moving and storage
                  companies · Last-mile delivery · Relocation companies · Manufacturers
current_focus:    Captive insurance programs for moving and storage companies
```

Piper Jordan returned `ownership: "Operating Subsidiary of Brown & Brown"` — which explains the
Brown & Brown acquisition that had been sitting in the evidence as an unexplained `mgt_change`.

This is richer than anything signal research has produced for either account, and it is the right
shape for it: these companies have had little happen recently (§66, §67) but they are still
describable.

### The dead link it exposed

The first run stored **two of four sources as unresolved `vertexaisearch` grounding redirects**.
`ground()` replaces a link only where resolution succeeded; for an `EvidenceBatch` the unresolved
ones are dropped with their passage, but for any other contract they were left standing.

A redirect that did not resolve is not an address: it is a temporary link issued by the search API,
it expires, it names no site, and a reader clicking it gets nothing. Four sources of which two are
dead is worse than two, because a rep cannot tell which two.

`replace_links` now **drops an unresolved redirect from a list**, where removing an item is
meaningful, and leaves a lone string field alone, where emptying it would silently discard whatever
the field meant. Re-run: three real URLs on the company's own domain, zero dead links.

`schemas/profile.py`, `services/profiles.py` (new), `services/stages.py`,
`services/instructions.py` (+2 stages), `services/gemini_grounding.py`, `models/account.py`,
`api/intelligence.py`, `core/pipeline.service.ts`, `alembic c8e2a4f71d03`,
`tests/test_gemini_grounding.py` (+4), `tests/test_prompt_config.py` (+3).

**Not done:** nothing calls these stages in the pipeline yet — they are invoked directly — and no
screen displays a profile. Both are small and deliberate next steps.

## §71 — The profile stages wired into the pipeline (2026-10-05)

`run_profile` is injected like the other runners and switchable from the URL:
`POST /lists/{id}/run-research?profiles=false`. Called at two points, with the same runner —
company after the CRM check, people after the contact families.

**Outside the sweep gate, deliberately.** The gate (§59) exists to stop paying *per run* for
accounts with nothing happening. A profile is paid **once per account** and reused on every run
afterwards, so the economics the gate protects against do not apply to it — and a profile is most
valuable on exactly the accounts the gate turns away. An account with no live trigger can still be
written to if we know what it sells and who it sells to, and on this book (§66, §67) that is the
common case rather than the exception. There is a test for this specifically: a gated run still
writes a profile.

**Once per account, once per person.** Skipped where one already exists, so `profiled` comes back
`None` rather than `False` — absent because it was not tried, which reads differently from tried and
found nothing.

**People after the contact families, not before.** Those families can add people the account did not
have, and a profile is worth having for everyone we end up approaching.

**Failures are isolated at both levels.** A broken profiler does not cost the research run, and one
person's failure does not leave the rest of the contacts undescribed — a provider stumbling over one
name is not a reason to skip the other two.

**No `run_id` on the profile runner.** A profile is not evidence and belongs to no run: it is the
current best description, replaced wholesale, with nothing citing the previous one the way a draft
cites a signal.

`services/pipeline.py`, `api/lists.py`, `tests/test_research_pipeline.py` (+8).

## §72 — Pruned what produced nothing, wired what was inert (2026-10-05)

Measured over ten accounts researched the same afternoon, reading `llm_call` and
`research_coverage` together:

| family | calls | evidence | |
|---|---:|---:|---|
| `fast_sweep` | 13 | **25** | best producer |
| `company_site` | 8 | **11** | best value — a fetch, no model call |
| `reviews` | 8 | 4 | |
| `news` | 11 | 3 | |
| `hiring` | 8 | 2 | |
| `funding` | 8 | **1** | technology-track |
| `leadership` | 11 | **1** | |
| `tech_stack` | 8 | **0** | technology-track |
| `type:contact_role_change` | 6 | **0** | |

**Nothing was stuck.** 97 calls, zero failures, zero timeouts, and roughly 0.1s of non-model time
between consecutive calls — the overhead hypothesis was wrong and the ledger said so. The cost is
call *count*, not call *health*: ten model calls per account, run one account at a time by
`sequential-run.ts` and one family at a time by the pipeline.

**The gate has never fired.** Zero families skipped across every run, because the sweep always finds
something. It is still the single best producer at 25 evidence from 13 calls, so it stays — but it
earns its keep as a *source*, not as the saving it was built to be (§59).

### Applied

`tech_stack` and `funding` pruned **from the ICP**, not the registry: sixteen calls between them for
one piece of evidence, and both are technology-track sources being run against insurance
brokerages. They remain available the day a technology ICP exists.

`contact_role_change`'s `search_instruction` removed — six calls, nothing found. An instruction is
the exception that earns an extra search per account, and this one did not.

The four sources registered in `a9c3e7f21b64` were **never running**: no signal type named them in
`produced_by`, so `build_plan` never planned them. Registered and inert, which was my omission.
Wired to the types they serve.

### The arithmetic, which did not come out where predicted

I said "+3 against −3, net zero". It is not:

```
company scope   7 -> 8 search families   (+1)
contact scope   5 -> 4 per person        (-1)
```

The `contact_role_change` saving lands on the *contact* pass, not the company one, so the company
cost rose by one. Flat overall on an account with contacts, one call worse on an account without.

That is the honest number. The justification is aim rather than volume: two sources returning one
piece of evidence in sixteen calls are replaced by three aimed at places that returned evidence
under test (§65). The next run is what says whether the aim was better — and if
`press_wire_aggregators` and `regulatory_and_filings` come back empty on this book the way the
narrow queries did in §66, they should go the same way as `tech_stack`.

`alembic d1a7e9c45b82`, `docs/schema/full-schema.sql`.

## §73 — `strategy_synthesis` max_tokens set below what a working call needs (2026-10-05)

Reported from the screen: *"Gemini hit maxOutputTokens before finishing… retried at low thinking
after the first ran out of room"*. The stage was failing 43% of the time (17 of 39 calls).

The config history says it plainly:

```
v8   effort=medium  max_tokens=8000     <- the value §52 measured as working
v9   effort=medium  max_tokens=2000     <- live, and failing
```

And what a *successful* call actually uses: **avg 684, p95 1316, max 3160** output tokens.

**The ceiling was below the observed maximum of a succeeding call**, before counting thinking —
which on Gemini is charged against the same budget. So a call that thought normally and produced a
normal-length answer had nowhere to put it, and the quieter retry had no more room than the first
attempt.

§52 found that *lowering* `max_tokens` from 24,000 to 8,000 fixed this stage, because a tight
ceiling makes a runaway fail early enough for the quieter retry to land. v9 took that one step
further and crossed from "tight enough to catch runaways" into "too tight for legitimate work" —
the same lever, past its useful range.

Restored to 8,000 as **v10** through the versioned config rather than an UPDATE, so v9 stays in the
history as the thing that was tried. That leaves 4,840 tokens of headroom above the largest
successful answer, and is still three times tighter than the 24,000 that caused the original
problem.

**The error message steered toward the wrong lever here.** "Lower this stage's effort before raising
max_tokens" is sound general advice — thinking does eat the budget — but in this case effort was
already `medium` and the budget was simply below what the work needs. A message that named the
observed output distribution ("successful calls here have used up to N tokens; the ceiling is M")
would have pointed straight at it. Worth doing if this recurs.

Nothing in code changed; this is configuration, recorded because the next person to see a
`maxOutputTokens` error should check the ceiling against the ledger before lowering effort.

## §74 — Strategy was arguing from a name and a postcode (2026-10-05)

Reported as "something wrong on strategy building", with the observation that **Maria ran fine and
Mark did not**. That difference is the whole diagnosis: Maria's thread cites a live signal, Mark's
is a "pursue anyway" thread with none.

Over 44 calls:

```
success: 26 calls, avg  8.8s
failure: 18 calls, avg 35.6s     <- four times longer
```

A failure here is not a quick rejection. It is the model deliberating itself into exhausting its
token budget looking for a trigger that does not exist — one call ran **53 seconds** before failing.

### What it was actually given

The prompt tells the model, for a thread with no live trigger, to *"make the case from the company's
situation and the person's role"*. The payload held:

```
account:  account_id · name · domain · industry · employee_count · hq_country · hq_region · linkedin_url
contact:  full_name · title · seniority · buying_role
```

There was no situation in it. Meanwhile **the material existed and was already stored** —
`account.profile` for ten accounts and `contact.profile` for all three contacts, built by the stages
added in §70. Strategy could see neither. Mark's profile holds his focus areas ("Insurance agency
M&A deals", "Captives and alternative risk structures") and his decision scope; strategy was handed
"Mark R · Chief Executive Officer" and asked to construct an argument.

### Fixed in three places, none sufficient alone

* `_account_facts` carries `account.profile`;
* a new `_contact_facts` carries `contact.profile` — the four columns were all a thread ever got;
* the prompt says the material is all there is, and says plainly **not to deliberate at length over
  a thread with no trigger**: there is no hidden trigger to recover and a long search returns the
  same answer as a short one. It also gives the model somewhere to go when both profiles are empty —
  say so in one sentence, mark the thread low confidence — where previously no acceptable answer
  existed except an invented one.

`sources` is dropped from both profiles on the way into the prompt: URLs are for a rep checking a
claim, nothing downstream reasons with them, and they are the longest field.

Prompt written as `prompt_template` v3 from the code (migration `e5c9b3a71f48`), skipped if the live
body is past v2 because an admin edited that deliberately.

### Related: `linkedin_serp` brings none of this

Asked whether the SERP route supplies the profile summary. It does not and cannot yet: **no client
code exists, no credential is configured, and the source is paused.** §68 registered a named route,
not a working one. Mark's profile came from ordinary grounded search against the company's own
website — which is worth noting on its own, because it is the material LinkedIn was wanted for,
obtained without it.

`services/stages.py`, `services/instructions.py`, `alembic e5c9b3a71f48`,
`tests/test_llm_call_sites.py` (+4).

## §75 — An undescribed schema field swallowed the whole answer (2026-10-05)

§74 gave strategy the material it was missing and the failures continued: *"still same issue. wasted
50 seconds and nothing"*. The instinct that followed was right and is the reason this was found —
**"I don't see the LLM taking more than 3 seconds to build strategy if all context is ready."** A
successful call now runs 2.3s. So 50 seconds was never deliberation over thin context; something
else was consuming the budget.

### Three wrong hypotheses, in order

1. **`max_tokens` too low.** Partly true and fixed as §73, but raising v9's 2,000 to 8,000 did not
   stop the failures.
2. **A thinking spiral.** Plausible after §74, and wrong: the failing calls reported
   `thoughtsTokenCount: 0`. Nothing was being deliberated at all. Finding that out needed the
   MAX_TOKENS error in `gemini.py` to report the thinking/answer split rather than just the ceiling
   it hit — that one logging change was the decisive diagnostic and is worth keeping.
3. **A malformed context package.** Checked directly against the live payload. It was clean.

### What it was

`account_angle` on `StrategyProposal` is a free string, and **the prompt never mentioned it**. The
model found an unnamed, unbounded field in the schema and wrote its entire answer into it — **7,986
output tokens** of prose — while leaving `threads` empty. One attempt was also refused with
`RECITATION`: it had started reciting its own input back.

`threads` being empty was *permitted*, because it was declared
`Field(default_factory=list)`. A proposal with no threads satisfied the contract, parsed cleanly,
and surfaced to the rep as "the model returned nothing for them" — which reads as a judgement about
the person rather than a malformed answer.

### Fixed in three places

* **The schema floors it.** `threads: list[ProposedThread] = Field(min_length=1)`. `min_length`
  reaches Gemini as `minItems`, which that API **accepts** — unlike `maxItems` and `maxLength`,
  which answer HTTP 400 (measured, §-noted on the field itself). The floor is what makes the empty
  answer unrepresentable rather than merely discouraged.
* **The prompt describes the field.** `account_angle` is **one sentence**. Its length cannot be
  enforced in the schema for the reason above, so the rule lives in the prompt — and the field now
  exists in the prompt at all, which is the actual fix.
* **A count, not an invitation.** `thread_count` goes into the payload and the prompt asks for
  *exactly* that many threads.

### The retry had to move with it

`campaign_strategy` retried on "no threads came back". The schema now makes that unreachable, and
two tests constructing `StrategyProposal(threads=[])` failed — correctly. The retry retargeted to
the failure that remains representable: `answers_nobody()`, a proposal whose every thread names a
`contact_id` nobody asked about. It satisfies the schema, is discarded, and would otherwise leave
the rep with the same misleading "nothing for them". Both tests renamed to say what they now cover,
with a `_about_a_stranger()` fixture in place of the empty list.

New logging: `campaign_strategy.proposal` (asked / returned / ids) and
`campaign_strategy.unknown_contact`.

### Verified

```
INFO: llm.call scenario=strategy_synthesis effort=medium in=2849 out=440
INFO: campaign_strategy.proposal ... asked=1 returned=1 ids=['298d5805-…']
AT MEDIUM -> built: True | pursued: ['Mark R'] | excluded: 0
```

Green at low and medium effort; config left as the original `effort=medium, max_tokens=8000` (v12).
Backend 1,765 pass, front end 348 pass, `ng build` exit 0.

`schemas/strategy.py`, `services/campaign_strategy.py`, `services/gemini.py`,
`services/instructions.py`, `services/stages.py`, `tests/test_campaign_strategy.py`.

## §76 — The eight barren types reviewed, and what the review found (2026-10-05)

§60 deferred deprecating eight signal types until a measured run existed. Asked to show them before
anything was deleted — which was the right order, because showing them changed the answer for half.

### The eight are still exactly eight, but not for one reason

19 active types, **4 had ever produced a signal**, 6 signals in total, from 10 of 57 accounts.
Grouping by the date each type was added separates two different things:

```
Sept 5-15 (original registry)   12 types   6 signals   -> 4 productive, 8 barren
2026-10-04 (Phase 2, §60)        7 types   0 signals   -> never had a run
```

The seven Enterprise IT types read as unproductive on a naive count and are nothing of the kind;
they are a day old. The eight are the September set.

They split again on **why**:

* **Four company-scoped types had documents and produced nothing.** 17 `jobs`, 19 `news` and 90
  `web` evidence rows exist, so these were read against real material.
* **Four contact-scoped types were never tested. There are three contacts in the database.** Every
  signal ever produced is company-scoped. That is a fact about the size of the book, not about four
  type definitions, and deprecating them would have recorded the wrong conclusion permanently.

One of the four is worse than untested: **`contact_content_activity` has an empty `produced_by`**.
No source opens research for it, so it cannot fire at all. A type that cannot fire counts as zero
whatever its definition says.

### Decisions taken

| type | decision |
|---|---|
| `delivery_quality_theme` | deleted |
| `company_pain_statement` | deleted |
| `product_feature_launch` | kept, relabelled **"Product launch"**, redescribed, key renamed to `product_launch` |
| `engineering_team_expansion` | stays |

Both deletions went through `DELETE /api/config/signal-types/{key}`, not SQL, so the zero-signal
guard is what authorised them rather than my reading of the count. 17 types remain; all 6 signals
intact.

**`product_feature_launch` was mis-defined, not unproductive.** "A product or feature launch" reads
as software and so only ever fitted an ISV or SaaS account; the book is 57 insurance brokerages. The
description is what extraction reads to choose between types, so a brokerage launching a scheme or a
service line had nowhere to put it. Now described against whatever the company actually sells, with
a software feature named as one instance and explicitly not the definition.

**The key followed, to `product_launch`** (`f7b3d9e24a16`). `SignalTypePatch` omits `key` on purpose
— it is written into the extraction output schema — so the API cannot do this and a migration must.
Safe to rename rather than recreate: `signal.signal_type` carries a composite FK to
`signal_type(key, scope)` and this type has produced no signals, so nothing pointed at the old
name and nothing had to be deleted. All eight `icp_profile_version` rows were remapped in the same
transaction, historical ones included, following `b4f8d1a27c95` — a rename is the same concept under
a new name, so a version that recorded "this type mattered" still records that. Round-tripped down
and back up: the downgrade restores the old name in all eight, the upgrade puts it back.

`product_launch` was the curated spreadsheet's own name all along. The rename to
`product_feature_launch` in `b4f8d1a27c95` is where the software reading entered.

### Two things the deletion dragged behind it

* **The active ICP still named both deleted types** in `signals_that_matter`. Harmless at runtime —
  both consumers use the list as a filter (`SignalType.key.in_(wanted)`), so a dangling name matches
  nothing — but wrong on the screen a rep reads. Cleaned as Default **v10** through
  `PUT /icp-profiles/{id}`, which activates a new version rather than editing v9, so runs that
  recorded v9 stay explainable.
* **Two one-off scripts would have put the types straight back.** Neither type was created by a
  migration; both came from setup scripts that insert by key and are documented as idempotent. A
  script that silently undoes a deliberate deletion is worse than no script, so both are deleted:
  `add_company_pain_type.py`, whose entire purpose was one of them, and `enable_more_families.py`,
  which by the end of the day had nothing left that was still true — `delivery_quality_theme` and
  `public_focus` deleted, `partnership` and `tech_adoption` renamed by `b4f8d1a27c95`, and
  `product_launch` redescribed. Recoverable:
  `git show b0aeaaf:SalesDemandGen360/backend/scripts/<name>`.

### Then, in the same review

* **`product_feature_launch` → `product_launch`** (`f7b3d9e24a16`), above.
* **`contact_profile_headline_change` → `contact_profile`** (`a2e8c5b74f91`). "A headline change" is
  one observation about a profile; what the type is wanted for is keeping the stored contact profile
  current from the public index, so the key says that. It pairs with the `contact_profile()` stage
  from §70 — the stage fills the profile, this type is what notices the profile has moved on.
* **`public_focus` deleted with its two signals** (`a2e8c5b74f91`). It had produced signals, so the
  API answers 409 and is right to; the owner confirmed test data and asked for the type and the data
  to go. **The two evidence rows survive** — invariant 2 is not suspended by a reset, exactly as
  `b4f8d1a27c95` reasoned. Verified: 134 evidence rows before and after.
* **The three remaining contact types wired to `linkedin_serp`**, which is contact-scoped and which
  `sources.validate` accepts — it refuses unknown, wrong-scope, duplicate and support-only-and-alone
  lists, but **not a paused source**. So all three are configured and none can fire until a SERP
  credential exists. `contact_role_change` asked for "the company website" and cannot name
  `company_site`, which is company-scope only; `leadership` ("exec appointments and departures,
  team-page changes") is that route for a contact.
* **`contact_content_activity`'s two import defects fixed**: `produced_by` was `{}`, so no source
  opened research and it could never fire, and `search_group` held the spreadsheet note
  `"together or alone"`.

`alembic f7b3d9e24a16`, `alembic a2e8c5b74f91`, `scripts/export_signal_registry.py`,
`scripts/fill_signal_queries.py`, `docs/15-signal-registry.md`, ICP Default v10,
`signal_type` (3 rows deleted, 2 renamed, 4 retuned), `signal` (2 test rows deleted).

## §77 — Source reachability audited; the LinkedIn queries moved to X-Ray (2026-10-05)

"First we need to check all sources are reachable." Reachable turned out to be **four** questions,
and a source can pass three and still never produce anything. `build_plan` applies them in this
order:

1. **Active?** Paused or deprecated is skipped outright.
2. **In the ICP's `sources` list?** That list **takes precedence over what the signal types claim.**
   A source three types name but the ICP omits never runs; a source the ICP names but nobody claims
   runs anyway, as an `extra`. This is the gate nobody was checking.
3. **A `search` or `fetch` kind?** `provider` and `manual` are excluded by design — fanning research
   over a provider would spend Apollo credits like tokens.
4. **Scope.**

Written up as `scripts/audit_sources.py`, read-only, no network and no credits: every answer is
already in the database. What it found on 17 sources:

```
producing   company_site 25 · leadership 10 · news 9 · content_activity 7 · reviews 6
            hiring 4 · funding 4 · tech_stack 4
dead weight job_board — 26 attempts, nothing
untried     careers_domain_direct · press_wire_aggregators · regulatory_and_filings
            trust_security_portals  (wired yesterday in d1a7e9c45b82; no run since)
never runs  funding · tech_stack — not in the ICP · linkedin — deprecated
```

### Three things the audit found that nobody had looked for

* **`linkedin_serp` could never have run.** Earlier today its three contact types were pointed at it;
  it was active and claimed by all three, and **absent from the ICP's source list**, so the wiring
  was inert. My own change, and the ICP gate is why checking beat asserting.
* **Two of the three types that have ever produced a signal are structurally dead.**
  `funding_growth_milestone` and `tech_stack_expansion` have exactly one source each — `funding` and
  `tech_stack` — and both were pruned from the ICP in `d1a7e9c45b82`. That prune was sound on cost
  (sixteen calls for one passage, technology sources against a brokerage book) but it silently
  removed the only route two producing types had. **Left as it is, pending a decision** — reinstating
  them would undo a measured call.
* **`linkedin_serp` was resumed outside this session at 09:39** and kept the `status_reason` it was
  paused with, "No SERP API credential is configured", so the registry showed a running source
  carrying a live-looking warning.

### And underneath that, a 500 on every real edit

`PATCH /research-sources/{key}` built its response as
`{c.name: getattr(row, c.name) for c in row.__table__.columns}` **after** `commit()`. `updated_at` is
mapped `onupdate=func.now()` — a SQL expression, so a flush expires the attribute and the next read
of it is IO, inside a synchronous comprehension. `MissingGreenlet`, a 500, **and the commit had
already happened**: the write landed and the caller was told it failed. A patch that changes nothing
flushes nothing and looks fine, which is how it survived. That is exactly the shape of what happened
at 09:39 — database correct, screen wrong.

Fixed with `await session.refresh(row)` before the columns are read, and the endpoint now clears
`status_reason` when a source goes back to active, because that field answers "why is this not
active?" and has to go when the answer stops existing. Three tests added, one of them on a patch
that genuinely changes a value — the no-op case is what hid this.

### The LinkedIn queries (`b6d4a8f32e07`)

`linkedin` is **deprecated, not paused**: paused reads as "we may turn this back on", and §64 settled
that there is nothing to turn back on — grounding excludes `linkedin.com` for everyone, confirmed
four ways, 16 attempts and no evidence. Removed from every ICP's sources and from every type's
`produced_by`, so nothing claims a route that cannot run.

The queries move to the path operators rather than the bare domain:

```
site:linkedin.com/in      a person's public profile
site:linkedin.com/posts   a dated post
```

Narrower than `site:linkedin.com`, which also matches jobs, learning, pulse and company pages and
buries the two things worth having. Written into the `linkedin_serp` description and into
`contact_content_activity`'s instruction, so the form lives in the registry rather than in somebody's
memory.

**Stated plainly because it is easy to miss: this still retrieves nothing today.** X-Ray is a query
*form*, not a retrieval route — the exclusion is on the domain, not the phrasing, so through
grounding these return what every other LinkedIn query returns. They need a SERP API, and **no SERP
credential is configured** (`integration_credential` holds anthropic, apollo, gemini, lgm). What the
migration buys is that the day a credential exists, the queries are already right. Nothing here
opens `linkedin.com`.

`scripts/audit_sources.py` (new), `api/config.py`, `alembic b6d4a8f32e07`,
`tests/test_research_config.py` (+3).

## §78 — Sources become places, and are trialled before they are stored (2026-10-05)

"Some of the sources are not source where we get signal/evidence. They are more of signal type mixed
with sources." Correct, and it was the registry contradicting the invariant it exists to serve —
*a source says what research opens; signal types say what is read out of it*. Seven of seventeen rows
were named for what you hoped to find: `funding`, `hiring`, `leadership`, `tech_stack`,
`content_activity`, `news`, `reviews`. A type naming `hiring` said the same thing twice and neither
half said where to go. Open decision #4 in docs/15, now closed.

### Two designs, and why the measurement chose

* **A** — a registry of places, each with a tested query; types stay interpretation.
* **B** — no registry; each type owns its queries, grouped by common source into one call.

B is the better authoring story and **it is the shape already measured as worse**: Arm A (broad
topic briefs) beat Arm B (narrow per-signal queries) **7 calls to 38 for the same evidence** (§66),
and the best producer on the book is the fast sweep — one broad call. B recovers that only by
grouping queries back into broad calls, which is A with the registry hidden inside a string-matching
step. A also keeps "every document is read against every active type" structural rather than a rule
to remember. **A, with B's authoring flow**: a type is authored with a "where is this found?" step
that picks or creates a locus, and the locus owns the query.

### Try it before you store it (`services/source_trial.py`)

The reason a bad source is expensive is that it costs a read per account from the moment it is saved
and is only judged afterwards. `job_board` took **26 attempts across 57 accounts** to establish that
it finds nothing.

`POST /api/config/research-sources/try` takes a candidate — the same fields that would be stored —
runs it against up to six real accounts, and shows what came back and what it cost. It stores
nothing: no evidence, no coverage, no signals.

**The trial is the real path or it is worthless.** A search goes through `stages.research_family`
with a new `candidate` override, so it is the same prompt, model, effort and contract as a stored
source; the only differences are where the definition comes from and that `store_found` is never
reached. A fetch goes through `sweep_account`, already read-only. `provider` and `manual` are
**refused by name** rather than trialled — "no evidence" and "no implementation" look identical in a
result and mean opposite things, which is exactly how `linkedin_serp` sat configured for a day with
no credential and nothing saying so.

It earned its cost on first use. Four candidate loci against three accounts, 12 calls:

```
trade_press                     2 passages   STORE
company_data_providers          2 passages   STORE
conference_and_podcast_circuit  2 passages   STORE
review_sites                    0 of 3       NOT STORED
```

`review_sites` was never written. `reviews`, the row it would have replaced, is retired.

### What the trial found that matters more than the renaming

**Every passage came from the one insurtech in the sample.** Both brokerages returned nothing from
any locus. The stored record agrees: **47 of 57 accounts have never produced a passage**, and the two
largest (41 and 42 people) hold **69% of all evidence**.

So these places are where a *technology* company appears. They open the technology track; they do
not improve brokerage coverage, and nothing will — a twenty-person brokerage has no public footprint
beyond its own website. That is why `company_site` is the only reliable producer at 25, and it is a
fact about the book rather than about the registry.

### The registry after `c1f7e3b89d24`

Seven loci and two routes, from seventeen rows:

```
company_site                    fetch   8 types   producing 25
trade_press                     search 10 types   trialled
company_data_providers          search  4 types   trialled
conference_and_podcast_circuit  search  2 types   trialled
regulators_and_registers        search  2 types   trialled 0/2
linkedin_index                  search  3 types   no SERP credential
ats_boards                      fetch   3 types   PAUSED - 26 attempts, nothing
enrichment / manual             routes
```

`trust_security_portals` folded into `company_site` because it always was part of it —
`site_sweep.PAGE_PATHS` already reads `/security`, `/trust` and `/compliance`. It was a second row
for pages one fetch already opened.

**A dead end closed by accident, worth noting.** §77 flagged that `funding_growth_milestone` and
`tech_stack_expansion` — two of the three types that have ever produced a signal — had exactly one
source each, both pruned from the ICP. Both collapsed onto `company_data_providers`, which is active
and in the ICP, so both are reachable again without reinstating anything. `engineering_team_expansion`
was left naming only the paused `ats_boards` and was given `trade_press` and
`company_data_providers`, so every type now reaches at least one live source.

### The seed and the table had to be corrected together

`query_families.QUERY_FAMILIES` is the registry seen from the other side — what a fresh install gets
and what `tests/conftest.py` restores after a truncate. It still held the old topic-shaped keys, and
**the suite passed anyway**, because the tests were internally consistent with a registry production
no longer had. That is the drift the module's own comment warns about. Rewritten to the same seven
loci, which broke 20 tests that encoded the old catalogue; all updated, none bent.

One of those was a real consequence rather than a stale fixture: **`reviews` was the only
`support_only` source**, so retiring it left the concept with no instance. The rule is still enforced
by `sources.validate`, so the tests now build a corroborating source rather than borrowing a shipped
one — a better test, and it outlives the next retirement.

**Old keys were deleted with their coverage rows**, per the standing instruction to purge conflicting
transaction data rather than reconcile it. The measured record was written to
`docs/source-health-2026-10-05.csv` first — `scripts/audit_sources.py --csv` — which is the baseline
the restructure gets judged against.

Backend 1,776 pass; front end 348 pass; `ng build` exit 0.

`services/source_trial.py` (new), `scripts/trial_loci.py` (new), `scripts/audit_sources.py`,
`services/query_families.py`, `services/stages.py`, `api/config.py`, `schemas/config.py`,
`alembic c1f7e3b89d24`, and five test modules.

## §79 — The Try panel: the logic shown, the inputs named, the A/B in one call (2026-10-05)

§78 built the trial engine and left no way to drive it — `trial_loci.py` had its candidates
hardcoded in Python and the endpoint had no UI. Three gaps, all fair:

### 1. The search logic was not exposed

Only the *brief* was editable. The thing it feeds — the `company_research` template plus the
rendered payload — was invisible, so a brief could only be tuned blind.

`stages.research_request` is now split out of `research_family`, and `research_family` calls it.
**That is the point of the split:** the Try panel shows what comes back from the same function the
real call uses, so what is displayed cannot drift from what runs. A reconstruction would drift, and
somebody tuning against a stale copy of the prompt is worse off than somebody tuning blind.

The panel prints the instructions (5,030 characters) and the payload verbatim, to be copied into any
model and argued with, and says where each part is editable: the instructions under Settings →
Prompts, the brief as the `source.read_for` line.

Capturing it is wrapped in `try/except`. It is a display aid and the findings are the answer — a
failure there must not cost somebody the results they just paid for.

### 2. Nothing said what inputs a source needs

"Found nothing" and "we had nothing to search with" looked identical. An account with no stored
website returns nothing for every source, and reading that as a verdict on the wording sends somebody
to rewrite a brief that was never the problem.

`ACCOUNT_INPUTS` names the five fields in plain words, and each account's empty ones are reported:
*"this account has no website — a source needing one of those would find nothing here whatever the
brief says."* The verdict changes with it: when the whole sample is starved it says **"this may not be
the wording"** instead of "do not store this".

### 3. No way to A/B

`description_b` runs a second wording **against the same accounts in the same call**. That is what
makes it a comparison: the prompt, the model, the account and the day are held still and one field
moves. Two runs minutes apart are not — §74 saw the same request return a sound answer on 411 output
tokens and nothing usable on 790, minutes apart.

The account ceiling halves when a B is given, because the cap is on calls rather than rows.

Verified live against Agentero, one account, both wordings:

```
A and B both found 2 across 1 accounts - nothing to choose between them on this sample
  A  found=2  Rainbow Announces Partnership With Agentero / ...compliance with Producerflow
  B  found=2  Agentero launches Producerflow... / How Agentero is revolutionising...
```

Equal counts, different articles — which is the honest reading the verdict gives rather than
declaring a winner from one account.

### Two fixture faults found by its own tests, worth recording

* `_Account` in `tests/test_source_trial.py` had only a name and a domain, so the new missing-inputs
  branch fired on every test and changed every verdict. The stub is now fully populated and the
  starved case has a test of its own. The failure was correct and the fixture was wrong.
* The front-end spec set the draft fields but never opened the Add-source form, so the panel was not
  in the DOM at all. Fixture again, not a defect.

Backend 1,782 pass; front end 351 pass; `ng build` exit 0.

`services/stages.py`, `services/source_trial.py`, `api/config.py`, `schemas/config.py`,
`core/config.service.ts`, `settings/research.component.ts`, two spec modules.

## §80 — Step 4: eight of fifteen signal types could not fire (2026-10-05)

Step 4 was meant to be tidying overlaps. The first query made it something else.

### The gate

`ListPlan.type_keys` returns the active ICP's `signals_that_matter`, and its own docstring says what
that is for: **"Every signal type the ICPs care about — what extraction may return."** `pipeline`
passes it as `signal_type_keys` and extraction is restricted to it. So a type absent from that list
**cannot produce a signal**, however well configured, whatever sources it claims, however much
evidence exists.

The list named eight types. One of them, `public_pain_statement`, **no longer exists**. The registry
held fifteen. So:

```
eligible          7   funding_growth_milestone, engineering_team_expansion, contact_role_change,
                      product_launch, strategic_partnership_alliance, tech_stack_expansion,
                      contact_profile
INERT             8   compliance_security_deadline, digital_transformation_mandate,
                      hiring_bottleneck, leadership_change_executive, m_and_a_integration,
                      tech_debt_modernization, vendor_consolidation, contact_content_activity
dangling          1   public_pain_statement
```

**All seven Enterprise IT types from `d7a4e1c93b26` are in the inert list.** They were added in §60
specifically because the book is insurance brokerages and the shipped registry was built for
technology companies. They have been unable to produce a signal since the day they were created.

§76 recorded them as "never had a run" and treated the zero as youth. That was the charitable reading
and it was wrong about the mechanism: they could not have produced a signal if every run in the book
had gone perfectly.

**The gate itself is not the bug.** It is deliberate and already covered by
`test_only_the_icps_signal_types_may_be_extracted` — research should not extract a type nobody looked
for. The bug is that nothing said the list had fallen behind the registry. The only visible symptom
was a zero in the Signals column, which looks exactly like a type that is simply not firing.

Fixed in three places, because data alone would rot again:

* the active ICP names all fifteen (v11, through `PUT` so the version chain stays intact; the
  dangling key dropped);
* `SignalTypeOut.extractable` carries the answer, computed from the active ICPs;
* the Signal types screen shows a **not extractable** badge beside the status, so the next gap
  announces itself instead of looking like a quiet type.

`None` is kept distinct from the empty set throughout: an ICP that has accepted no signal list does
not narrow extraction at all, so reporting every type as unreachable there would be the opposite of
the truth.

### Then the overlaps, which were the actual task

A description is not documentation — it is what extraction reads to decide which type a passage
belongs to. Two pairs were colliding on the same sentence, which makes the choice between them a coin
toss:

* **`engineering_team_expansion` and `hiring_bottleneck` both offered "several related roles open at
  once".** They are opposite readings of one careers page: roles opening because the company is
  growing, against roles that will not fill.
* **`tech_debt_modernization` and `digital_transformation_mandate` both offered "move to cloud".**

Resolved by giving each an anchor and **naming its sibling**, rather than by deleting words — the
phrase still appears in both, but now only alongside the discriminator:

| pair | the discriminator |
|---|---|
| expansion / bottleneck | duration and repetition. Several roles at once is expansion; re-posted or long-open is the bottleneck |
| debt / mandate | debt is anchored on the **old system being named**, mandate on the **programme being declared**. Tie-break stated: prefer the system, because a system is a fact and a programme is a plan |
| partnership / launch | a **second named party** |
| stack expansion | adoption only; migration is debt, supplier reduction is consolidation |
| leadership change / contact role change | overlaps **on purpose**; this was true before and written nowhere. Seat changed vs person we track, and both firing on one passage is acceptable |

A description that says only what a type *is* leaves the extractor to infer the boundary. Naming the
neighbour makes the boundary the thing it reads.

Carried as `d8b3f1c62a95`, generated from the live rows so the file and the database cannot disagree,
with no downgrade: restoring the colliding wording would reinstate the coin toss.

Backend 1,789 pass; front end 351 pass; `ng build` exit 0.

`api/config.py`, `schemas/config.py`, `alembic d8b3f1c62a95`, ICP Default v11,
`settings/signal-types.component.ts`, `core/config.service.ts`, `tests/test_research_config.py` (+2).

## §81 — Sources derived from signals; the pickers tell the truth (2026-10-05)

Four things, from one observation: *"since sources are linked to signal, why give option to choose
sources."*

### The ICP no longer picks sources

An ICP carried two lists that could disagree about the same thing — `signals_that_matter` and
`sources` — while every signal type already names where its fact lives in `produced_by`. The second
was a parallel answer to a settled question, and `build_plan` let it win. Both directions failed
inside one week:

* `linkedin_serp`, claimed by all three contact types, **never ran** — the ICP omitted it (§77);
* `reviews` **ran anyway** with no type claiming it, after the one that did was deleted;
* and the sibling list had fallen eight types behind the registry (§80).

Sources are now the union of `produced_by` across the types the ICP names, filtered as before by
status, kind and scope. One list, one gate, and both failures become unrepresentable rather than
fixed. `sources_excluded` keeps the only thing the old list was good for — `d1a7e9c45b82` dropped
`funding` and `tech_stack` for a book of brokerages, sixteen calls for one passage, while keeping the
types so they return for a technology ICP. A subtraction cannot describe a different world.

**Nothing moved when it was applied**, which is what made it safe in one step: the ICP listed seven
sources and the derived set is those seven plus `ats_boards` and `manual`, both dropped downstream
anyway — one paused, one a kind the planner never schedules. `sources_excluded` starts empty.

`IcpDefinitionIn` now **refuses** a `sources` key rather than ignoring it. A definition still
carrying it would look honoured, and the screen would agree.

The editor's `driftedSources`/`addDrifted` are gone with it. They existed to reconcile the two lists
— a patch over the flaw, not a fix for it.

### The track stays, and goes horizontal

Asked whether it is needed, since the signals are chosen explicitly. It is: the track is not a signal
selector but the one factor the strategy and drafting prompts **branch on**. `enterprise` argues risk
and continuity to a buyer measured on nothing going wrong, where "velocity language reads as naive";
`tech_company` argues bandwidth and time to market. The same signal is argued differently to each —
an acquisition is integration risk to a CIO and roadmap contention to a CTO. Dropping it would flatten
every draft to "write plainly and let the evidence carry it".

Two mutually exclusive options now sit side by side rather than stacked: a column reads as a list to
work through, a row as the choice it is.

### The source picker was hiding one, and then explaining nothing

Two faults on the Signal types screen:

* It filtered `status === 'active'` **on top of** the endpoint's own exclusion of deprecated rows, so
  **paused sources were invisible**. `ats_boards` is paused and three types claim it — the chip showed
  on the row with no checkbox to untick. Paused rows are now listed and marked.
* Eight of nine appeared for a company signal with nothing saying why. The ninth is `enrichment`,
  which looks up people. The picker now states the count and names what the other scope takes.

### A suggestion is a proposal, not a filter

`Suggest sources` ticked boxes and said nothing about which were its idea. Suggested sources are now
marked (dashed edge, "suggested") while **every** source stays listed and tickable. Showing only the
suggestions would hide the source a rep knows is right; ticking without marking leaves them unable to
tell their own choices from the model's, or to judge how good its last answer was. Cleared on reset,
so a mark never claims the model proposed something for a type it never saw.

**A backtick inside the Angular template literal again** — an HTML comment quoting a function name,
the third time this session. It terminates the template string and produces `TS-991002` plus a
cascade of nonsense errors pointing nowhere near the real line.

Backend 1,789 pass; front end 351 pass; `ng build` exit 0.

`services/research.py`, `schemas/config.py`, `alembic e4a9c7d13b60`,
`settings/icp-editor.component.ts`, `settings/signal-types.component.ts`, two spec modules.

## §82 — The careers page was already being walked past (2026-10-05)

Asked whether news was wired properly, whether a waterfall was possible, and whether to try RSS
first — then handed a document of suggestions for reaching companies in the $10M–$50M band.

**Two of the three efficiency suggestions were already built.** RSS-first is `company_site`, which
tries ten feed paths before any HTML. The waterfall is `run_sweep`: one broad sweep gates the
account, and if it finds nothing every planned family is skipped with a coverage row saying why.
Worth stating rather than re-implementing.

### What was actually missing

`ats_boards` is paused at **26 attempts across 57 accounts and no evidence** — a twenty-person
broker runs no Greenhouse board. But it has a `/careers` page, and `company_site` — a `fetch`,
costing no model call, and the only source on this book that reliably produces anything — was
reading `/news` and `/security` and **walking straight past it**.

So the cheapest answer to "who are they hiring, and what platform are they hiring around" was
already running and was not being asked. Confirmed live on the first brokerage tried: Beach &
O'Neill returns `news, careers, newsroom, jobs`.

`PAGE_PATHS` now **interleaves** kinds rather than grouping them. The loop stops at `MAX_PAGES`, so
grouping meant a site with four news pages never reached the second kind at all — which is how
`/security` was being starved before anybody noticed.

`/security`, `/trust` and `/compliance` are **dropped** at the owner's instruction.
`compliance_security_deadline` produced nothing on this book and each miss cost an eight-second
timeout on every account without such a page. It keeps `trade_press`, `regulators_and_registers`
and its own search instruction, so it is narrowed rather than orphaned.

`engineering_team_expansion` gains `company_site`. It named `ats_boards`, `trade_press` and
`company_data_providers` — a paused source and two that ignore companies this size — so on this book
it had no live route to the one page that lists its evidence.

### Local business journals: tested, rejected

The document proposed widening `trade_press` to regional press for companies national wires ignore.
A/B'd through the Try panel against three accounts, same day, one field moved:

```
A (national wires)  3 passages — all PR Newswire
B (+ local press)   2 passages — a regional paper reprint and a trade blog
```

Both brokerages returned nothing either way. B traded a wire citation for a reprint of the same
story. **Not applied** — and this is the second time the harness has paid for itself by refusing
something plausible.

### Aggregated LinkedIn tenure shifts: not obtainable this way

Asked whether Google X-Ray could give department-level hiring velocity. It cannot, and the reason is
structural: a `/in` profile **carries no date in the index**. Only `/posts` yields one, from the
activity id's top 41 bits. X-Ray can establish that a Senior Engineer exists at a company; it cannot
establish that they arrived in March, and the arrival is the entire signal.

**The signal is reachable from a different direction, and it generalises.** For a company that
announces nothing, the signal is not an event but a *change in a static page* — and a change needs
us to have looked before. Three engineering roles appearing on `/careers` between March and June is
department-level hiring velocity, from a page now fetched for free, with no credential and no
terms-of-service exposure.

**The data model already supports it.** `evidence.source_hash` is keyed on URL and title and is
documented "deliberately not unique", so every observation of one page shares it. `excerpt_hash` is
keyed on URL and normalised text, so a page whose contents changed stores a new row rather than
deduplicating away. The grouping key and the version key both exist already. Nothing computes the
diff.

Three things would be needed: re-reading on a cadence rather than skipping inside the freshness
window, a step turning two observations of one `source_hash` into a change passage, and a signal
type whose evidence is that diff. One mechanism — **a date we supply, where the source gives none** —
would cover hiring velocity, leadership change, infrastructure change and headcount drift. Recorded
here as the shape of the answer; not built.

Backend 1,789 pass.

`services/site_sweep.py`, `alembic f2c8b4e71a93`, `tests/test_job_boards.py`.

## §83 — The headcount was write-once, undated, and on eight accounts (2026-10-05)

Asked whether a SERP API could track employee counts and their delta between runs, with Google
X-Ray as the cheap path for small companies.

**The blocker was ours, not Google's.** `resolution.py` held:

```python
if best.employee_count and not account.employee_count:
    account.employee_count = int(best.employee_count)
```

Four problems, none of which a better source fixes:

1. **write-once** — a second resolution run never refreshed it, so a company that grew from 30 to 33
   looked exactly like one that had not moved;
2. **undated** — "41 staff" was as-of whenever it first landed, possibly a September CSV;
3. **no history** — the moment it did change, the number it replaced was gone, destroying the delta
   at the instant it became computable;
4. **49 of 57 accounts carry no count at all.**

`a7e1d4c92f85` adds `employee_count_as_of`, `employee_count_before` and
`employee_count_before_as_of`, and `sizing.record_headcount` is the one place that decides what an
observation means:

* nothing known — store and date it;
* **the same number again — refresh the date only.** Writing it into `before` as well would collapse
  the window a real change is measured over, and the next change would read as "30 to 33 in zero
  days";
* a different number — the current value becomes `before` with its own date.

So the pair always spans a **real change** rather than the last two runs. Three observations and one
change report the month the growth happened in, not the quarter we happened to look across.

`None` is ignored rather than clearing the field: every source returns `None` for "I do not know",
and letting that erase a held number would make the stored value depend on which source answered
last — a company would lose its size by being looked at.

Dates are **ours, not theirs**. A directory page or a company profile carries no date, so the only
honest timestamp is when we looked. Nothing is backfilled for the same reason.

Wired into resolution (replacing the guard) and the manual edit, so a rep correcting a number leaves
the same trail an automated observation would.

### On the question as asked

The pasted analysis is right that Google returns no aggregated headcount and that its result-count
estimate is unusable. It misses something worse for us: **through Gemini grounding there is no result
count at all**, only a few cited passages — so the snapshot-delta method needs a real SERP API *with
pagination* and cannot be approximated.

And "SERP API for large, X-Ray for small" does not divide into two routes. **X-Ray is a query form,
not a retrieval route**; both halves need the same credential, because grounding excludes
`linkedin.com` for everyone (§64). There is no free fallback at the small end.

**The careers page already gives the signal more directly.** Three engineering roles appearing on
`/careers` between March and June *is* department-level hiring velocity — which is what a headcount
delta is a proxy for — from a page fetched since §82 at no model cost and no terms-of-service
exposure. LinkedIn headcount would be the most expensive route to a number we hold for eight
accounts.

### One thing worth keeping

`AccountOut` carries the three new fields. A stored value nothing can read is the inert-field problem
this session kept finding — unreachable sources, types that could not fire — and adding a fourth
would have been careless.

Caught by checking rather than trusting: the first version of that change compiled, the app built,
and the annotation was an **unresolved `ForwardRef`** because `date` was never imported. It would
have failed at serialisation, not at import.

Backend 1,796 pass.

`models/account.py`, `services/sizing.py`, `services/resolution.py`, `api/lists.py`,
`alembic a7e1d4c92f85`, `tests/test_sizing_and_runners.py` (+7).
