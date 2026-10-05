"""Why a research source is paused, recorded where it is paused.

`linkedin` was paused in §53 on the evidence of sixteen runs and no evidence,
and nothing in the database said so. Three sessions later the obvious next move
looked like "its search instruction must be wrong — rewrite it with `site:`
operators and unpause". The instruction already had those operators, and three
live probes confirmed the index has nothing: a 7,700-employee company returned
as little as a twenty-person brokerage.

That round trip cost three model calls to rediscover a conclusion already
reached. A status with no reason beside it invites exactly that, because the
reason lives in a document nobody is reading while they look at the settings
screen.

Revision ID: e2b9f4c71d38
Revises: d7a4e1c93b26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2b9f4c71d38"
down_revision = "d7a4e1c93b26"
branch_labels = None
depends_on = None

LINKEDIN_REASON = (
    "Measured, and the cause is the retrieval tool rather than the query. "
    "Gemini Grounding with Google Search does not return linkedin.com results "
    "at all: on one Microsoft account the news family returned evidence from "
    "blogs.microsoft.com and thenextweb.com while the linkedin family on the "
    "same account returned nothing, and a probe for Satya Nadella found "
    "nothing either. It is not thin coverage of small companies, and not the "
    "instruction — that already uses site:linkedin.com/company, /posts and "
    "/in operators and is given the account's own LinkedIn URL. LinkedIn's "
    "robots.txt forbids crawling and the grounding corpus respects it. The "
    "only route left is a SERP API (SerpApi, Scrapingdog) reading Google's "
    "public index, which does carry LinkedIn profiles; that needs a credential "
    "and spend. Fetching linkedin.com directly is never an option: hiQ ended "
    "in a $500,000 judgment and Proxycurl was sued into shutdown."
)


def upgrade() -> None:
    op.add_column("research_source", sa.Column("status_reason", sa.Text()))
    op.execute(
        sa.text(
            "UPDATE research_source SET status_reason = :reason WHERE key = 'linkedin'"
        ).bindparams(reason=LINKEDIN_REASON)
    )


def downgrade() -> None:
    op.drop_column("research_source", "status_reason")
