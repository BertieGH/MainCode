"""A standing description for a person, and the prompts that write both.

`account.profile` arrived in `a9c3e7f21b64`. Its counterpart for a person did
not, and the pair are the same idea: what someone *is*, as against what has
just happened to them.

Both are stored **undated and ungated**. Everything else research keeps is
checked against a durability window; a description of a role has no date to
check — `linkedin.post_date` returns None for a `/in/` URL, which is the
correct answer rather than a gap — and applying a window would discard a
standing fact for being old when it is simply still true.

The two prompts are seeded into `prompt_template` from `instructions.STAGE`,
so an admin can edit them from the Prompts screen like every other stage (§57).
Seeding from the code rather than a frozen copy keeps the shipped baseline and
the stored row identical at birth, which is what "Reset to shipped" depends on.

Revision ID: c8e2a4f71d03
Revises: b4f8d1a27c95
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c8e2a4f71d03"
down_revision = "b4f8d1a27c95"
branch_labels = None
depends_on = None

NEW_STAGES = ("company_profile", "contact_profile")


def upgrade() -> None:
    op.add_column(
        "contact",
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text())),
    )

    from app.services.instructions import STAGE

    conn = op.get_bind()
    for scenario in NEW_STAGES:
        body = STAGE[scenario].strip()
        conn.execute(
            sa.text(
                """
                INSERT INTO prompt_template (scenario, body, version, is_active)
                VALUES (:s, :b, 1, true)
                ON CONFLICT (scenario, version) DO NOTHING
                """
            ).bindparams(s=scenario, b=body)
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM prompt_template WHERE scenario = ANY(:s)").bindparams(
            s=list(NEW_STAGES)
        )
    )
    op.drop_column("contact", "profile")
