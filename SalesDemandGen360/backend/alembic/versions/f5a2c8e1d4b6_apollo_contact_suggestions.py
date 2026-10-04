"""Find people with Apollo's free search; pay only for the ones a rep accepts.

Enrichment could only look up people already on a list. On the Test Data list
seven of twelve were checked and Apollo recognised none of them, because the
names came from a spreadsheet nobody had verified. Apollo's People API Search
answers the other question — who works there in the roles an ICP wants — for
no credits, and returns enough to choose (first name, an obfuscated surname,
title, whether an email and a location are held) without revealing anything.

* `contact_suggestion` holds what that search proposed, per account and
  persona, until a rep accepts or rejects it. Accepted rows are revealed
  through `people/bulk_match` — one credit per person Apollo has data for.
* `contact.apollo_person_id` records which Apollo person a contact is, so a
  second search recognises them instead of suggesting them again;
  `contact.city` / `contact.country` hold where the reveal placed them.
* `account.company_check` keeps the last company check — what the website and
  Apollo's organisation record said about country and LinkedIn page, and the
  disagreements left for a rep — so a conflict survives a reload and Apollo is
  not paid twice for the same answer.
* `enrichment_config.suggestions_per_persona` caps how many people a search
  proposes per persona per account. Five by default.

Revision ID: f5a2c8e1d4b6
Revises: e2b9d4a7c1f3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f5a2c8e1d4b6"
down_revision = "e2b9d4a7c1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contact", sa.Column("city", sa.Text(), nullable=True))
    op.add_column("contact", sa.Column("country", sa.Text(), nullable=True))
    op.add_column("contact", sa.Column("apollo_person_id", sa.Text(), nullable=True))
    op.create_index("ix_contact_apollo_person", "contact", ["apollo_person_id"])

    op.add_column("account", sa.Column("company_check", postgresql.JSONB(), nullable=True))

    op.add_column(
        "enrichment_config",
        sa.Column(
            "suggestions_per_persona", sa.Integer(), nullable=False,
            server_default=sa.text("5"),
        ),
    )
    op.create_check_constraint(
        "suggestions_per_persona_range", "enrichment_config",
        "suggestions_per_persona BETWEEN 1 AND 25",
    )

    op.create_table(
        "contact_suggestion",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("list_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("apollo_person_id", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name_hint", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("persona", sa.Text(), nullable=True),
        sa.Column("buying_role", sa.Text(), nullable=True),
        sa.Column("has_email", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_location", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_direct_phone", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'proposed'")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_contact_suggestion"),
        sa.ForeignKeyConstraint(["list_id"], ["account_list.id"], ondelete="CASCADE",
                                name="fk_contact_suggestion_list_id_account_list"),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE",
                                name="fk_contact_suggestion_account_id_account"),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"], ondelete="SET NULL",
                                name="fk_contact_suggestion_contact_id_contact"),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'revealed', 'known', 'not_found')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "buying_role IS NULL OR buying_role IN "
            "('economic_buyer', 'technical_buyer', 'champion', 'influencer', 'blocker')",
            name="buying_role_valid",
        ),
        sa.UniqueConstraint("account_id", "apollo_person_id",
                            name="uq_contact_suggestion_account_person"),
    )
    op.create_index("ix_contact_suggestion_list", "contact_suggestion", ["list_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_contact_suggestion_list", table_name="contact_suggestion")
    op.drop_table("contact_suggestion")
    op.drop_constraint("suggestions_per_persona_range", "enrichment_config", type_="check")
    op.drop_column("enrichment_config", "suggestions_per_persona")
    op.drop_column("account", "company_check")
    op.drop_index("ix_contact_apollo_person", table_name="contact")
    op.drop_column("contact", "apollo_person_id")
    op.drop_column("contact", "country")
    op.drop_column("contact", "city")
