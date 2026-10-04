"""People we paid Apollo for are saved as contacts in the Apollo account.

Apollo: "A contact is a person saved to Apollo, which means their data becomes
permanently accessible to your organization." A person enriched through the API
and never saved is, to Apollo, a new request next time — and charged again.

So a revealed or enriched person is saved (`contacts/bulk_create`, free,
de-duplicated, labelled "Gen360"), and before any paid lookup the account's
saved contacts are searched (`contacts/search`, free). These columns record
which Apollo contact a contact is, and when it was saved.

Revision ID: c9e4a2d7f1b3
Revises: b3d7f1a9c5e2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9e4a2d7f1b3"
down_revision = "b3d7f1a9c5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contact", sa.Column("apollo_contact_id", sa.Text(), nullable=True))
    op.add_column(
        "contact", sa.Column("apollo_saved_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("contact", "apollo_saved_at")
    op.drop_column("contact", "apollo_contact_id")
