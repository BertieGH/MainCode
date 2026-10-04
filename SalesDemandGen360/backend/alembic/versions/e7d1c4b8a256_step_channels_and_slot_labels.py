"""Which channel each step runs on, and what to call each attribute slot.

A cadence shape recorded the attribute each step's body reads and nothing else.
Two things were missing to make that binding legible to a rep:

* **`step_channels`** — LGM knows step 1 is an email and step 2 a LinkedIn
  message; we only stored the campaign's channel list. Without it the screen
  cannot say why a step has no subject line, and drafting cannot know that
  writing one would be pointless.
* **`slot_labels`** — `customAttribute3` says where copy lands and nothing
  about what it is. LGM lets you name its slots in its own UI, but the API
  exposes no labels anywhere: templates read `{{customAttribute3}}` and lead
  payloads key on `customAttribute1..20`. So the names are derived here, from
  the channel and step the template actually uses them for, and can be edited.

Revision ID: e7d1c4b8a256
Revises: d4b8f2c6a913
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7d1c4b8a256"
down_revision = "d4b8f2c6a913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("step_channels", "slot_labels"):
        op.add_column(
            "cadence_shape",
            sa.Column(
                column,
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.drop_column("cadence_shape", "slot_labels")
    op.drop_column("cadence_shape", "step_channels")
