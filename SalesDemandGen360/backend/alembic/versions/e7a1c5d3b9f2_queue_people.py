"""Campaigns are built from people: a queue holds contacts, and a sequence names its person.

A queue held companies only, and promotion turned each company's pursued
strategy threads into sequences — so there was no way to choose *who* a
campaign reaches, and nobody could be promoted until a strategy existed for
their company. Outreach is to people; enrichment and research stay company-wide.

* `campaign_queue_contact` — people chosen for a queue, with the company they
  belong to and the list they were picked from (a provenance stamp). A person
  may join when their company passes the queue rule and they are reachable: a
  verified email or a LinkedIn profile.
* `outreach_sequence.contact_id` — the person a sequence is for, set for every
  sequence (existing ones take it from their strategy thread). `thread_id`
  becomes optional: a person promoted before a strategy exists gets a sequence
  now, and the strategy is linked when it is built. A sequence must name one or
  the other, and pre-flight refuses to execute any sequence without a strategy.

Whole companies can still be queued alongside people.

Revision ID: e7a1c5d3b9f2
Revises: c9e4a2d7f1b3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7a1c5d3b9f2"
down_revision = "c9e4a2d7f1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_queue_contact",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_list_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("added_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_queue_contact"),
        sa.ForeignKeyConstraint(["queue_id"], ["campaign_queue.id"], ondelete="CASCADE",
                                name="fk_campaign_queue_contact_queue_id_campaign_queue"),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"], ondelete="CASCADE",
                                name="fk_campaign_queue_contact_contact_id_contact"),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE",
                                name="fk_campaign_queue_contact_account_id_account"),
        sa.ForeignKeyConstraint(["source_list_id"], ["account_list.id"], ondelete="SET NULL",
                                name="fk_campaign_queue_contact_source_list_id_account_list"),
        sa.UniqueConstraint("queue_id", "contact_id", name="uq_campaign_queue_contact_queue_contact"),
    )
    op.create_index("ix_campaign_queue_contact_queue", "campaign_queue_contact", ["queue_id"])
    op.create_index("ix_campaign_queue_contact_account", "campaign_queue_contact", ["account_id"])

    op.add_column(
        "outreach_sequence",
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_outreach_sequence_contact_id_contact", "outreach_sequence", "contact",
        ["contact_id"], ["id"],
    )
    op.execute(
        "UPDATE outreach_sequence s SET contact_id = t.contact_id "
        "FROM strategy_thread t WHERE s.thread_id = t.id AND s.contact_id IS NULL"
    )
    op.alter_column("outreach_sequence", "thread_id", nullable=True)
    op.create_check_constraint(
        "names_a_person", "outreach_sequence", "thread_id IS NOT NULL OR contact_id IS NOT NULL"
    )
    op.create_index("ix_outreach_sequence_contact", "outreach_sequence", ["contact_id"])


def downgrade() -> None:
    op.drop_index("ix_outreach_sequence_contact", table_name="outreach_sequence")
    op.drop_constraint("names_a_person", "outreach_sequence", type_="check")
    op.execute("DELETE FROM outreach_sequence WHERE thread_id IS NULL")
    op.alter_column("outreach_sequence", "thread_id", nullable=False)
    op.drop_constraint("fk_outreach_sequence_contact_id_contact", "outreach_sequence", type_="foreignkey")
    op.drop_column("outreach_sequence", "contact_id")
    op.drop_index("ix_campaign_queue_contact_account", table_name="campaign_queue_contact")
    op.drop_index("ix_campaign_queue_contact_queue", table_name="campaign_queue_contact")
    op.drop_table("campaign_queue_contact")
