"""Drop `org_profile.icp`. There is one ICP concept now, and it is not here.

`c81a3f60d4e7` copied this column into an `icp_profile` named "Default" but
deliberately left it in place, because two things still read it: the research
prompt (`stages._research_prefix`) and the industry-multiplier rows on the
Research screen. Both now read the ICP profiles instead, so the column is the
last remaining second source of truth — and a second source of truth for "who
do we sell to" is exactly what this whole sequence set out to remove.

What survives on `org_profile` is `name` and `description`: who is *selling*.
That has no other home, and every prompt needs it.

Dropped rather than deprecated. The data was copied, not lost, and there is no
history to protect — see `docs/09` on the same decision, and note it does not
generalise past this rework.

Revision ID: d4b28e15a903
Revises: c81a3f60d4e7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d4b28e15a903"
down_revision = "c81a3f60d4e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("org_profile", "icp")


def downgrade() -> None:
    op.add_column(
        "org_profile",
        sa.Column("icp", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    # Put the active profile's definition back, so a downgrade lands on
    # something usable rather than an empty object.
    op.execute(
        """
        UPDATE org_profile o
        SET icp = COALESCE((
            SELECT v.definition
            FROM icp_profile p
            JOIN icp_profile_version v ON v.icp_profile_id = p.id
            WHERE v.is_active AND p.name = 'Default'
            LIMIT 1
        ), '{}'::jsonb)
        WHERE o.is_active
        """
    )
