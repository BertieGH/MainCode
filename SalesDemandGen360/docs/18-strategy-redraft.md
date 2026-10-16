# Strategy redraft: ranked angles from the whole picture

**Status: built (2026-10-15).** Prototyped first beside the current stage on 3
qualified and 3 unqualified contacts, then wired in, then the same 6 rebuilt
through the real app path. Results are summarised at the end
(no prospect names: this repository is public).

## Why

Strategy is the stage everything after it is written from: cadence drafts
and sales prep both argue from it. The trace of the current stage found:

- **The decision of who to approach was idle.** 216 of 218 contacts had no
  buying role and seniority `unknown`, because the CSV and Apollo imports never
  run the title classifier. Every founder, CEO and CTO weighed 7 against a
  threshold of 50, so every thread in the book was a "pursue anyway" override.
- **The model was not told the campaign's ICP**, only a service code, while
  its instructions depend on the ICP's `track`.
- **It got signal summaries, not the evidence behind them**, and no ranking of
  which signal matters most.
- **One argument per person.** The rep could not choose between ways in.
- `account_angle` was generated, paid for and discarded.
- Drafting saw less of the person than strategy did (no profile).

## The rule this is built on

**Gates decide who; they never shape what is said.** Weight, the ICP
qualification score and a rep's override decide only whether a person
proceeds to strategy and drafting. Once a person proceeds, none of them reach
the model. An overridden person gets the same quality of argument as one the
rules chose. `weight`, `rank` and `thread_status` leave the payload.

## The context the model gets (one call per company)

| Block | Contents |
|---|---|
| `company` | Facts and profile (what it sells, to whom, what it is pushing) |
| `company_signals` | Live company signals, **ranked** (below), each with type, summary, business implication, strength, confidence, age in days, whether the ICP lists its type, and up to two **evidence excerpts** with source and date |
| `icp` | The campaign's ICP version: name, `track`, industries, regions, size, personas, `signals_that_matter`, exclusions |
| `service` | The campaign's service: name, description, positioning angles, economic buyer |
| `proof_points` | Approved proof for that service, plus general ones, by id |
| `people` | Per person: title, seniority / buying role / department (classified from the title where not stored), the ICP persona they match, their profile, and their own ranked **contact signals** |

Retrieved text (excerpts, profiles) travels inside the untrusted-content
delimiters, as qualification's already does.

## Signal ranking (computed in Python, not by the model)

`rank_score = strength × confidence × recency × icp_match × about_this_person`

- strength: high 3, medium 2, low 1
- recency: halves every 60 days since the signal was observed
- icp_match: ×1.5 when the signal's type is in the ICP's `signals_that_matter`
- about_this_person: ×1.3 for a contact signal, in that person's list

Deterministic, like every other score here (invariant 7), so a rep can be
told why one signal led an angle and another did not.

## What comes back

Per person, **2–3 angles**, each a complete way in:

- `angle`: a short name for the way in
- `problem_hypothesis`: what we think hurts *this person*
- `why_now`: the moment, tied to `trigger_signal_ids` (empty only where a rep
  allowed no signal)
- `positioning`: the service framed against that problem
- `proof_point_ids`: approved proof only, from the list given
- `cta`, `avoid`, `confidence`

The model ranks them (`recommended_order`, with a one-line reason), and adds
one company-level `account_angle` sentence. The service checks:

- cited signals are live;
- cited proof is approved;
- each person's **top-ranked** angles differ across the company (the existing
  differentiation rule).

## Storage and use

- `strategy_angle` rows under each thread hold every angle with its rank. The
  thread's own fields mirror the **selected** one (rank 1 by default), so
  drafting, approval and prep keep working unchanged.
- A rep can select a different angle; that re-opens the person's drafts.
- `strategy.account_angle` is stored.
- **Drafting** gets the selected angle, its proof, the account angle and the
  person's profile.
- **Sales prep** gets the selected angle and the alternatives, as fall-back
  talk tracks for the call.

## Prototype results

Run 2026-10-15 on `gemini-3.8-flash` (the live stage's model), one EIA campaign,
Default ICP (`enterprise` track). Six contacts at six companies: three whose
company is qualified (medium band, 2–3 live signals) and three with no
qualification and no live signal. "Old" is each contact's stored strategy.

| | Old | New |
|---|---|---|
| Ways in per person | 1 | 2, ranked, with the reason for the order |
| Lead signal (qualified) | Not ranked. One led with a 177-day-old acquisition over a hiring signal from the same week | Highest-ranked signal leads every time; older signals become the second angle |
| Proof points cited | Never (no field) | Every angle, approved only, all checks passed |
| Confidence with no live signal | 0.65–0.72 | 0.30–0.40, as the evidence warrants |
| Role the model was told | `unknown`, no buying role, for all six | Classified from the title: technical or economic buyer, C-level |
| Account angle | Generated, discarded | One sentence, kept |
| Cited signals not live / proof not approved | — | 0 / 0 |
| Cost per company | similar | 2.5–3.4k tokens in, 0.5–0.85k out, 14–18 s |

**What the run also showed:**
- **Positioning is copied word for word** from the service's only positioning
  angle, including its odd capitalisation, in every angle at every company.
  Partly the prompt ("use the service's own positioning angles") and mostly
  the service record: EIA has a one-line description, one positioning angle
  and one proof point with no metrics. The prompt is changed to paraphrase.
  The catalogue needs content — that is input, not code.
- **The second angle converges on "knowledge silos"** at every company, for
  the same reason: there is one proof point to argue from.
- **Contact signals are nearly empty** (1 of 157 live signals is about a
  person), so the person-level material is the contact profile. Contact-level
  research is a separate gap.
- One model output prefixed its hypothesis with "Hypothesis:". The prompt now
  says the label is added by the UI.

## Built

- `models/account.fill_role_from_title` classifies seniority, buying role and
  persona key on every contact write, filling blanks only. Existing contacts
  were backfilled with `scripts/classify_contacts.py` (215 of 218).
- `services/strategy_context.py` builds the payload and ranks the signals.
- `schemas/strategy.py` is the new contract (`StrategyProposal` → `people` →
  `PersonAngles` → `StrategyAngle`).
- Migration `d7e2a9c4f1b8` adds `strategy_angle` and `strategy.account_angle`.
  It backfills one selected angle per existing thread and stores the new
  instructions as the next `strategy_synthesis` prompt version (earlier
  versions are kept).
- `campaign_strategy.build` stores every angle that survives the checks and
  auto-selects rank 1. `select_angle`
  (`POST /campaigns/{id}/people/{contact}/angle`) lets a rep pitch another. It
  re-opens saved drafts, is refused once enrolled, and is audited.
- Drafting gets the selected angle, its approved proof, the account angle and
  the contact's profile, and no longer gets a channel list. Sales prep gets the
  selected angle plus the alternatives as talk tracks.
- The person drawer's Strategy section shows the account read and the ranked
  angles, with "Pitch this angle".

**The live rerun** of the same 6 contacts through the real path:
- It found one bug the injected-synthesiser tests could not reach (the default
  synthesiser passed an argument the stage does not take). That is fixed, and
  `TestTheRealCallPath` covers it.
- Positioning is no longer copied from the service record.
- With roles classified, the 4 economic buyers were pursued by the rules on
  their own. The 2 CTOs (technical buyer, weight 40) are still below the
  threshold of 50 and need an override — a sales-rules decision, not a bug.

