"""Put every LinkedIn query in Google X-Ray form, and retire the old route.

Two LinkedIn sources existed: `linkedin`, which asked Gemini grounding to find
LinkedIn content, and `linkedin_serp`, registered in `a9c3e7f21b64` as the
route that reads Google's public index through a SERP API. `linkedin` was
measured dead in §64 — **Gemini grounding excludes `linkedin.com` for
everyone**, confirmed four ways, including a Microsoft/Nadella control that
returned nothing while a `news` search on the same account returned two
passages. Sixteen attempts, no evidence, ever.

So `linkedin` is **deprecated here, not paused**: paused reads as "we may turn
this back on", and there is nothing to turn back on. It is also removed from
every ICP's accepted sources, because a deprecated key sitting in that list is
a dangling reference of exactly the kind `b4f8d1a27c95` cleaned up.

The queries themselves move to **X-Ray form** — the operator that names the
path rather than the site:

    site:linkedin.com/in     a person's public profile
    site:linkedin.com/posts  a dated post

Narrower than `site:linkedin.com`, which also matches jobs, learning, pulse and
company pages and buries the two things worth having. Written into the source
description and into the one signal type carrying its own instruction, so the
form is in the registry rather than in somebody's memory.

**This still fetches nothing today, and the reason is worth stating plainly.**
X-Ray is a query *form*, not a retrieval route. Through Gemini grounding these
queries return what every other LinkedIn query returns — nothing — because the
exclusion is on the domain, not on the phrasing. They work through a SERP API
(SerpApi, Scrapingdog) reading Google's index, and **no SERP credential is
configured**. What this migration buys is that the day a credential exists, the
queries are already right. Nothing here opens `linkedin.com`, which remains
forbidden: robots.txt disallows it, hiQ ended in a $500,000 judgment, and
Proxycurl was sued into shutdown.

Revision ID: b6d4a8f32e07
Revises: a2e8c5b74f91
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "b6d4a8f32e07"
down_revision = "a2e8c5b74f91"
branch_labels = None
depends_on = None

SERP_DESCRIPTION = (
    "Public LinkedIn content as Google has indexed it, reached with X-Ray path "
    "operators: site:linkedin.com/in for a person's profile and "
    "site:linkedin.com/posts for a dated post. Pair either with the quoted "
    "company name, and for a person the quoted full name. Read through a SERP "
    "API (SerpApi, Scrapingdog) which returns the URL and snippet from "
    "Google's index. Never by opening linkedin.com.\n\n"
    "DATES. A post carries its own date inside its URL: a LinkedIn activity id "
    "is a 64-bit number whose top 41 bits are milliseconds since the epoch, and "
    "services/linkedin.post_date decodes it to the day without fetching "
    "anything. So recency is fully enforceable for /posts - keep only those "
    "inside the signal type's durability window. A /in profile carries no date "
    "at all, so treat it as background unless a dated post corroborates it."
)

#: Deprecated, not paused. Nothing to turn back on.
DEAD_REASON = (
    "Deprecated: Gemini grounding excludes linkedin.com for every account, not "
    "just ours (measured four ways, §64 - 16 attempts, no evidence). Superseded "
    "by linkedin_serp, which reads Google's index through a SERP API in X-Ray "
    "form. Kept as a row because coverage history points at this key."
)

XRAY_INSTRUCTION = (
    "Find what this person has published in public and when. Query Google in "
    'X-Ray form: site:linkedin.com/posts "{person}" "{company}" for their own '
    'posts, and site:linkedin.com/in "{person}" "{company}" for the profile '
    "behind them. Widen past LinkedIn with the quoted name against industry "
    "press, podcasts, panel listings and conference bios. Two readings both "
    "count: posts about their own company or what it sells, and where their "
    "professional attention sits more generally - AI, automation, data, cloud, "
    "security, a platform migration, a trend they keep returning to. Keep the "
    "date for every post; a post whose date cannot be established is background, "
    "not a trigger. Their own words, not a bare reshare."
)


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            "UPDATE research_source SET description = :d, status = 'active', "
            "status_reason = NULL, updated_at = now() WHERE key = 'linkedin_serp'"
        ).bindparams(d=SERP_DESCRIPTION)
    )
    conn.execute(
        sa.text(
            "UPDATE research_source SET status = 'deprecated', status_reason = :r, "
            "updated_at = now() WHERE key = 'linkedin'"
        ).bindparams(r=DEAD_REASON)
    )
    conn.execute(
        sa.text(
            "UPDATE signal_type SET search_instruction = :i, updated_at = now() "
            "WHERE key = 'contact_content_activity'"
        ).bindparams(i=XRAY_INSTRUCTION)
    )

    # A type may still name the dead source in `produced_by`; drop it there too,
    # or the registry claims a route that cannot run.
    # `produced_by` is a `text[]`, not jsonb — `array_remove` is the whole job.
    conn.execute(
        sa.text(
            "UPDATE signal_type SET produced_by = array_remove(produced_by, 'linkedin'), "
            "updated_at = now() WHERE 'linkedin' = ANY(produced_by)"
        )
    )

    _icp_sources(conn, drop="linkedin", add="linkedin_serp")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE research_source SET status = 'paused', updated_at = now() "
            "WHERE key = 'linkedin'"
        )
    )
    # The descriptions and the instruction are not restored: a downgrade undoes
    # the status change, not the writing.
    _icp_sources(conn, drop="linkedin_serp", add="linkedin")


def _icp_sources(conn, *, drop: str, add: str) -> None:
    """Swap one key for another in every ICP's accepted sources.

    Edited in place across all versions rather than activating a new one,
    following `d1a7e9c45b82`: this is a registry correction, not somebody
    changing their mind about what to read. A version left naming a deprecated
    source would report a permanent coverage gap for a route that cannot run.
    """
    rows = conn.execute(
        sa.text("SELECT id, definition FROM icp_profile_version WHERE definition ? 'sources'")
    ).all()
    for row_id, definition in rows:
        current = definition.get("sources") or []
        if not isinstance(current, list):
            continue
        kept = [k for k in current if k != drop]
        if add not in kept:
            kept.append(add)
        if kept == current:
            continue
        definition["sources"] = kept
        conn.execute(
            sa.text(
                "UPDATE icp_profile_version SET definition = CAST(:d AS jsonb) WHERE id = :i"
            ).bindparams(d=json.dumps(definition), i=row_id)
        )
