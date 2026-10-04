"""Which attribute a step's *subject* reads, when it reads one.

`attribute_map` recorded one attribute per step: whichever appeared first in
the template. That is the body. A custom subject line needs its own slot — the
subject is a separate template field in LGM, and it can only show a lead
attribute if it names one.

Nothing recorded that, so execution invented a key: `custom_attribute_1` for
the body and `custom_attribute_1_subject` for the subject. No such field
exists. LGM answers an unknown field with a 404 and stores nothing, so the
whole lead write failed — subject, body and all.

Revision ID: c9e3b7d1a482
Revises: b1c7f4a9d6e2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c9e3b7d1a482"
down_revision = "b1c7f4a9d6e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cadence_shape",
        sa.Column(
            "subject_attribute_map",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cadence_shape", "subject_attribute_map")
