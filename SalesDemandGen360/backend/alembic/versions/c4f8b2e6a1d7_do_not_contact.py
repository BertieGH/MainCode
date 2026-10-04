"""A person can be marked do-not-contact, with a reason.

Deleting a contact was the alternative, and it is the wrong tool: their signals,
evidence and research coverage cite them, and outreach already sent is history.
Suppression keeps all of it and closes every door that spends money or reaches
the person — enrichment skips them, queues refuse them, research passes over
them, and pre-flight blocks a campaign that still holds one.

The reason is required: "why is this person off limits" is asked months later,
by somebody who was not there.

Revision ID: c4f8b2e6a1d7
Revises: b8e3f1c6d2a4
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c4f8b2e6a1d7"
down_revision = "b8e3f1c6d2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contact",
        sa.Column("do_not_contact", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("contact", sa.Column("do_not_contact_reason", sa.Text(), nullable=True))
    op.add_column(
        "contact", sa.Column("do_not_contact_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "dnc_carries_a_reason", "contact", "NOT do_not_contact OR do_not_contact_reason IS NOT NULL"
    )
    op.create_index(
        "ix_contact_do_not_contact", "contact", ["account_id"],
        postgresql_where=sa.text("do_not_contact"),
    )


def downgrade() -> None:
    op.drop_index("ix_contact_do_not_contact", table_name="contact")
    op.drop_constraint("ck_contact_dnc_carries_a_reason", "contact", type_="check")
    op.drop_column("contact", "do_not_contact_at")
    op.drop_column("contact", "do_not_contact_reason")
    op.drop_column("contact", "do_not_contact")
