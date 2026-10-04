"""Lists become workspaces: an account no list or queue holds goes dormant.

A list refused deletion once anything on it had been researched, because
deleting the list deleted the accounts only it held, and deleting an account
cascades to its evidence — which is never deleted. So a worked list could never
be cleaned up, and the Lists screen only grew.

Lists are now a way of organising accounts to build campaigns from, not what
decides whether an account's data lives:

* An account is **anchored** while it is on at least one list or in at least
  one campaign queue. Deleting a list is always allowed.
* An account that loses its last anchor and has work behind it — research,
  signals, a score, enriched contacts, a company check — goes **dormant**:
  hidden, nothing deleted. `dormant_at` says when, `dormant_reason` why.
* One with nothing behind it (a bad import) is deleted, as before.
* Joining a list again — an import matching its domain, or Add to list —
  clears `dormant_at`, and its research and contacts are there to reuse.

`contact.email_verified_at` dates a verified address, so one verified long ago
can be flagged for re-checking rather than trusted forever; existing verified
addresses take their row's last update. `contact_suggestion.list_id` becomes
nullable so a rejected or revealed suggestion outlives the list it was found on
— a rejection that vanished with its list would be suggested again.

Revision ID: a8c4e2f6b1d9
Revises: f5a2c8e1d4b6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a8c4e2f6b1d9"
down_revision = "f5a2c8e1d4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("account", sa.Column("dormant_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("account", sa.Column("dormant_reason", sa.Text(), nullable=True))
    op.create_index(
        "ix_account_dormant", "account", ["dormant_at"],
        postgresql_where=sa.text("dormant_at IS NOT NULL"),
    )

    op.add_column(
        "contact", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE contact SET email_verified_at = COALESCE(updated_at, created_at) "
        "WHERE email_status = 'verified'"
    )

    op.drop_constraint(
        "fk_contact_suggestion_list_id_account_list", "contact_suggestion", type_="foreignkey"
    )
    op.alter_column("contact_suggestion", "list_id", nullable=True)
    op.create_foreign_key(
        "fk_contact_suggestion_list_id_account_list", "contact_suggestion", "account_list",
        ["list_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_contact_suggestion_list_id_account_list", "contact_suggestion", type_="foreignkey"
    )
    op.execute("DELETE FROM contact_suggestion WHERE list_id IS NULL")
    op.alter_column("contact_suggestion", "list_id", nullable=False)
    op.create_foreign_key(
        "fk_contact_suggestion_list_id_account_list", "contact_suggestion", "account_list",
        ["list_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_column("contact", "email_verified_at")
    op.drop_index("ix_account_dormant", table_name="account")
    op.drop_column("account", "dormant_reason")
    op.drop_column("account", "dormant_at")
