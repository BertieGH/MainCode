"""Qualification stays with the company; strategy and cadence drafts belong to outreach.

Qualification is needed before a campaign exists — it decides what is worth
queueing — so it stays on the company and is read per ICP: fit and buyer are
computed in Python for each ICP from the one stored assessment, and the roll-up
is arithmetic. The per-campaign qualification columns added in `a4d9e2b7c1f6`
are dropped; nothing was scored with them.

* `draft.generated_as` accepts `rep_edit`: a rep's own wording is saved as a new
  version, never over the model's.
* Sequences that reached `pending_approval` or `approved` with no touches are
  returned to `draft`. They were approved with nothing to read; their approval
  rows are kept as history, and do not count.

Revision ID: b8e3f1c6d2a4
Revises: a4d9e2b7c1f6
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b8e3f1c6d2a4"
down_revision = "a4d9e2b7c1f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_qualification_campaign", table_name="qualification")
    op.drop_constraint("fk_qualification_icp_profile_id_icp_profile", "qualification", type_="foreignkey")
    op.drop_constraint("fk_qualification_campaign_id_outreach_campaign", "qualification", type_="foreignkey")
    op.drop_column("qualification", "icp_version")
    op.drop_column("qualification", "icp_profile_id")
    op.drop_column("qualification", "campaign_id")

    op.execute("ALTER TABLE draft DROP CONSTRAINT ck_draft_generated_as_valid")
    op.execute(
        "ALTER TABLE draft ADD CONSTRAINT ck_draft_generated_as_valid "
        "CHECK (generated_as IN ('arc','regeneration','rep_edit'))"
    )

    op.execute(
        "UPDATE outreach_sequence s SET status = 'draft' "
        "WHERE s.status IN ('pending_approval','approved') "
        "AND NOT EXISTS (SELECT 1 FROM touch t WHERE t.sequence_id = s.id)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM draft WHERE generated_as = 'rep_edit'")
    op.execute("ALTER TABLE draft DROP CONSTRAINT ck_draft_generated_as_valid")
    op.execute(
        "ALTER TABLE draft ADD CONSTRAINT ck_draft_generated_as_valid "
        "CHECK (generated_as IN ('arc','regeneration'))"
    )
    op.add_column("qualification", sa.Column("campaign_id", sa.dialects.postgresql.UUID(as_uuid=True)))
    op.add_column("qualification", sa.Column("icp_profile_id", sa.dialects.postgresql.UUID(as_uuid=True)))
    op.add_column("qualification", sa.Column("icp_version", sa.Integer()))
    op.create_foreign_key(
        "fk_qualification_campaign_id_outreach_campaign", "qualification", "outreach_campaign",
        ["campaign_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_qualification_icp_profile_id_icp_profile", "qualification", "icp_profile",
        ["icp_profile_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_qualification_campaign", "qualification", ["campaign_id", "account_id"])
