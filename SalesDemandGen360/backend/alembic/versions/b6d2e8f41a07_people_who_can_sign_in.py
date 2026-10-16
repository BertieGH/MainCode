"""people who can sign in

The installation had no notion of a person: every route open, one password on
the prompt editor. This adds the two tables login needs (`docs/17`).

**`organization`** holds one row, CGVAK, seeded here. It exists so a later
split costs a column; nothing else points at it yet, by decision.

**`app_user`**, not `user` — reserved in Postgres. Email is unique on
`lower(email)`, so the same address typed with a capital is the same person.
Users are never deleted, so nothing here cascades.

No user is seeded. The first admin is made with `scripts/create_admin.py`,
which keeps the password out of a migration file and out of git.

Revision ID: b6d2e8f41a07
Revises: f4c7e0a92b31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b6d2e8f41a07"
down_revision = "f4c7e0a92b31"
branch_labels = None
depends_on = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "organization",
        *_base_columns(),
        sa.Column("name", sa.Text(), nullable=False),
    )
    op.execute("INSERT INTO organization (name) VALUES ('CGVAK')")

    op.create_table(
        "app_user",
        *_base_columns(),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization.id", name="fk_app_user_organization_id_organization"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("password_hash", sa.LargeBinary(), nullable=False),
        sa.Column("salt", sa.LargeBinary(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("r", sa.Integer(), nullable=False),
        sa.Column("p", sa.Integer(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", name="fk_app_user_created_by_id_app_user"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'aiops', 'marketing', 'demandgen')", name="ck_app_user_role_valid"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'deactivated')", name="ck_app_user_status_valid"
        ),
    )
    op.execute("CREATE UNIQUE INDEX uq_app_user_email_lower ON app_user (lower(email))")


def downgrade() -> None:
    op.drop_table("app_user")
    op.drop_table("organization")
