"""What came back: every message, reply and status change LGM reports.

Outreach was write-only. We enrolled a lead and never heard anything again —
no sends, no replies, nothing a dashboard could show and nothing a later
campaign could learn from.

`outreach_event` is the record of what happened after enrolment, from either of
the two routes LGM offers and stored identically by both:

* the **inbox webhook** (`POST /flow/inboxWebhooks`), pushed in real time;
* **polling** `/flow/conversations/search` and `/flow/campaigns/:id/statsleads`,
  which is the fallback where no public URL exists and the reconciler for
  anything a webhook dropped.

`external_id` is unique per source so the same message arriving twice — once
pushed, once polled — is one row. The raw payload is kept: it is provider data,
read as data and never as instruction, and the first question about a surprising
event is always "what did they actually send us".

Revision ID: f3a6c9e2b1d8
Revises: e2b7d4a9c3f1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f3a6c9e2b1d8"
down_revision = "e2b7d4a9c3f1"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "outreach_event",
        sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'lgm'")),
        #: `webhook` or `poll` — which route told us. Kept because a gap in one
        #: of them is invisible otherwise.
        sa.Column("received_via", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lgm_lead_id", sa.Text(), nullable=True),
        sa.Column("lgm_campaign_id", sa.Text(), nullable=True),
        sa.Column("conversation_id", sa.Text(), nullable=True),
        sa.Column("preview", sa.Text(), nullable=True),
        sa.Column("contact_id", UUID, nullable=True),
        sa.Column("sequence_id", UUID, nullable=True),
        sa.Column("campaign_id", UUID, nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outreach_event"),
        sa.CheckConstraint(
            "received_via IN ('webhook','poll')", name="ck_outreach_event_received_via_valid"
        ),
        sa.CheckConstraint(
            "direction IS NULL OR direction IN ('sent','received')",
            name="ck_outreach_event_direction_valid",
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"], ondelete="SET NULL",
                                name="fk_outreach_event_contact_id_contact"),
        sa.ForeignKeyConstraint(["sequence_id"], ["outreach_sequence.id"], ondelete="SET NULL",
                                name="fk_outreach_event_sequence_id_outreach_sequence"),
        sa.ForeignKeyConstraint(["campaign_id"], ["outreach_campaign.id"], ondelete="CASCADE",
                                name="fk_outreach_event_campaign_id_outreach_campaign"),
    )
    op.create_index(
        "uq_outreach_event_external", "outreach_event", ["source", "external_id"],
        unique=True, postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index("ix_outreach_event_campaign", "outreach_event", ["campaign_id", "occurred_at"])
    op.create_index("ix_outreach_event_contact", "outreach_event", ["contact_id", "occurred_at"])

    # The two facts a dashboard asks of a sequence, kept on the row so they do
    # not need an aggregate over every event to answer.
    op.add_column(
        "outreach_sequence", sa.Column("first_reply_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "outreach_sequence", sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("outreach_sequence", "last_event_at")
    op.drop_column("outreach_sequence", "first_reply_at")
    op.drop_index("ix_outreach_event_contact", table_name="outreach_event")
    op.drop_index("ix_outreach_event_campaign", table_name="outreach_event")
    op.drop_index("uq_outreach_event_external", table_name="outreach_event")
    op.drop_table("outreach_event")
