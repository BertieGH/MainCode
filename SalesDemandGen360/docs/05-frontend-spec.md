# 05 — Frontend Spec

Angular 17 (standalone components, signals, new control flow). Angular Material as the component
base. One `ApiService` per domain under `src/app/core/api/`, no mock data past M0.

## Design posture

The approach document's own styling is the reference: a calm, document-like editorial surface —
serif headings, monospace for identifiers and scores, generous whitespace, colour used only to carry
meaning (accent = system conclusion, amber = governance gate, red = risk/rejection). It should read
like a research brief a rep trusts, not a CRM dashboard competing for attention.

Three semantic conventions carry throughout and must never be decorative:

| Convention | Meaning |
|---|---|
| Amber border / background | A governance gate — evaluation or human approval |
| Dashed border | Hypothesis, not verified fact |
| Monospace `ev_###` chip | A clickable evidence reference |

## Routes

| Route | Page | Milestone |
|---|---|---|
| `/` | Dashboard — **Today / Performance / Quality** tabs | M1→M6 |
| `/lists` | Account Lists index | M1 |
| `/lists/:id` | List detail — accounts table | M1 |
| `/accounts/:id` | Account detail (tabbed) | M1→M4 |
| `/queues` | Campaign Queues index | M3 |
| `/queues/:id` | Queue detail — members, editable while draft | M3 |
| `/queues/new` | Queue builder — multi-list cherry-pick | M3 |
| `/campaigns` | Outreach — Campaigns / Live threads tabs | M4 |
| `/campaigns/:id` | Campaign detail — **Approval** / Threads / Cadence tabs | M4 |
| `/threads/:id` | Thread execution timeline | M4→M5 |
| `/learning` | Learning — candidate patterns table | M6 |
| `/learning/:id` | Pattern detail — traceability drill-through | M6 |
| `/settings/*` | Configuration assets | M0 |

**Two screens were removed, deliberately.** `/pipeline` folded into the Dashboard's Performance and
Quality tabs — it duplicated the Dashboard once that became outreach-centric. `/review` (Approvals)
was removed because approval now happens **inside the campaign** rather than in a separate inbox.

*Known cost of merging Pipeline in, and the mitigation:* tabs past the first get opened less, and the
retrospective data is exactly what the Learning layer needs someone to look at. Two counterweights
are built in — the **Quality tab carries an attention dot** when a metric moves materially, and the
Today tab ends with the approve-without-edit rate and a "See what changed" link that deep-links into
Quality. The number stays visible even when the tab is not.

**Naming:** "Review Queue" became **Approvals** once campaign queues existed — two things called
"queue" in one nav is a usability trap.

## Sortable tables — one implementation

Every index and member table sorts on every column. Build **one** directive with a three-state cycle
(asc → desc → none, where none restores insertion order) and apply it everywhere; do not hand-roll
per table. It pairs with the single backend sort dependency in [04](04-api-surface.md).

## Queue builder

The screen that makes "one account from each of three lists" possible. Two panes: source lists on
the left, each expandable to a checkbox account table; a running **basket** on the right with a live
count of accounts and distinct source lists. Selecting copies — the basket note says so explicitly,
because a rep who expects a live link will be surprised later.

## Campaign detail — Cadence tab

A **mirror of the LGM sequence**, not an editor — see *Campaign → Cadence tab* later in this
document for the full spec. It shows the selected LGM campaign, the attribute budget, and each step
in order with its `{{custom_attribute_N}}` binding, sync badge, and the copy written for a chosen
lead.

There is no step editor and no "Add step". Cadence structure is LGM's; changing it means changing it
in LGM and re-verifying the registration.

---

## Dashboard `/` — outreach performance

Outreach-centric and queryable, not a vanity metrics wall. A shared filter bar (campaign, period,
persona, industry, free-text search) drives everything below it, and **every figure drills into the
threads behind it**.

- **Six KPI tiles**, all clickable: active threads, touches sent, reply rate, meetings booked,
  pending approval, blocked/skipped — each with a period-over-period delta
- **Touches sent per day**, read against the daily send caps
- **Reply rate by touch number** — the evidence for or against a 6-touch cadence. If touch 6 never
  earns a reply, that is an argument to shorten the template, and this chart is where it shows up
- **Campaign performance table** (sortable): threads, sent, opened, replied, meetings, reply rate
- **Needs attention** — replies awaiting acknowledgement, touches awaiting re-approval, skipped
  sends. Everything here blocks a send until someone acts, and each row drills into the thread
- **Reply rate by persona**, plus the approve-without-edit rate as the standing gate metric

## Thread execution `/threads/:id`

The answer to "what has actually gone out to this person, and what is about to?" Reached from the
campaign threads table, live threads, or any dashboard drill-in.

Header: contact, persona, campaign, cadence, thread rank; a progress bar; and counts by state.
Alongside it, **why this thread's cadence differs from the template**, each deviation with its
reason and evidence.

Then the **cadence execution timeline** — one card per touch, colour-striped by state, expandable to
read the content:

| State | Shows |
|---|---|
| `sent` | Timestamp, the exact content sent, engagement (opened / clicked / accepted / replied), who approved it |
| `scheduled` | Queued time and the approved content, already written to the LGM lead |
| `pending` | Approved and written, not yet due |
| `stopped` | The failed freshness check with its reason, the content that will now never send, and *Re-enrol with fresh content* / *Leave stopped* |
| `skipped` | Why it was dropped — no content was generated and nothing was sent |

The `stopped` case is the one that earns this screen. Because content is frozen at enrolment, a
failed check cannot rewrite the touch — it halts the rest of the sequence, and the rep needs to see
exactly which words never went out and why.

## Account lists `/lists` and `/lists/:id`

Index: Label, Source, Accounts, Researched, Qualified, In queues, Created — all sortable.
List detail sortable table: Name, Industry, Size, Country, ICP score, Priority band, Status, Threads active,
Last activity. Filters mirror the API query params. Bulk actions: run pipeline, disqualify, export.

CSV import opens a dialog that shows the **per-row outcome** after upload — created / merged /
skipped with the reason. Reps distrust silent imports, correctly.

## Account detail `/accounts/:id`

Tabs, left-to-right in pipeline order. Each tab is only enabled once its stage has produced data.

### Overview
Firmographics, CRM link, ICP match with reasons, buying committee cards (name, title, persona role,
verification badges on email/phone). Unverified contacts render with a dashed border and a
"not contactable" note — visible before a rep wonders why a thread will not start.

### Evidence & Signals
Signal list grouped by type. Each signal row: type chip, summary, business implication, strength bar,
confidence percentage, observed date, lifecycle state chip, and its `ev_###` evidence chips.

Clicking an evidence chip opens a side panel with the source name, URL, retrieval time, observation
date, and the exact excerpt. **This is the trust-building surface of the whole product** — the first
thing a sceptical BDE will click. Build it properly in M1, not as a stub.

Rep controls per signal: adjust strength, mark expired, mark invalid.

### Qualification
The six-dimension panel: labelled score bars, priority formula strip
(`FIT + INTENT + TIMING + ACCESS = OPPORTUNITY PRIORITY`), band badge, per-dimension reason text
with inline evidence chips. Legacy MAN line beneath a dashed divider when
`scoring_config.man_view_enabled`.

### Strategy
Two parts:

1. **Persona × service matrix** — every mapped persona against every service, with weight, best-fit
   service, and thread status (`Active — primary` / `Active — secondary` / `Queued — thread cap
   reached` / `Not activated — below threshold`). Non-activated rows stay visible; "why didn't we
   contact the CEO?" must be answerable on screen.
2. **Thread cards**, one per active thread — problem hypothesis (dashed border: it is a hypothesis),
   trigger with signal chips, capability, positioning, channel, CTA, avoid-list, confidence.

Rep can edit any field on a thread, activate a queued thread, or drop one.

### Outreach
Per thread: a 6-column cadence timeline. Each touch card shows day, channel, purpose, status, and
the current draft (expandable). Channel colour-codes the top border — accent for LinkedIn, amber for
email. Per-touch: edit, regenerate, view version history — all **only before the sequence is
enrolled**. After enrolment the tab is read-only, because the copy is frozen on the LGM lead.

### Sales Prep

**Not here.** The account-detail tab is a pointer to the Sales Prep menu, explaining why: a brief is
prepared for a **person before a specific conversation**, not for an account in the abstract. The tab
lists the account's contacts and their prep status, and links onward.

### Timeline
One merged chronological stream: signals discovered, context versions, qualification changes,
strategy versions, drafts, approvals, sends, engagement events, outcomes. Filterable by actor
(agent / user / system). This is `audit_log` made legible.

---

## Approvals — the surface that decides adoption

Reached at `/campaigns/:id` → Approval tab. There is no standalone `/review` route; approval lives
inside the campaign so a rep always sees the campaign a thread belongs to.

If reps do not use this screen, nothing else matters. Design constraints:

- **Everything needed to decide is on one screen.** No navigating away to check a signal.
- **Keyboard-first.** `A` approve, `E` edit, `R` regenerate, `X` reject, `J`/`K` to move. A rep
  clearing 40 items with a mouse will stop clearing 40 items.
- **The evidence is one click from the claim**, never two.

Layout: approval list on the left (ranked by priority, then age), item detail on the right containing —

1. Account name, priority band badge, strategy confidence
2. Top evidence-backed signals with their chips
3. Recommended persona + strategy rationale
4. Proposed CGVAK capability
5. The draft message, inline-editable
6. Evaluation Agent findings, if any — surfaced as a banner, not hidden
7. Action row: **Approve · Edit · Regenerate · Reject**

**Reject is a two-step interaction.** Clicking Reject reveals the mandatory reason chips —
*Wrong Persona · Wrong Signal · Wrong Problem · Wrong Solution · Poor Message · Other* — plus an
optional comment. Rejection without a reason is not submittable. That structured reason is the
system's highest-value learning input; making it optional would quietly kill the M6 gate.

Edits are stored as a delta against the generated draft, never as a silent overwrite.

---

## Outreach monitor `/outreach`

Active threads across all accounts. Columns: Account, Contact, Persona, Thread rank, Current step,
Next touch date, Status, Last engagement. Row highlight for threads paused by a cross-thread reply,
with a one-click "acknowledge reply" that releases the pause.

## Pipeline `/pipeline`

Funnel counts by outcome stage, plus the four analytics views: signal performance, persona
performance, service performance, and approval quality. Approval quality is first, not last —
it is the gate metric.

Charts follow one consistent palette; no chart carries meaning by colour alone.

## Learning `/learning`

Candidate patterns with sample size and confidence. Each row: pattern description, supporting data,
and Validate / Reject / Promote actions. **Promote opens a confirmation showing exactly which config
value or prompt template would change, and creates a new version rather than mutating the active
one.** Nothing here changes production silently.

## Settings `/settings/*`

There is no separate "Org profile" screen. It held two unrelated things — who CGVAK *is* and who it
sells *to* — and the second outgrew it. Identity is two fields at the top of ICP profiles; the buyer
side is the list beneath. See [11](11-icp-model.md).

Ordered by dependency, not alphabetically: you cannot describe a buyer before you have something to
sell them, and nothing runs before a key exists. The nav is that order top to bottom.

| Sub-route | Content |
|---|---|
| `/settings/setup` | **API settings** — credentials, per-provider test, model shortlist. First because everything else needs a key |
| `/settings/models` | Model config — provider and model per stage, from the shortlists chosen above |
| `/settings/icp-profiles` | **Company identity** (name, description — who is *selling*) plus every ICP, its linked services, and its definition |
| `/settings/services` | Service catalog + proof points (with an approval toggle per proof point) |
| `/settings/writing` | Writing samples |
| `/settings/rules` | Sales rules — thresholds, thread cap, cadence editor, no-go list, compliance |
| `/settings/scoring` | Dimension weights, band cut-offs, MAN toggle; version list with activate |
| `/settings/signal-types` | The signal registry — scope, TTL, weight, producing families |
| `/settings/prompts` | Per-stage prompt templates with named presets and reset-to-default *(not built)* |
| `/settings/research` | Industry and size multipliers, persona taxonomy, query families — all with promote/demote weight controls |
| `/settings/integrations` | Claude credentials + spend cap, per-scenario model config, Apollo / ContactOut / LGM / CRM credentials |

Rules and scoring pages must show the **version history** and make clear that saving creates a new
version. Activating a new scoring version prompts "re-score all accounts?" — it is cheap and
deterministic, so the answer is normally yes.

## Cross-cutting UI rules

1. A hypothesis never renders identically to a fact.
2. Every score shows its reason on hover or expand; no bare numbers.
3. Every conclusion has a clickable path to its evidence.
4. Long-running actions show which stage is running, not an indeterminate spinner.
5. Anything that could send a message is visually distinct and confirms first.


## Settings — weights and credentials

**Research & taxonomy** exposes three tunable maps as promote/demote controls (`−` / value / `+`,
stepping by 0.05): industry and size → dimension multipliers, buying role → persona weight, query family →
signal weight plus an on/off toggle. Saving creates a new `scoring_config` version and offers a bulk
re-score, which is free because the maths is deterministic Python.

**Integrations** has four groups: Claude (API key, monthly spend cap, month-to-date spend), the
per-scenario model table (scenario → model, effort, max tokens, output contract), enrichment
providers (Apollo, ContactOut — key, credits, test connection), and outreach execution (LGM — key,
webhook secret with rotate, daily send caps), plus the blocked custom CRM.

Credential fields are **masked, write-only inputs**. The UI shows `last_four` and never requests a
full value from the API — there is no endpoint that would return one.


## Table conventions — every list, every screen

One pattern, applied without exception, so a rep learns it once:

| Position | Contents |
|---|---|
| **Leftmost column** | Selection checkbox. Header checkbox selects all, and shows an indeterminate state on a partial selection |
| Middle columns | Data — all sortable, three-state cycle |
| **Rightmost column** | Actions — always icon buttons, never text buttons |

**Action icons are fixed vocabulary.** One icon means one thing across the whole app:

| Icon | Action | Styling |
|---|---|---|
| Eye | View / drill in | Muted, accent on hover |
| Bin | Delete / remove | **Red at rest**, not only on hover — destructive actions announce themselves before the pointer arrives |
| Pencil | Edit | Muted, accent on hover — used on config tables where a row is edited in place rather than opened |

A text button in an action column (an earlier `Remove` button on queue members) is a bug, not a
variant. Every table gets the same treatment including analytics and configuration tables, where the
action set narrows — view-only on the dashboard's campaign table, edit-only on taxonomy tables whose
rows are not user-deletable.

Selecting one or more rows reveals a **bulk action bar** above the table with the count and the
actions valid for that entity (re-run research, enrich, add to queue, remove). Clicks inside the
checkbox or action cells must `stopPropagation` — otherwise selecting a row also triggers its
drill-in navigation.

Rows carry a `picked` highlight while selected, so the selection stays visible when the bar scrolls
out of view.

## Account list detail — research and enrichment

Two independent status columns, not one:

| Pill | Research | Enrichment |
|---|---|---|
| Complete | All query families ran | Committee resolved with contactable details |
| Partial | Some families returned nothing | Email but no phone, or some contacts unresolved |
| Failed | Site unreachable, nothing extracted | No contactable person found by either provider |
| Not started / Skipped | Never run | Never run, or deliberately skipped as unqualified |

Both pills carry the reason on hover from `account.pipeline_note`. **"Show incomplete only"** is a
one-click filter for everything that did not finish cleanly — the view a rep uses to decide what to
re-run — and the page footer states the count outright ("2 accounts need attention").

`Run research` and `Enrich` are **separate buttons**. Enrichment spends provider credits per lookup,
so it is never implied by an import or a research run.


## Dashboard — three tabs, three questions

| Tab | Question | Contents |
|---|---|---|
| **Today** | What do I do now? | Threads awaiting approval, replies to acknowledge, blocked sends, campaigns executing; send capacity against daily caps; needs-attention list; approve-without-edit rate as a doorway into Quality |
| **Performance** | Is it working? | Filters + date range, funnel, reply rate by touch number, campaign performance table, reply rate by persona |
| **Quality** | Should I trust it? | Approval quality split, rejection reasons, **read vs accepted-unread comparison**, signal→meeting lift, what-changed-this-week |

Filters live on Performance and Quality only. A date range means nothing on Today, and putting one in
a shared header is how the merged layout gets confusing.

The **read vs accepted-unread** panel on Quality is the control on sampling: it compares reply rates
of drafts a human actually read against those accepted on the strength of a sample. If the gap
widens, the sample rate is too low.

## Campaign approval — stratified sampling

Approval lives on the campaign, as an **Approval tab** that carries an attention dot while threads
are waiting. Two strata, and the split is the whole point:

**Needs your eyes** — never sampled, every one read individually. A thread lands here for an
evaluation warning, an unverified contact, low strategy confidence, or a cadence deviation from the
template.

**Clean** — the app draws a **random** sample; the rep cannot choose which. Approving the sample
accepts the rest of the stratum.

| Control | Behaviour |
|---|---|
| Sample rate | From `sales_rules`. Starts high (40%+) for a new service × persona combination, falls as approve-without-edit proves out. 100% for a first-run campaign |
| Redraw | A rep may redraw the sample but never hand-pick it — the point of randomness is that it cannot be gamed |
| 1 rejection in sample | Sample size doubles |
| 2+ rejections | Whole batch drops to individual review |
| Recorded as | `approval.review_depth` = `individual` / `sampled` / `inherited`, plus the sampled ids |

Uniform sampling would be the flaw here: a random 6 of 18 could miss all four flagged threads.
Stratifying first is what makes the model defensible rather than a faster way to rubber-stamp.


## Learning — pattern detail

The screen exists to make a pattern falsifiable before it is promoted. Order matters: the maths, then
the claim in plain language, then the confounders, then the cases — supporting *and* counter — then
what promotion would change.

- **Four stat tiles**: lift, supporting count, counter count, confidence against the promotion bar.
  Counter-example count is styled as a warning, not a neutral figure — it should feel like something
  to look at.
- **The claim in prose**, precise enough to be falsifiable: rates, window, date range, population.
- **Confounder panel** in amber when a concentration is detected ("29 of 34 supporting cases are
  SaaS"). It does not block promotion; it stops promotion happening blind.
- **Two case tables**, both with evidence chips opening the same side panel used on the account
  screens. The counter-example table carries a "plausible reason" column — an enterprise account
  that never replied to a 6-touch cadence is a cadence finding, not a signal failure.
- **Promotion preview** as a config diff, with `Promote, scoped` offered alongside `Promote globally`
  when confounders suggest the finding is narrower than it looks.
- **Post-promotion measurement**, so a promoted pattern stays under review rather than becoming a
  permanent assumption.


## Create flows — one component, twelve instances

Every "New" / "Add" action opens the **same form modal**, rendered from a field spec rather than
hand-built per entity. Build it once as a config-driven component; twelve bespoke dialogs is twelve
places for the styling and validation to drift.

Field types the component supports: `text`, `textarea`, `select`, `chips` (tag input), `toggle`.
Each field carries an optional hint line — used throughout to explain a consequence rather than
restate the label.

| Form | Opened from | Notable fields |
|---|---|---|
| New account list | Account Lists | Label, description, source |
| New service | Settings → Service catalog | Code, positioning angles (chips), target personas (chips) |
| New proof point | Settings → Service catalog | Kind, quantified outcome, substantiation, **approved toggle** |
| New industry | Settings → ICP profiles | Added to an ICP definition; its multiplier row then appears under Research. Rows are the **union** across active ICPs |
| New buying role | Settings → Research | Title keywords (chips), seniority, persona weight |
| New query family | Settings → Research | Feeds signal type, weight, **"can create a signal alone"** toggle |
| New model scenario | Settings → Integrations | Model, effort, max tokens, output contract |
| Add contact | Account → Overview | Title (auto-normalised), **is-hypothesis** toggle |
| New writing sample | Settings → Writing samples | Channel, body, why it works |
| Add cadence step | Campaign → Cadence | Day offset, channel, purpose |
| Save to cadence library | Campaign → Cadence | Template name, allowed channels, max touches |
| Save rules as new version | Settings → Sales rules | Change note, activate immediately |

Three hint lines carry real rules and should survive into the build verbatim in spirit:

- Proof point → *"Unapproved proof points cannot appear in a draft; evaluation fails the draft."*
- Add contact → *"Email and phone stay unverified until enrichment resolves them — an unverified contact cannot be emailed."*
- Query family → *"Off means it can support a signal but never create one"* — the reviews-family rule, made settable.

## CSV import — three steps, no silent writes

Import is not a file picker. It is a **dry run you confirm**.

1. **Choose destination and file.** Import into a new or existing list; appending never replaces.
2. **Map columns.** Only company name *or* domain is required. A notes column can map to
   **Manual evidence**, creating an attributed evidence record per row rather than a free-text blob
   on the account.
3. **Dry run.** Counts by outcome — new / merged / skipped / unresolvable — and a per-row table with
   the reason for every non-create. Nothing is written until confirmed.

**Research does not start automatically.** Imported accounts land `not_started`, because research
costs money and the rep should choose what is worth spending it on.

## New campaign — three steps, ending in pre-flight

1. **Label and source queues.** Locked queues are shown but disabled, with "clone it to reuse" as the
   explanation rather than a silent omission.
2. **Cadence template.** Library templates or start blank.
3. **Pre-flight, before creation.** Thread availability, contact dedup, **global thread cap**, no-go
   screen.

The thread-cap conflict is the reason this is a three-step flow rather than a single form. It names
the offending accounts and the campaign already working them, then offers a resolution — exclude
them, or include and pause the other threads. Discovering this *after* creating a campaign would mean
unpicking it; discovering it at send time would mean invisible skips.


## Campaign → Cadence tab — a mirror, not an editor

The cadence lives in LGM, so this tab **reflects** it rather than editing it. What it shows:

| Element | Purpose |
|---|---|
| LGM campaign card | Shape name, `lgm_campaign_id`, channels, leads enrolled, deep link to LGM |
| Attribute budget meter | Used vs the 10-per-lead cap — the constraint that decides touch count |
| Lead selector | View the sequence as it will run for one specific lead |
| Sequence simulation | Each LGM step in order: day, channel, attribute binding, sync status, and the content we wrote |

Each step shows its `{{custom_attribute_N}}` binding and a sync badge (`written` / `written · sent` /
`not yet written`). That badge is the point: our database holding a draft is not the same as LGM's lead
holding it, and a rep needs to see which is true.

There is deliberately **no drag-and-drop step editor**. A node-graph builder costs weeks and earns its
keep on branching — and our branching is expressed as shape selection plus deterministic adaptation,
not as a graph. Editing steps happens in LGM, where they actually live.

A "View in La Growth Machine →" link is for troubleshooting, not authoring.


## Settings → LGM cadences

The registration surface for what exists in LGM. Not an editor — there is no way to change a step here,
by design.

| Element | Purpose |
|---|---|
| Registered cadences table | Shape, LGM campaign id, touches, span, attributes used / 10, selection rule, last verified |
| Attention summary | Cadences LGM reports as changed since verification, those past the 90-day backstop, and selection rules pointing at unregistered shapes |
| Step mapping | Per-shape: step, day, channel, `custom_attribute_N` it reads, subject source, and the derived signal-anchoring rule |

The step-mapping table is the contract a developer implements against. Its **signal anchoring** column
(`Dated allowed` / `Implied only` / `Durable only`) is derived from the cadence span rather than
configured, since it depends on how far ahead each touch is written.

Two states the UI must make obvious, because both fail silently otherwise: a cadence whose verification
has lapsed (enrolment blocked), and a selection rule pointing at a shape nobody registered (falls back
to default, warns).


## Campaign → Approval tab

Everything needed to get from a drafted campaign to an executing one, in the order a rep works it.

**1. Triage.** Two strata, because they demand different attention.

| Stratum | Behaviour |
|---|---|
| **Needs your eyes** | Every thread read individually. A thread lands here for an evaluation warning, an unverified contact, low strategy confidence, or a cadence deviation |
| **Clean** | The app draws a **random** sample the rep cannot hand-pick. Approving the sample accepts the stratum |

**2. All threads.** A sortable, filterable table of *every* thread — contact, persona, the cadence
selected for it, draft count, evaluation verdict, review state. Any row opens its arc.

This table is not redundant with the triage cards, and the distinction matters: **the sample decides
what a rep _must_ read, never what they _may_.** Without it, a rep who wants to check a specific
account has no route to it.

Cadence differs per row because it is *selected*, not authored — visible in the table, which makes the
selection rules legible without opening Settings.

**3. Execute.** A pre-flight list and the button, disabled until every check passes:

| Check | Blocks execution |
|---|---|
| Threads approved | Yes — 0 of 18 blocks |
| Cadence registration current | Yes — a changed-in-LGM shape blocks |
| Attribute budget within 10 | Yes |
| Contact enrolment lock | Yes — names the conflicting contacts |
| No-go and unsubscribe screened | Yes |

Directly above the button, the freeze warning: after execute the words cannot change, and the only
levers are stopping one contact's sequence or the whole campaign.

## Arc review — the screen the gate depends on

Reached from any thread row, any flagged thread, or *Review sample*. One thread, its whole arc.

**Context row across the top** — three cards, matching the page-head-then-content pattern used
everywhere else:

| Why this person | Strategy | Last edit point |
|---|---|---|
| The signals driving the thread, with confidence and a one-line reason each | Hypothesis, capability, positioning, CTA, avoid-list | The freeze warning |

**The arc below, full width.** One card per touch, in cadence order, each showing:

- Step, day, channel
- The **`custom_attribute_N` it writes to** — the LGM binding visible at the moment of approval
- **What it anchors to**, with the evidence chip, click-through to source
- The draft, **editable in place** — Edit makes the textarea live, Save commits
- Regenerate, per touch
- Its signal-dependence band: `Dated allowed`, `Implied only`, or `Durable only`

**Sticky footer**: Approve arc, Reject with mandatory reason. Keyboard `A` / `X` / `J` / `K` / `N`.

**Sample pager at the top**: *n of 6*, dots filling as threads are approved, and a line stating that
approving the sample accepts the unsampled remainder as `review_depth = sampled`. Rejecting one
announces the sample has doubled — the escalation rule made visible rather than buried in config.

Full width matters here: an email body wrapping inside a two-thirds column reads nothing like it will
in an inbox, and this is the screen where that judgement is made.

## Settings → signal types, split by scope

Two separate registries rather than one table with a scope column, because they answer different
questions and are tuned independently:

- **Company signal types** — evidence about the organisation. Answers *why now*.
- **Contact signal types** — evidence about a person. Answers *why you*, and decides which persona leads.

Each has its own Add button opening a scope-fixed form, so a contact type cannot be created and
accidentally scoped to company. Badge colours match the striping used on the account's Evidence &
Signals tab, so the two screens read as one system.

## Account detail → Evidence & Signals

Split the same way: **Company signals** then **Contact signals**, the latter grouped per person and
amber-striped. Both carry evidence chips — a contact signal is not a weaker kind of signal, it is a
signal about a different subject.

A contact with nothing found is **rendered as a card, not omitted**: *"Nothing found about this
person — a gap, not a pass."* An absent contact signal is information, and it is why that persona's
thread ranks below the others.

## Structural integrity check

`mockups/check_ui.py`, run after every UI edit:

```bash
python mockups/check_ui.py
```

It exists because the same failure recurred three times while building the walkthrough: a splice
removed a panel and left the button that opens it, so a tab rendered blank with no error anywhere —
in the browser, the console, or the file. It checks 15 rule groups: every nav button has a view,
every tab button has a panel and vice versa, exactly one default-active panel per group, no
suspiciously empty panels, balanced divs, every `onclick` resolving to a defined function, and every
`openForm` key present in `FORMS`.

Its first run caught two dead handlers — `pickReason` had been deleted along with the standalone
review queue, which silently broke *reject* on the approval screen: the reason chips did nothing and
Confirm stayed disabled. Nothing surfaced that until the check ran.


## Sales Prep `/prep` and `/prep/:contactId`

Its own menu item rather than a tab, because prep is **on demand, one contact at a time** — the only
part of the system with no batch mode.

**Index.** Search across *any* contact, plus a queue of those with a reason to prep — meeting booked,
or a reply asking for a call. Columns: Contact, Persona, **Why now**, Meeting, **Research age**, Prep
status. Sortable like every other table.

The queue is a convenience, not a gate: a contact with no meeting can be found by search and prepped
anyway. A rep who wants to prepare before there is a calendar invite should not be blocked by the
data model.

**Detail.** Breadcrumb `Sales Prep / <account> / <contact>`, then three steps in order:

| Step | What it does |
|---|---|
| 1 · Refresh what we know | Re-runs research and enrichment for this account and contact only, with the cost stated |
| 2 · Add what you know | Opens the manual-intel composer — whatever surfaced when the meeting was booked |
| 3 · Generate the brief | Uses current signals, the strategy thread, and everything actually sent and replied |

Two panels carry most of the value:

- **Staleness banner.** Research age against the meeting date and the touches sent since it ran, shown
  *before* generation. A confident brief built on a stale picture is worse than no brief.
- **"What we already said."** The touches sent, their engagement, and the reply verbatim — with the
  explicit note that the brief must not re-argue points the contact has already heard and agreed with.
  For a call this matters more than the original signals.

Exports (`pptx` / `docx` / `pdf`) stay disabled until a brief exists.
