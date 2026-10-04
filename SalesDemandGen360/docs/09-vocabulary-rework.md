> **IMPLEMENTED 2026-09-07.** `archetype` is gone from the schema, the models, the frontend and
> the tests; `industry_multipliers` and `size_multipliers` are live in `scoring_config`; size is
> derived by `services/sizing.py` and drives cadence selection; query families carry a `runner`.
> Kept for the reasoning, which is why the shape is what it is.

# 09 — Vocabulary Rework: Industry Multipliers and Query Family Runners

Two changes to closed vocabularies, planned together because they share a sequencing constraint and
the same underlying principle: **a vocabulary should be shaped like the thing it describes.**

| | change |
|---|---|
| **A** | `archetype` → `industry` (from the ICP) + `size_band` (derived from headcount) |
| **B** | Query families gain a `runner`, so `enrichment` stops pretending to be a web search |

Both are cheap **right now** and expensive later, for the same reason: neither vocabulary is doing
any work yet. Nothing assigns an archetype, no prompt reads one, and no research agent runs a family.
The Context Builder (Phase 11+) is what makes these load-bearing. Reshaping a vocabulary after agents
are written against it is a different job.

---

## A. Industry multipliers

### Why archetype is the wrong shape

`ARCHETYPES` is six values in one column that are actually two taxonomies:

* **business model** — `saas`, `agency`, `ecommerce`
* **size / stage** — `enterprise`, `smb`, `startup`

A SaaS startup is genuinely both and can only be stored as one, so every such classification is a
lossy coin-flip, and the `saas` and `startup` multipliers can never both apply. Sector — Logistics,
Insurance, Manufacturing — is a *third* axis with nowhere to go, which is what makes the list feel
incomplete. It isn't incomplete; it is three things wearing one name.

The two halves also have different natures. Business model is a judgement about a company. Size is a
fact already sitting on the row as `employee_count`. Only one of those needs a classifier.

### Target shape

**Industry** comes from the ICP. Every industry in the active `org_profile.icp` gets a multiplier row,
defaulting to ×1.00 on every dimension — so the change is inert until deliberately calibrated. Adding
an industry in Org profile makes its row appear; there is no separate list to maintain and no "Add"
button that could disagree with the ICP.

**Size band is derived, never stored as a vocabulary:**

| band | rule |
|---|---|
| `small` | `employee_count < 50` |
| `mid` | 50 ≤ `employee_count` < 1000 |
| `large` | `employee_count >= 1000` |
| `unknown` | `employee_count IS NULL` |

Derived rather than detected because headcount is a fact and an archetype was a guess. No classifier,
no LLM call, no list to deprecate, and `archetype_confidence` stops being a thing that needs
explaining to a rep.

The band names are deliberately **not** the cadence shape names. `enterprise_8_23` and `startup_5_11`
are shapes registered in LGM (invariant 6 — Gen360 never authors a cadence, it selects a registered
shape). Naming our band `large` and mapping it to LGM's `enterprise_8_23` keeps our vocabulary ours
and theirs theirs; naming both `enterprise` would couple them by coincidence.

### Multipliers stack, and renormalise once

```
weights[dim] × industry_factor[dim] × size_factor[dim]   → then renormalise to 100
```

Renormalising once at the end, not after each. The existing reasoning in `scoring.effective_weights`
holds and is the whole point: multipliers change the *balance* between dimensions, never the total.
Two multipliers applied and renormalised twice would silently favour whichever was applied last.

`effective_weights(base, multipliers)` becomes `effective_weights(base, *multiplier_sets)`.

### The join key — the one piece of real work

`account.industry` is uncontrolled free text. It arrives only from CSV import, from whatever column
was called industry, sector or vertical (`csv_import.py:290`). ICP industries are strings someone
typed into a chip field. Nothing normalises either.

So "FinTech" in a spreadsheet and "Fintech" in the ICP do not match, and the failure is **silent** —
the account just quietly scores on base weights and nobody is told why. Harmless today because
nothing reads the field; not harmless the moment it drives scoring.

**Phase 1 — normalise, do not alias.** A single `industry_key`: lowercased, trimmed, internal
whitespace collapsed. Computed on write for `account.industry`, and on read for ICP industries.
`"FinTech"`, `"fintech "` and `"FINTECH"` converge. `"Financial Services"` does **not** become
`fintech`, and should not — that is a mapping decision, not a normalisation.

**Phase 2 — alias table, when there is a second taxonomy to reconcile.** Not before. Today there is
exactly one source of industry strings. When account enrichment lands, Apollo brings its own
(`organization.industry`, e.g. `"information technology & services"`) and aliases stop being
speculative. Building the alias layer now means guessing at mappings for a taxonomy not yet in the
system.

**An account whose industry matches no row scores on base weights and is surfaced, never guessed.**
Same rule as `unknown` archetype today, and the same reasoning as `verification`'s `unavailable` vs
`not_found`: "we have no calibration for this industry" and "this industry is calibrated at ×1.00"
are different facts and must not collapse.

### Orphaned multiplier rows

`org_profile` and `scoring_config` are versioned independently. Remove "Insurance" from the ICP and
its multiplier row is orphaned — and any qualification already scored under Insurance ×1.3 must stay
explainable.

Same treatment as the ICP signal orphans: **shown struck through with a reason, kept until removed
deliberately, never dropped on save.** Deleting silently would change how the whole book scores
without appearing in any diff a person reads.

### Migration — clean removal

The first draft of this plan kept `archetype` and merely stopped writing it, on the deprecate-never-
delete rule. **That rule protects explainability of real history, and there is none here** — every
account and qualification in the database is throwaway test data, confirmed by the owner. Carrying a
dead column and a dead JSONB key forward would leave two vocabularies in the schema for the rest of
the project's life to protect scores nobody will ever ask about.

So: `account.archetype`, `account.archetype_confidence`, `scoring_config.archetype_multipliers` and
the `ARCHETYPES` tuple are **dropped**. No compatibility shim, no deprecation note, no second name
for the same idea. The word does not survive anywhere in the codebase.

This is a deliberate, authorised exception to the project's usual rule, made once, while the cost of
making it is zero. It does not generalise: once real qualifications exist, deprecation is the only
correct move, and `docs/07` should be read as still saying so.

The old multiplier values are not migrated — with nothing real scored under them there is nothing to
preserve. For reference, had they been: `saas` was always an industry, `enterprise` was always a size.

### Files touched

| file | change |
|---|---|
| `alembic/versions/*` | add `industry_multipliers`, `size_multipliers` JSONB to `scoring_config` |
| `app/models/config.py` | the two new columns; deprecation note on `archetype_multipliers` |
| `app/models/account.py` | `industry_key`; deprecation note on `archetype*`; `ARCHETYPES` frozen |
| `app/services/scoring.py` | `effective_weights(base, *sets)`; `compute(industry=, size_band=)` |
| `app/services/sizing.py` *(new)* | `band_for(employee_count)` — four lines and one docstring |
| `app/services/cadence.py` | `SelectionInput.archetype` → `size_band`; `large`/`small` rules |
| `app/services/context.py` | `reasons["_industry"]`, `reasons["_size_band"]` |
| `app/services/promotion.py` | confound on industry **and** size band, not archetype |
| `app/services/csv_import.py` | write `industry_key` alongside `industry` |
| `web/.../research.component.ts` | two tables; rows derived from the ICP; orphan styling |

---

## B. Query family runners

### The problem

`enrichment` sits in a list of web-search families and breaks three of their assumptions:

| | search families | enrichment |
|---|---|---|
| cost | tokens | **credits — real money per call** |
| "returned nothing" | not found in public sources | not in database, **or** no credential, no credit, 429, bad identifiers |
| modelled elsewhere | no | **yes** — `enrichment_config`, the waterfall, `verification.py` |

The middle row is the sharp one. The coverage model has one bucket — *returned nothing = gap*. The
verification pass deliberately has five, because collapsing them was found to be actively harmful:
it is how a reachable contact gets written off, or an unreachable one keeps getting re-charged. A
research sweep reporting "enrichment: coverage gap" when the truth is "no ContactOut credential" is
the wrong instruction to a rep.

The cost row is the practical one: if a plan is "run every family for this account", treating
enrichment as ordinary means a sweep silently spends Apollo credits.

### One axis, not a second flag

The obvious move is a `provider_backed` boolean. Better is to name the axis that is already implicit:

```python
runner: Literal["search", "provider", "manual"] = "search"
```

| value | who runs it | coverage means |
|---|---|---|
| `search` | the research agent | returned nothing → gap |
| `provider` | the enrichment waterfall | status from the verification report |
| `manual` | a rep | never a gap; always available |

`manual` earns the same treatment for the same reason — it is not a search, it must never be
auto-run, and "manual returned nothing" is not a coverage gap. Under a boolean it would have needed
a second flag; under an enum it is just a third value.

This costs **one concept, not two**, and it replaces an assumption that was previously unwritten:
that every family is a web search. `support_only` stays orthogonal — `reviews` is a genuine search
family that may corroborate but never create (§7.1 rule 1).

### Effects

* **Planner** fans out only over `runner == "search"`. Enrichment is invoked through the waterfall it
  already has; manual is never invoked.
* **Coverage strip** reads enrichment's status from the verification report — *"12 of 40 contacts
  verified, 3 unavailable (no ContactOut credential)"* is worth far more than a gap marker.
* **Provenance is unchanged.** `role_change` keeps `produced_by: ['leadership', 'enrichment']`,
  which is true — enrichment really is how a title change gets noticed.

No migration: `QUERY_FAMILIES` is a code-level tuple. `docs/07` Q12 already specifies a `has_runner`
flag for when families become runtime-editable; this is that idea arriving earlier and with a third
state it turned out to need.

### Files touched

| file | change |
|---|---|
| `app/services/query_families.py` | `runner` on the dataclass; set on `enrichment` and `manual` |
| `app/services/research.py` | `build_plan` fans out over search families only |
| `app/schemas/config.py` | `QueryFamilyOut.runner` |
| `web/.../research.component.ts` | show the runner; explain a non-search family differently |

---

## Sequencing

Ordered by dependency, each sized to one session.

1. **Query family runners.** Self-contained, no migration, no dependency on anything below.
2. **Size band derivation + cadence rekey.** Small, and it is what makes archetype removable —
   until cadence keys on something else, archetype cannot be deprecated.
3. **Industry multipliers.** Migration, scoring, UI. The large one.
4. **Deprecate archetype.** Stop writing it; model comments; confirm old qualifications still read.

Doing 3 before 2 would leave cadence with no account-shape input and every account falling through
to `standard_6_15` — silently, since nothing assigns an archetype today anyway and the regression
would look exactly like the status quo.

---

## Decisions still open

1. **Size thresholds.** `<50` small, `≥1000` large is proposed because it preserves the two cadence
   rules that exist today. A business call, not a technical one — the ICP band picker offers finer
   bands (1-50 · 50-100 · 100-200 · 200-500 · 500-1000 · >1000) if scoring wants more resolution than
   cadence does.
2. **Do industry and size multipliers both apply?** Proposed yes, single renormalise. The alternative
   — most specific wins — is defensible and changes the table's shape, so it must be settled before
   the migration.

---

## Noted in passing, not part of this work

`tech_stack` and `news` are search families that **no signal type consumes**, so their Feeds column
reads "nothing yet". They would run, be told they feed nothing, and anything found would have no
signal type to become. The spec expects `news` → `product_launch`/`expansion` and `tech_stack` →
`tech_adoption`; none of those three types exist. Worth resolving before research agents are built,
but it is a signal-type decision rather than a vocabulary one.
