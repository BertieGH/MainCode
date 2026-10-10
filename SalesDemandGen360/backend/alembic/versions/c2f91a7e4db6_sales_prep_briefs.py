"""sales prep briefs

The table Phase 12 was waiting on. A brief is kept rather than regenerated on
every view, for two reasons that are not caching:

* it costs a model call, and a rep reloading the screen should not spend one;
* a brief is what someone walked into a call holding. When the hypothesis turns
  out wrong, the useful question is what the brief claimed at the time, and
  that answer does not exist if the text is rebuilt from today's signals.

So each row records the generation, not the current truth: the mode it was
written in, the context it was written from, and when. Superseded rows stay —
the same reason evidence is never deleted.

Revision ID: c2f91a7e4db6
Revises: b5d2f08c3a17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c2f91a7e4db6"
down_revision = "b5d2f08c3a17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_prep",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contact.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Which way the brief was written. Decided from the engagement ladder
        # at generation time, so a brief written before a reply is legible as
        # such afterwards instead of looking like it ignored one.
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        # What it was written from, so a later review can tell whether a wrong
        # brief was wrongly reasoned or merely under-informed.
        sa.Column("research_completed_at", sa.DateTime(timezone=True)),
        sa.Column("newest_signal_on", sa.Date()),
        sa.Column("signal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("touches_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("replies_seen", sa.Integer(), nullable=False, server_default="0"),
        # The rep's verdict after the call. Null until they come back, which
        # is also a finding: a brief nobody rated is a brief nobody used.
        sa.Column("hypothesis_verdict", sa.Text()),
        sa.Column("outcome", sa.Text()),
        sa.Column("rep_note", sa.Text()),
        sa.CheckConstraint(
            "mode IN ('pre_engagement', 'engagement_aware')",
            name="ck_sales_prep_mode_valid",
        ),
        sa.CheckConstraint(
            "hypothesis_verdict IS NULL OR hypothesis_verdict IN "
            "('confirmed', 'rejected', 'partly', 'not_discussed')",
            name="ck_sales_prep_verdict_valid",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('meeting_booked', 'follow_up', 'no_need_now', 'not_interested')",
            name="ck_sales_prep_outcome_valid",
        ),
    )
    # The screen asks one question — the newest brief for this contact — and
    # the history is read far less often than it is written past.
    op.create_index(
        "ix_sales_prep_contact_newest",
        "sales_prep",
        ["contact_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_sales_prep_contact_newest", table_name="sales_prep")
    op.drop_table("sales_prep")
