"""A service says who signs off; the ICP says who to reach.

`service_catalog.target_personas` held two vocabularies in one column — job
titles on one service (`CEO, CTO, CIO, IT head`), buying roles on another
(`technical_buyer, champion`) — and fed persona matching alongside the ICP, so
an ICP could never narrow what a service had already widened.

It becomes `economic_buyer`: one line of text saying who signs off for this
service, broadly. The people to reach are the ICP's buyer personas, and
nothing else. Existing values are carried across as text, not discarded, so
the next edit starts from what was there.

Revision ID: a8d3f5c27e19
Revises: e5b1c08d7a42
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a8d3f5c27e19"
down_revision = "e5b1c08d7a42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_catalog", sa.Column("economic_buyer", sa.Text(), nullable=True)
    )
    op.execute(
        """
        UPDATE service_catalog
           SET economic_buyer = (
                 SELECT string_agg(value, ', ')
                   FROM jsonb_array_elements_text(target_personas) AS value
               )
         WHERE jsonb_typeof(target_personas) = 'array'
        """
    )
    op.drop_column("service_catalog", "target_personas")


def downgrade() -> None:
    op.add_column(
        "service_catalog", sa.Column("target_personas", JSONB(), nullable=True)
    )
    op.execute(
        """
        UPDATE service_catalog
           SET target_personas = to_jsonb(regexp_split_to_array(economic_buyer, '\\s*,\\s*'))
         WHERE economic_buyer IS NOT NULL
        """
    )
    op.drop_column("service_catalog", "economic_buyer")
