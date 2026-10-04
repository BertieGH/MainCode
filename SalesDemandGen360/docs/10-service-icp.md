> **SUPERSEDED by [11 — The ICP Model, Restated](11-icp-model.md).**
> This document proposed an ICP owned by a service, one each. The real shape is
> many-to-many, with ICPs standing alone — an account list has to target an ICP,
> and it cannot point at one that belongs to a service. Kept for the caching
> reasoning in "Prompt caching decides where the ICP goes", which still holds.

# 10 — Service ICPs

An ICP per service, created against the service that owns it. The ideal customer for QA outsourcing
is not the ideal customer for an AI pack, and one global ICP can only hold their union — the same
lossiness that made `archetype` the wrong shape ([09](09-vocabulary-rework.md)).

---

## Owned by the service, not shared

An earlier draft proposed ICP profiles as their own entity, referenced by services, so two services
could share one. **That was the wrong recommendation for this codebase**, and it is worth saying why
plainly rather than quietly changing it:

* A shared library needs machinery a handful of services does not justify — a profile list to
  navigate, a "which services use this?" lookup, and a deprecate-if-used rule so deleting a profile
  cannot strand a service.
* It buys deduplication for services that share an ideal customer. With CGVAK's service count, that
  is a cheap thing to lose and an expensive thing to build for.
* If sharing becomes real later, promoting a service's ICP to a shared entity is a **widening**
  migration — every existing row keeps working. Going the other way is not.

So: **one ICP per service, owned by it.** Create the service, then define who it is for.

---

## Two layers, because they answer different questions

The house ICP does not go away. It is consulted at a different time and about a different thing.

| | holds | consulted |
|---|---|---|
| **House ICP** — `org_profile.icp`, unchanged | Regions, industries, exclusions, compliance no-gos — *where we sell at all* | List building, research targeting, **industry multipliers** |
| **Service ICP** — new, per service | Company size, tech signals, pains, signals that matter — *who, within that, a service suits* | Strategy: which service to pitch, and how |

Two reasons this split is not arbitrary:

**Research runs before the service is known.** The pipeline researches an account, *then* strategy
picks a service per contact. At research time there is no service to take an ICP from, so research
can only use the house ICP. Narrowing research per service would mean N research runs per account
and N× the bill for a question strategy answers later for free.

**`scoring_config.industry_multipliers` reads the house ICP's industries.** Rows come from
`org_profile.icp.industries` ([09](09-vocabulary-rework.md)). Abolishing the house ICP would leave
that table with no source; keeping it means today's work is untouched.

It also avoids repeating "UK and US, not Government, not existing customers" across every service.

---

## Prompt caching decides where the ICP goes

The research prefix is `org` → `catalog` → proofs → samples, and every block must be
**byte-identical across accounts in a batch** or each account pays a cache miss on the whole prefix.

* Service ICPs live **inside the `catalog` block**, alongside the service they belong to. The
  catalogue is the same for every account, so the prefix stays identical and **caching is
  unaffected**.
* The tempting alternative — resolve the best-matching ICP per account and put it in the `org`
  block — makes the prefix vary per account and **misses cache on every single one**.

This is the one decision in the whole design with a direct bill attached, and the shape that reads
as more natural is also the cheap one.

---

## Schema

```
service_icp
  service_id  FK -> service_catalog(id) ON DELETE CASCADE
  icp         JSONB NOT NULL
  version     INT  NOT NULL
  is_active   BOOL NOT NULL DEFAULT false
  unique (service_id, version)
  partial unique index on (service_id) WHERE is_active
```

**Versioned per key**, exactly the pattern `llm_config` uses for its scenarios — one active row per
service. Not a JSONB column on `service_catalog`, for the reason `CLAUDE.md` gives: every config
table is versioned and never mutated in place. A stored strategy has to stay explainable against the
ICP that produced it, and an edited-in-place column makes "why did it pitch QA here?" unanswerable
three months later.

`ON DELETE CASCADE` is safe in a way it would not be for a shared profile: the ICP belongs to this
service and means nothing without it.

Note that `service_catalog` itself is **not** versioned — `is_active` there means "still offered",
not "the active version". That is a pre-existing inconsistency and this change does not widen it: the
ICP is the part that changes and therefore the part that needs history.

---

## What it changes downstream

**Strategy gets a real basis for service fit.** Today `ServiceInput` carries `service_id`, `code`
and `target_personas` — a list of role names, and the only service-fit input `score_personas` has.
Nothing currently lets it say whether the *company* suits the service. The service ICP is what turns
"this persona is targeted by QA" into "this account fits the QA profile and not the AI one", which
is the whole point of the change.

**`account.icp_match_score` becomes ambiguous** — one number, now several ICPs. Proposed: it stays a
single number holding the **best** match, plus `icp_match_service_id` recording which service won.
List sorting keeps working on one sortable column, and the score becomes explainable rather than
merely comparable. Per-service scores are a separate table if they are ever wanted; they are not
needed to make this work.

**UI**: the service editor gains an ICP section, using the factor editor built for the house ICP
rather than a second one. Signals stay a picker over the active signal types; industries on a
service ICP should be constrained to the house ICP's industries, since a service cannot sensibly
target a market the business does not sell into.

---

## Sequencing

1. **`service_icp` table + API.** Migration, versioned-per-service activation, CRUD. Nothing reads
   it yet, so it lands safely on its own.
2. **Service editor UI.** Reuse `app-icp-editor`; house industries constrain the picker.
3. **Into the catalogue block.** Service ICPs join the cached prefix. Verify
   `usage.cache_read_input_tokens` is unchanged across a batch — that assertion is the point of
   putting them there, so it should be tested rather than assumed.
4. **Strategy uses it.** `ServiceInput` carries the ICP; `score_personas` weighs company fit.
5. **`icp_match_score` semantics.** Best match plus the service that won.

Steps 1–3 are inert with respect to behaviour. Step 4 is where output changes.

---

## Decisions still open

1. **Field split.** The table above is a proposal. Which factors are house-wide and which are
   per-service is a judgement about how CGVAK sells, not a technical constraint.
2. **A service with no ICP.** Proposed: it is scored on the house ICP alone and flagged, never
   guessed — the same rule as an unmapped industry. A service must not become unpitchable because
   nobody has written its profile yet.
3. **Does the house ICP keep `signals_that_matter`?** It is arguably entirely service-specific. Left
   in both for now; if it turns out never to be set at house level, it should move.
