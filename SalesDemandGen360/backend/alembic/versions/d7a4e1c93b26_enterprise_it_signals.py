"""Seven signal types for the Enterprise IT track.

The registry shipped built for technology companies — funding rounds,
engineering scaling, product launches, tech stack adoption. The book it is
being run against is 57 insurance brokerages, and the measurement says so
plainly: of thirteen active types, **five have ever produced a signal and eight
have produced nothing**, and the eight are the tech-company ones.

These seven are the Enterprise IT equivalents — a non-technology business with
internal IT, legacy systems, compliance load and acquisitions. They are not
speculative for this book. Three of the eight signals already stored are
acquisitions, filed under `mgt_change` and `partnership` because nothing better
existed:

    mgt_change   2021-05-17  Brown & Brown, Inc. acquired substantially all of the assets of…
    mgt_change   2023-04-26  Total Financial & Insurance Services was acquired by Simplicity
    partnership  2023-04-26  Total Financial & Insurance Services was acquired by Simplicity

`mgt_change`'s own description reads "If there is Top Management change or
Merger or Acquisition etc", which is why they landed there. `m_and_a_integration`
narrows that: the acquisition itself, as the integration work it implies.

**Deliberately additive.** The eight unproductive types are *not* deprecated
here. They are retired after a measured run, not before one — a type that has
produced nothing against this book may still be right for the technology track,
and the comparison is cheap to make once but impossible to make afterwards.
That leaves twenty active types in the interim, each interpreted against every
document, which is a real cost and a temporary one.

**Only two carry a `search_instruction`, and they share a group.** The
convention is that an instruction is an exception: every source that gets read
is interpreted against every signal type anyway, so words of its own are worth
it only where a general sweep would reliably miss the fact. Giving all seven one
would add seven searches per account to a change made for efficiency. The two
that qualify are the ones whose evidence lives somewhere nothing currently
looks — `company_site` is a *feed reader* and will never open `/security` — and
they are grouped so they cost one search between them.

Revision ID: d7a4e1c93b26
Revises: c3f7b2e9a815
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d7a4e1c93b26"
down_revision = "c3f7b2e9a815"
branch_labels = None
depends_on = None

GROUP = "enterprise_it_estate"

#: key, label, scope, kind, ttl, durability, weight, produced_by, description,
#: search_instruction
TYPES = [
    (
        "m_and_a_integration",
        "Acquisition or merger",
        "company",
        "event",
        365,
        # An acquisition is permanently true, and permanently useless as an
        # opener once the integration work is done. The TTL ends it as a hook
        # at a year; the durability keeps it readable as background for ten.
        3650,
        2.00,
        ["news", "company_site"],
        "The company acquired another business, was acquired, or merged. Keep "
        "the acquiring and acquired names and the date announced. Brokerage "
        "consolidation is constant, so this is common and still worth having: "
        "it implies systems to merge, duplicate platforms to rationalise and "
        "data to migrate. A rumour or an 'exploring options' report is not "
        "this — the deal must be announced as done or agreed.",
        None,
    ),
    (
        "compliance_security_deadline",
        "Compliance or security deadline",
        "company",
        "event",
        180,
        None,
        1.50,
        ["company_site", "news"],
        "A named audit, certification or regulatory deadline the company has "
        "to meet — SOC 2, HIPAA, ISO 27001, PCI-DSS, a state insurance "
        "department examination, or a published remediation commitment. The "
        "fact is the obligation and its date, not that the company has a "
        "security page. 'We take security seriously' is marketing; 'our SOC 2 "
        "Type II audit completes in Q3' is a deadline.",
        'Look for a trust or security page and any named audit or certification '
        'deadline. Try the company\'s own /security, /trust and /compliance '
        'pages, and search for the company name with "SOC 2", "HIPAA", '
        '"ISO 27001", "PCI-DSS" or "examination". Quote the sentence naming '
        "the standard and, where given, the date.",
    ),
    (
        "tech_debt_modernization",
        "Legacy system or modernisation work",
        "company",
        "theme",
        365,
        None,
        1.50,
        ["tech_stack", "company_site", "news", "hiring"],
        "The company is carrying ageing systems or has said it is replacing "
        "them. For a non-technology business this is usually a named vendor "
        "platform rather than a framework: an agency management system, an "
        "ERP, a claims or policy administration system, an on-premise estate "
        "moving to cloud. Mentions of a migration, a replatform, an "
        "end-of-support date, or hiring for a legacy skill all count.",
        'Search for the company name with the names of ageing business '
        'platforms and modernisation language: "Applied Epic", "Vertafore", '
        '"AMS360", "legacy system", "end of life", "migration", "replatform", '
        '"on-premise", "modernisation". A job advert asking for an old skill '
        "is evidence the system is still running.",
    ),
    (
        "vendor_consolidation",
        "Vendor or IT spend consolidation",
        "company",
        "event",
        270,
        None,
        1.25,
        ["news", "company_site"],
        "A stated intention to reduce the number of suppliers, rationalise IT "
        "spend, review a preferred-vendor list, or cut contractor headcount. "
        "The buying window this opens is a review, not a purchase — it is as "
        "often a reason to be careful as a reason to call.",
        None,
    ),
    (
        "digital_transformation_mandate",
        "Digital transformation mandate",
        "company",
        "theme",
        365,
        None,
        1.25,
        ["news", "leadership", "company_site", "content_activity"],
        "A leadership-level programme to digitise manual work, move to cloud, "
        "or build client or employee portals. It must be stated as an "
        "initiative the company is running, with someone's name or a named "
        "programme behind it. An aspiration in a marketing page is not one.",
        None,
    ),
    (
        "leadership_vendor_review",
        "New technology leader",
        "company",
        "event",
        90,
        None,
        1.50,
        ["leadership", "news"],
        "A technology or operations leader — CIO, CTO, VP of IT, COO, head of "
        "operations — started in the last ninety days. The conclusion is not "
        "that a person changed job; it is that a review of incumbent systems "
        "and suppliers usually follows one, and that window is short. Overlaps "
        "deliberately with `mgt_change`, which is broader: if both fire on the "
        "same evidence, this is the narrower and more actionable reading.",
        None,
    ),
    (
        "hiring_bottleneck",
        "Hiring bottleneck",
        "company",
        "theme",
        90,
        None,
        1.25,
        ["hiring", "job_board", "company_site"],
        "The company cannot fill roles it has been advertising. Evidence is a "
        "role open unusually long, the same role re-posted, or several related "
        "roles open at once. For a non-technology business this is more often "
        "backfilling institutional knowledge after a retirement or a "
        "resignation than scaling a team — and that is the more useful "
        "reading, because the knowledge leaving is the problem.",
        None,
    ),
]


def upgrade() -> None:
    table = sa.table(
        "signal_type",
        sa.column("key", sa.Text),
        sa.column("label", sa.Text),
        sa.column("scope", sa.Text),
        sa.column("kind", sa.Text),
        sa.column("default_ttl_days", sa.Integer),
        sa.column("durability_days", sa.Integer),
        sa.column("weight", sa.Numeric),
        sa.column("produced_by", sa.ARRAY(sa.Text)),
        sa.column("description", sa.Text),
        sa.column("search_instruction", sa.Text),
        sa.column("search_group", sa.Text),
        sa.column("status", sa.Text),
    )
    op.bulk_insert(
        table,
        [
            {
                "key": key,
                "label": label,
                "scope": scope,
                "kind": kind,
                "default_ttl_days": ttl,
                "durability_days": durability,
                "weight": weight,
                "produced_by": sources,
                "description": description,
                "search_instruction": instruction,
                # Grouped so the two that carry words of their own are searched
                # once between them rather than twice.
                "search_group": GROUP if instruction else None,
                "status": "active",
            }
            for (
                key, label, scope, kind, ttl, durability, weight, sources,
                description, instruction,
            ) in TYPES
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM signal_type WHERE key = ANY(:keys)").bindparams(
            keys=[t[0] for t in TYPES]
        )
    )
