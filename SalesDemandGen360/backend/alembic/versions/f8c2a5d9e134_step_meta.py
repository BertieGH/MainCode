"""Where each step sits in the LGM campaign, and what it is called there.

`/campaigns/:id/messages` returns templates and an `order` among templates.
`/campaigns/:id/steps` — undocumented — returns the campaign's actual steps,
and the two disagree in ways that matter:

* the first account this was read against had its two message templates at
  **positions 4 and 5**, so three earlier steps (a profile visit, a connection
  request, a wait) carry nothing of ours and `/messages` cannot see them at
  all. "Step 1" in Gen360 was never step 1 of the campaign.
* the names tell you what a step is *for*: "Not Accepted - Email" and
  "Accepted - DM" are not step one and step two of a sequence — they are two
  branches of one, and copy that reads as a follow-up in the second is wrong
  whenever the first never sent.

Revision ID: f8c2a5d9e134
Revises: e7d1c4b8a256
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f8c2a5d9e134"
down_revision = "e7d1c4b8a256"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cadence_shape",
        sa.Column(
            "step_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cadence_shape", "step_meta")
