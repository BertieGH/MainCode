# Signal registry — what we look for, where, and for how long

**Working document.** Edit it as the registry is curated; it is the shared view the decisions are
made against. Counts and TTLs below were read from the live database on 2026-10-04 and go stale —
`SELECT key, scope, default_ttl_days, durability_days, produced_by FROM signal_type` is the truth.

**TTL** is how long a fact stays a *hook* — a reason to reach out now. **Life** (durability) is how
long it stays worth *reading* as background. The gap between them is the whole point: an acquisition
is permanently true and useless as an opener within the year. See §54 in the corrections log.

Legend:

| | |
|---|---|
| ✅ | search pattern tested 2026-10-04 and returned evidence |
| ⚠ | source produces little or nothing today |
| ☠ | source is dead — Gemini grounding excludes `linkedin.com` (§64) |
| 🔵 | technology track; pause for the current book |
| 🔴 | recommended for deprecation |
| 🐛 | configuration bug |

---

## Company-scoped

| Signal type | Sources | What to search | TTL | Life | Signals |
|---|---|---|---|---|---|
| `m_and_a_integration` | news, company_site | ✅ `"{company}" ("completes acquisition of" OR "acquires" OR "merger agreement") site:prnewswire.com OR site:businesswire.com OR site:sec.gov` | 365 | 1000 | 0 |
| `compliance_security_deadline` | company_site, news | ✅ `site:{domain}/security OR /trust OR /compliance ("SOC 2" OR "ISO 27001" OR "HIPAA" OR "examination")` | 180 | 540 | 0 |
| `leadership_vendor_review` | leadership, news | `"{company}" ("appoints" OR "names" OR "joins as") ("CIO" OR "CTO" OR "COO" OR "VP of IT" OR "head of operations")` plus the newsroom | 90 | 270 | 0 |
| `tech_debt_modernization` | tech_stack, company_site, news, hiring | `"{company}" ("Applied Epic" OR "Vertafore" OR "AMS360" OR "legacy" OR "end of life" OR "migration" OR "replatform" OR "on-premise")` | 365 | 1095 | 0 |
| `vendor_consolidation` | news, company_site | `"{company}" ("vendor consolidation" OR "cost rationalisation" OR "preferred vendor" OR "contractor reduction" OR "IT spend")` plus wires | 270 | 810 | 0 |
| `digital_transformation_mandate` | news, leadership, company_site, content_activity | `"{company}" ("digital transformation" OR "client portal" OR "automation initiative" OR "cloud migration")` plus the newsroom | 365 | 1095 | 0 |
| `hiring_bottleneck` | hiring, job_board ⚠, company_site | ✅ `site:{domain}/careers OR {company}careers.com OR site:ziprecruiter.com "{company}"` — titles, posting age, re-posts | 90 | 270 | 0 |
| `company_pain_statement` | company_site, news | `"{company}" ("struggling with" OR "manual process" OR "bottleneck" OR "we need to")` — their own words, quoted | 150 | 450 | 0 |
| `delivery_quality_theme` | reviews ⚠, company_site | ✅ `"{company}" site:glassdoor.com OR site:google.com/maps` — **not** G2 or Capterra, which review software products | 180 | 540 | 0 |
| `partnership` | news, company_site | `"{company}" ("carrier appointment" OR "partnership" OR "alliance" OR "now offers")` | 180 | 540 | 1 |
| `public_focus` | company_site, news, linkedin ☠ | `site:{domain}/blog OR /insights OR /resources` — recurring themes | 90 | 270 | 1 |
| `funding` 🔵 | funding | Crunchbase, PitchBook, wires | 300 | 900 | 0 |
| `tech_adoption` 🔵 | tech_stack | `site:builtwith.com "{domain}"`, `site:{domain}/engineering` | 365 | 500 | 1 |
| `engineering_scaling` 🔵 | hiring, job_board ⚠ | ATS boards — overlaps `hiring_bottleneck` | 60 | 180 | 0 |
| `product_launch` 🔵 | news, company_site | `"{company}" ("launches" OR "introduces" OR "now available")` | 120 | 360 | 0 |
| `mgt_change` 🔴 | leadership, company_site, news | Superseded: split into `leadership_vendor_review` and `m_and_a_integration` | 180 | 540 | 5 |

## Contact-scoped

| Signal type | Sources | What to search | TTL | Life | Signals |
|---|---|---|---|---|---|
| `role_change` | leadership, enrichment ⚠ | `"{person}" "{company}" ("joins" OR "appointed" OR "promoted to")`; the provider waterfall is the reliable path | 365 | 500 | 0 |
| `public_pain_statement` | content_activity, linkedin ☠ | `"{person}" "{company}"` across podcasts, panels, trade press, conference bios | 150 | 450 | 0 |
| `contact_activity` | **none** 🐛 | No sources assigned — can only fire if a general sweep happens to turn something up | 90 | 270 | 0 |
| `linkedin_profile` 🔴 | linkedin ☠, manual | No live retrieval route; only a rep typing it in | 90 | 270 | 1 |

---

## What the tables make obvious

**Every contact-scoped signal depends on something broken.** Two lean on `linkedin`, which returns
nothing for anyone; one has no sources at all; `enrichment` has never run. This is not four weak
signal types, it is one missing capability — and it is why "is per-person research in scope?" has to
be answered before any of these four is worth tuning.

**`company_site` is load-bearing and is a feed reader.** Eleven of sixteen company types name it,
and it reads RSS only. The sub-path fallback added in §61 covers `/news` and `/security` when no
feed answers; the ✅ rows work because they route through search instead.

**Four of the patterns above need no new source.** They are `search_instruction` text on the signal
type — configuration, editable in the UI, no deploy.

**Of twenty active types, five have ever produced a signal**, and seven of the fifteen that have not
were added on 2026-10-04 and have not yet run. The meaningful count is eight types that ran and
produced nothing, and they are the technology-track ones.

## Open decisions

1. **Per-person research — in or out?** Decides whether the contact table is four types or one.
   There are three contacts in the database, with truncated surnames.
2. **Deprecate `mgt_change` now, or after a measured run?** It carries five signals, three of which
   are acquisitions that belong to `m_and_a_integration`.
3. **Pause the technology track for this book?** `funding`, `tech_adoption`, `engineering_scaling`,
   `product_launch` — four types interpreted against every document for a book of insurance
   brokerages.
4. **Place-shaped sources** — whether to restructure the twelve sources around *where* rather than
   *what*, and if so how many. The evidence for place-shaping is strong; the case for twelve of them
   is not (see §65).

## Durability values set by hand

Three types carry an explicit `durability_days` rather than the default of three times the TTL:
`m_and_a_integration` (1000), `tech_adoption` (500), `role_change` (500). Note that the **widest**
durability across active types sets the research intake window for *everything* (§54, §60), so
raising one of these widens what research reads for all of them.
