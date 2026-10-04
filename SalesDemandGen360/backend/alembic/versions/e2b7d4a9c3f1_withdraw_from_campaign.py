"""Somebody can be taken out of a campaign before anything is sent.

A promoted queue is locked forever — it is the record of what fed the campaign
— so until now there was no way to drop a person short of executing around
them. Withdrawal is that way, and it is not a delete: the sequence stays as
`cancelled` with a reason, its cadence drafts stay attached to it, and the
strategy stays where it is. What ends is their part in this campaign.

The reason is required, for the same argument as do-not-contact: "why did this
person come out?" is asked later, by somebody who was not there.

Revision ID: e2b7d4a9c3f1
Revises: d5c1a8f3e7b2
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e2b7d4a9c3f1"
down_revision = "d5c1a8f3e7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outreach_sequence", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("outreach_sequence", sa.Column("withdraw_reason", sa.Text(), nullable=True))
    # Only withdrawal uses `cancelled` on a sequence: stopping an enrolled one
    # writes `stopped`. So a cancelled row without a reason is a withdrawal
    # nobody explained.
    op.execute(
        "UPDATE outreach_sequence SET withdraw_reason = 'withdrawn before this was recorded' "
        "WHERE status = 'cancelled' AND withdraw_reason IS NULL"
    )
    op.create_check_constraint(
        "withdrawal_carries_a_reason",
        "outreach_sequence",
        "status <> 'cancelled' OR withdraw_reason IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_outreach_sequence_withdrawal_carries_a_reason", "outreach_sequence", type_="check"
    )
    op.drop_column("outreach_sequence", "withdraw_reason")
    op.drop_column("outreach_sequence", "withdrawn_at")
