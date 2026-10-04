"""Contact research: evidence and coverage can be about a person.

Research looked at companies only. The ICP's contact signals — a role change,
a public statement of pain — are about people, and finding them means
searching for named people at the account: the list's buyer personas, with a
verified email.

* `evidence.contact_id` — the person a passage is about. Null for company
  evidence. Set null rather than cascaded if the contact goes: evidence is
  never deleted (`docs/01` invariant 2).
* `research_coverage.contact_id` — coverage per person, so the reuse window can
  skip one person's fresh families without skipping another's. The unique key
  becomes (run, family, contact) with NULLS NOT DISTINCT, so a run still has
  exactly one company row per family beside one row per person.
* `run.icp_version_ids` — which ICP versions decided what the run looked for
  and who it looked into. "Why was this person researched?" has to survive a
  later edit to the ICP.

Revision ID: c7e2a9b4d153
Revises: b3e9d7c41a58
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "c7e2a9b4d153"
down_revision = "b3e9d7c41a58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("contact_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_evidence_contact_id_contact", "evidence", "contact",
        ["contact_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "evidence_by_contact", "evidence", ["contact_id"],
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )

    op.add_column(
        "research_coverage", sa.Column("contact_id", UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_research_coverage_contact_id_contact", "research_coverage", "contact",
        ["contact_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("one_row_per_family_per_run", "research_coverage", type_="unique")
    op.execute(
        "ALTER TABLE research_coverage ADD CONSTRAINT one_row_per_family_per_run "
        "UNIQUE NULLS NOT DISTINCT (run_id, family, contact_id)"
    )

    op.add_column("run", sa.Column("icp_version_ids", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("run", "icp_version_ids")
    op.execute("DELETE FROM research_coverage WHERE contact_id IS NOT NULL")
    op.drop_constraint("one_row_per_family_per_run", "research_coverage", type_="unique")
    op.create_unique_constraint(
        "one_row_per_family_per_run", "research_coverage", ["run_id", "family"]
    )
    op.drop_constraint(
        "fk_research_coverage_contact_id_contact", "research_coverage", type_="foreignkey"
    )
    op.drop_column("research_coverage", "contact_id")
    op.drop_index("evidence_by_contact", table_name="evidence")
    op.drop_constraint("fk_evidence_contact_id_contact", "evidence", type_="foreignkey")
    op.drop_column("evidence", "contact_id")
