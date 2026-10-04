"""How long a fact stays worth knowing, as distinct from how long it stays a hook.

`default_ttl_days` was carrying two jobs. It answers "when does this stop being
a trigger?" — a funding round is not news at 300 days — and it was also, by
omission, the only thing anyone could use to answer "is this still worth
reading at all?". Those are different questions. An acquisition from 2021 is
permanently true and permanently useless as an opener.

The gap showed up as signals born dead. Five of the eight signals held when
this was written were already past `expires_at` on the day they were created,
because `expiry_for` is arithmetic and nothing compared its answer to today:

    mgt_change    observed 2021-04-01  ttl=180  stored 2011 days late
    mgt_change    observed 2021-05-17  ttl=180  stored 1965 days late
    partnership   observed 2023-04-26  ttl=180  stored 1256 days late
    mgt_change    observed 2023-04-26  ttl=180  stored 1256 days late
    mgt_change    observed 2025-01-03  ttl=180  stored  638 days late

`expires_at` already keeps them out of every prompt — `context.live_signals`
filters on it — so they changed no outreach. They cost model calls to extract
and they sat on the screen next to current ones with only a date to tell them
apart.

`durability_days` is the second question's answer. NULL means "three times the
TTL", which is the default the rule was stated as; an explicit value overrides
it for a type whose facts outlive that, without a migration per type.

Revision ID: b5e9a3c7d241
Revises: a2d6f9b4c813
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b5e9a3c7d241"
down_revision = "a2d6f9b4c813"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signal_type", sa.Column("durability_days", sa.Integer(), nullable=True))
    # Durability shorter than the TTL would mean a signal whose own evidence is
    # refused before the signal stops counting — expiry would never be reached
    # because nothing could be stored to reach it.
    op.create_check_constraint(
        "durability_covers_ttl",
        "signal_type",
        "durability_days IS NULL OR durability_days >= default_ttl_days",
    )


def downgrade() -> None:
    op.drop_constraint("durability_covers_ttl", "signal_type", type_="check")
    op.drop_column("signal_type", "durability_days")
