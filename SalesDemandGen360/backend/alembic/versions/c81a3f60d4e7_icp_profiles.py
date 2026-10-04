"""ICPs as first-class, shared, versioned profiles.

Replaces `service_icp` (`b7d4e9a1c260`), which made an ICP a column on a
service — one each, cascade-deleted with it. That shape cannot satisfy the
requirement that an **account list targets an ICP**: a list pointing at "the
ICP belonging to a service" drags the service along with it. See `docs/11`.

Two tables rather than one, and the split is load-bearing. Links must point at
the *identity* of a profile, not at a version of it — otherwise activating a
new version silently orphans every service and list that referenced the old
one. So `icp_profile` is the thing with a name, and `icp_profile_version`
holds the definition that changes.

That is also what makes both halves of the rule work at once: an enrichment run
records the **version** it used, so "why were these contacts chosen?" stays
answerable, while a new list resolves the **active** version at the time it
runs.

Revision ID: c81a3f60d4e7
Revises: b7d4e9a1c260
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "c81a3f60d4e7"
down_revision = "b7d4e9a1c260"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- the wrong shape goes first -------------------------------------
    # Only ever written by an API smoke test; no screen created one and
    # nothing reads it. Dropped rather than deprecated because there is no
    # history here to protect — see `docs/09` on the same decision.
    op.drop_index("ix_service_icp_service", table_name="service_icp")
    op.drop_index("uq_service_icp_single_active", table_name="service_icp")
    op.drop_table("service_icp")

    # --- identity -------------------------------------------------------
    op.create_table(
        "icp_profile",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("name", name="uq_icp_profile_name"),
    )

    # --- the definition, which is what changes --------------------------
    op.create_table(
        "icp_profile_version",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "icp_profile_id", UUID(as_uuid=True),
            sa.ForeignKey("icp_profile.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "definition", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "icp_profile_id", "version", name="uq_icp_profile_version_number"
        ),
    )
    # Exactly one active version per profile, enforced by the index. Two
    # concurrent activations would both pass a check-then-write.
    op.create_index(
        "uq_icp_profile_single_active",
        "icp_profile_version",
        ["icp_profile_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # --- links, all pointing at identity --------------------------------
    op.create_table(
        "service_icp_link",
        sa.Column(
            "service_id", UUID(as_uuid=True),
            sa.ForeignKey("service_catalog.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "icp_profile_id", UUID(as_uuid=True),
            sa.ForeignKey("icp_profile.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "account_list_service",
        sa.Column(
            "list_id", UUID(as_uuid=True),
            sa.ForeignKey("account_list.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column(
            "service_id", UUID(as_uuid=True),
            sa.ForeignKey("service_catalog.id", ondelete="CASCADE"), primary_key=True,
        ),
    )
    op.create_table(
        "account_list_icp",
        sa.Column(
            "list_id", UUID(as_uuid=True),
            sa.ForeignKey("account_list.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column(
            "icp_profile_id", UUID(as_uuid=True),
            sa.ForeignKey("icp_profile.id", ondelete="CASCADE"), primary_key=True,
        ),
    )
    op.create_index("ix_service_icp_link_icp", "service_icp_link", ["icp_profile_id"])
    op.create_index("ix_account_list_icp_icp", "account_list_icp", ["icp_profile_id"])

    # --- carry the existing ICP across ----------------------------------
    # `org_profile.icp` was one profile pretending to be the only one. It
    # becomes a real profile named "Default", active at version 1, linked to
    # every active service — which satisfies "an ICP has >= 1 service" and
    # "a service has >= 1 ICP" for everything that already exists.
    #
    # The column itself stays for now: `scoring_config.industry_multipliers`
    # still reads its industries, and moving that source is a separate change
    # with its own tests. Dropping it here would break scoring silently.
    op.execute(
        """
        INSERT INTO icp_profile (name, description)
        SELECT 'Default', 'Carried over from the original org-level ICP.'
        WHERE EXISTS (SELECT 1 FROM org_profile WHERE is_active)
        """
    )
    op.execute(
        """
        INSERT INTO icp_profile_version (icp_profile_id, definition, version, is_active)
        SELECT p.id, COALESCE(o.icp, '{}'::jsonb), 1, true
        FROM icp_profile p
        CROSS JOIN (SELECT icp FROM org_profile WHERE is_active LIMIT 1) o
        WHERE p.name = 'Default'
        """
    )
    op.execute(
        """
        INSERT INTO service_icp_link (service_id, icp_profile_id)
        SELECT s.id, p.id
        FROM service_catalog s
        CROSS JOIN icp_profile p
        WHERE p.name = 'Default'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_account_list_icp_icp", table_name="account_list_icp")
    op.drop_index("ix_service_icp_link_icp", table_name="service_icp_link")
    op.drop_table("account_list_icp")
    op.drop_table("account_list_service")
    op.drop_table("service_icp_link")
    op.drop_index("uq_icp_profile_single_active", table_name="icp_profile_version")
    op.drop_table("icp_profile_version")
    op.drop_table("icp_profile")

    op.create_table(
        "service_icp",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "service_id", UUID(as_uuid=True),
            sa.ForeignKey("service_catalog.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("icp", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("service_id", "version", name="uq_service_icp_version"),
    )
    op.create_index(
        "uq_service_icp_single_active", "service_icp", ["service_id"],
        unique=True, postgresql_where=sa.text("is_active"),
    )
    op.create_index("ix_service_icp_service", "service_icp", ["service_id"])
