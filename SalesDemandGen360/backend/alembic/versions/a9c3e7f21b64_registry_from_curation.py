"""The curated registry: clearer names, four measured sources, a SERP route, a profile.

Four changes, each with a different reason.

**Labels and descriptions, not keys.** The curation sheet proposed renaming
`partnership` to `strategic_partnership_alliance`, `funding` to
`funding_growth_milestone` and so on. `signal.signal_type` carries a composite
foreign key to `signal_type(key, scope)`, so renaming a key that has produced
signals orphans their citations — `mgt_change` has five, and four more types
have one each. Keys are identity. The proposed names are better *display*
names, and the description is what actually reaches the extraction prompt, so
both of those change and the keys stay.

**Four new sources, each with evidence behind it.** Not the full place-shaped
restructure: §66 and §67 measured that narrow place-shaped queries *lose* on
this book — 5.4x the calls for the same evidence — because a 41-person
brokerage has no newsroom to point a query at. These four are the ones that
actually returned something in testing, so they are added *beside* the broad
briefs rather than replacing them.

**`linkedin_serp`, paused.** Gemini's grounding corpus excludes linkedin.com;
that is now confirmed four ways, most recently seven X-Ray queries returning
nothing each (§67). Google's *public* index does carry LinkedIn, so a SERP API
reaches it and nothing else does. The source is registered so the route is
named and its recency rule written down, and paused because no credential
exists. **Fetching linkedin.com directly is never an option.**

**`account.profile`.** A company's description, size, locations and focus are
not a buying signal — nothing about them says *now*. They were proposed as a
`firmographic_baseline` signal type; they belong in account metadata, where the
context builder can read them without an expiry date attached to a fact that
does not expire.

Revision ID: a9c3e7f21b64
Revises: f4c8d2a91e57
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a9c3e7f21b64"
down_revision = "f4c8d2a91e57"
branch_labels = None
depends_on = None

#: key -> (label, description). The description goes into the extraction
#: prompt, so it is written as an instruction rather than a topic.
TYPES = {
    "contact_activity": (
        "Contact content activity",
        "This person published, posted or spoke in public — a byline, a "
        "podcast, a panel, a webinar, a conference talk. The fact is that they "
        "said something and what it was, not that they have a profile "
        "somewhere.",
    ),
    "linkedin_profile": (
        "Profile headline change",
        "This person's public headline or title changed. Reachable only "
        "through a search engine's index of public profiles; never by opening "
        "linkedin.com.",
    ),
    "public_pain_statement": (
        "Public pain statement",
        "This person named a problem in public — on a panel, in an interview, "
        "in trade press or a podcast. Their words, quoted. An opinion about "
        "the industry is not one; a difficulty at their own company is.",
    ),
    "role_change": (
        "Contact role change",
        "This person started, changed or was promoted into a role. The useful "
        "window is short: a new post-holder reviews what they inherited.",
    ),
    "company_pain_statement": (
        "Technology issue or pain statement",
        "The company said, in its own words, that something is difficult — a "
        "manual process, a bottleneck, work that takes days, a system that "
        "cannot do what is needed. Quoted from their site, a case study or an "
        "interview. An inference is not this.",
    ),
    "engineering_scaling": (
        "Engineering team expansion",
        "The company is growing a software engineering team: several related "
        "technical roles open at once, or stated growth of a development "
        "function.",
    ),
    "funding": (
        "Funding or growth milestone",
        "A venture or private-equity round, its size, lead investor and date. "
        "For technology companies; a brokerage does not raise rounds.",
    ),
    "leadership_vendor_review": (
        "Leadership change — technology or operations",
        "A CIO, CTO, VP of IT, COO or head of operations started in the last "
        "ninety days. The conclusion is not that a person changed job; it is "
        "that a review of inherited systems and suppliers usually follows, and "
        "that window is short.",
    ),
    "partnership": (
        "Strategic partnership or alliance",
        "A named partnership, alliance, carrier appointment or a new offering "
        "made with another firm. Both parties named, and the date.",
    ),
    "product_launch": (
        "Product or feature launch",
        "Something the company has made is now available — a product, a "
        "portal, a service line. Announced as shipped, not planned.",
    ),
    "tech_adoption": (
        "Tech stack expansion",
        "A tool, platform or stack choice named publicly — in a job advert, an "
        "engineering post, an integrations page or a stack-detection index.",
    ),
}

#: key, label, description, kind, scopes, status, reason
SOURCES = [
    (
        "press_wire_aggregators",
        "Press wires",
        "Public wire distribution — PR Newswire, Business Wire, GlobeNewswire. "
        'Search the company name with the event\'s own language ("completes '
        'acquisition of", "appoints", "partners with") restricted to those '
        "hosts. Carries a date in the release itself.",
        "search",
        '["company"]',
        "active",
        None,
    ),
    (
        "regulatory_and_filings",
        "Filings and regulators",
        "SEC EDGAR and state insurance regulators. Search the company name "
        'with "acquisition", "merger", "risk factors" or an examination '
        "restricted to sec.gov. Found an acquisition the wires did not.",
        "search",
        '["company"]',
        "active",
        None,
    ),
    (
        "careers_domain_direct",
        "Careers pages and aggregators",
        "The company's own careers path and any standalone careers domain "
        "({company}careers.com), then ZipRecruiter, Indeed and Glassdoor "
        "listings. Read role titles, how long a post has been open, and "
        "repeated re-postings — a role advertised for thirty days is the "
        "signal, stated by the employer.",
        "search",
        '["company"]',
        "active",
        None,
    ),
    (
        "trust_security_portals",
        "Trust and security pages",
        "A company's /security, /trust or /compliance page, where audits and "
        'certifications are stated — SOC 2, ISO 27001, HIPAA, PCI. "We take '
        'security seriously" is marketing; a named standard with a date is an '
        "obligation.",
        "fetch",
        '["company"]',
        "active",
        None,
    ),
    (
        "linkedin_serp",
        "LinkedIn via SERP API",
        "Public LinkedIn content as a search engine indexes it: a company "
        "page, company posts, and a named person's posts and headline. Queried "
        "through a SERP API (SerpApi, Scrapingdog) which reads Google's public "
        "index and returns the URL and snippet. Never by opening linkedin.com."
        "\n\n"
        "DATES. A post carries its own publication date inside its URL: a "
        "LinkedIn activity id is a 64-bit number whose top 41 bits are "
        "milliseconds since the epoch, and services/linkedin.post_date decodes "
        "it to the day without fetching anything. So the recency rule is fully "
        "enforceable for posts - keep only those inside the signal type's "
        "durability window. A company page or a person's profile carries no "
        "date at all, so a headline change can be retrieved but not aged; "
        "treat it as background unless a dated post corroborates it.",
        "search",
        '["company", "contact"]',
        "paused",
        "No SERP API credential is configured. The route is registered so it "
        "is named rather than improvised. It exists because Gemini's grounding "
        "corpus excludes linkedin.com — measured four ways, most recently "
        "seven X-Ray queries returning nothing each, including a real named "
        "person at their real employer. Google's public index does carry "
        "LinkedIn profiles and posts, which is why a SERP API reaches what "
        "grounding cannot. Fetching linkedin.com directly is never an option: "
        "robots.txt forbids it, hiQ ended in a $500,000 judgment and Proxycurl "
        "was sued into shutdown.",
    ),
]


def upgrade() -> None:
    conn = op.get_bind()

    for key, (label, description) in TYPES.items():
        conn.execute(
            sa.text(
                "UPDATE signal_type SET label = :l, description = :d WHERE key = :k"
            ).bindparams(l=label, d=description, k=key)
        )

    for key, label, description, kind, scopes, status, reason in SOURCES:
        conn.execute(
            sa.text(
                """
                INSERT INTO research_source
                    (key, label, description, kind, scopes, support_only,
                     builtin, status, status_reason)
                VALUES (:k, :l, :d, :kind, CAST(:scopes AS jsonb), false, true,
                        :status, :reason)
                ON CONFLICT (key) DO UPDATE
                   SET label = EXCLUDED.label,
                       description = EXCLUDED.description,
                       status_reason = EXCLUDED.status_reason
                """
            ).bindparams(
                k=key, l=label, d=description, kind=kind, scopes=scopes,
                status=status, reason=reason,
            )
        )

    # Firmographics are not a signal: nothing about a company's size or
    # description says *now*. They ride here, where the context builder reads
    # them without an expiry attached to a fact that does not expire.
    op.add_column(
        "account",
        sa.Column("profile", sa.dialects.postgresql.JSONB(astext_type=sa.Text())),
    )


def downgrade() -> None:
    op.drop_column("account", "profile")
    op.execute(
        sa.text("DELETE FROM research_source WHERE key = ANY(:k)").bindparams(
            k=[s[0] for s in SOURCES]
        )
    )
