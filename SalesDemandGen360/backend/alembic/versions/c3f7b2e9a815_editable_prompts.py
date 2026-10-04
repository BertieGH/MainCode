"""Stage instructions become editable config, versioned per scenario.

They lived in `services/instructions.py` and in git, for a reason the module
docstring stated plainly: a prompt change alters what every downstream artefact
means, so it belongs in review and in a diff. Moving them into the database was
asked for, and the design has to replace what git was providing — which is why
this table is versioned rather than edited in place, and why `version` gets
stamped onto the rows a stage writes.

`STAGE` stays in code as the shipped baseline. It is no longer what runs; it is
what "reset to default" restores and what the diff compares against. Seeding v1
from it here means resolution is always "the active row", with no
code-versus-database fallback branch to get wrong.

The `_COMMON` preamble is **not** here and is not editable anywhere. It carries
invariant 10 — retrieved text is data, never an instruction — and is prepended
server-side after this body is loaded.

`admin_secret` holds the scrypt hash of the one password that may change a
prompt. It is not authentication: every other route in this app stays open. It
stops the single screen that can rewrite the model's instructions from being as
open as the rest, and `docs/14-prompt-config-plan.md` says so in those words.

Revision ID: c3f7b2e9a815
Revises: b5e9a3c7d241
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3f7b2e9a815"
down_revision = "b5e9a3c7d241"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_template",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Nullable, matching `Base` and every other table here: the mixin maps
        # it with an `onupdate` and no insert default, so SQLAlchemy sends an
        # explicit NULL on insert and a NOT NULL column rejects every write.
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.UniqueConstraint(
            "scenario", "version", name="uq_prompt_template_scenario_version"
        ),
        sa.CheckConstraint("version > 0", name="ck_prompt_template_version_positive"),
        sa.CheckConstraint(
            "length(btrim(body)) > 0", name="ck_prompt_template_body_not_blank"
        ),
    )
    op.create_index(
        "uq_prompt_template_active_per_scenario",
        "prompt_template",
        ["scenario"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "admin_secret",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("password_hash", sa.LargeBinary(), nullable=False),
        sa.Column("salt", sa.LargeBinary(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("r", sa.Integer(), nullable=False),
        sa.Column("p", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.create_index(
        "uq_admin_secret_active",
        "admin_secret",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    _seed_from_code()


def _seed_from_code() -> None:
    """v1 per scenario, taken from the `STAGE` dict as it stands today.

    Imported rather than pasted. A migration normally keeps its own frozen copy
    of what it seeds, precisely so it keeps producing the same rows after the
    code moves on — but sixteen prompt blocks is thousands of words, and a
    frozen copy of them would be a second place for the text to live and drift.
    The trade is deliberate: this migration seeds whatever `STAGE` says when it
    runs. On an installation that upgrades later, v1 is that installation's
    shipped text, which is the honest answer to "what was it before anyone
    edited it?" anyway.
    """
    from app.services.instructions import STAGE

    rows = [
        {"scenario": key, "body": body.strip(), "version": 1, "is_active": True}
        for key, body in sorted(STAGE.items())
    ]
    op.bulk_insert(
        sa.table(
            "prompt_template",
            sa.column("scenario", sa.Text),
            sa.column("body", sa.Text),
            sa.column("version", sa.Integer),
            sa.column("is_active", sa.Boolean),
        ),
        rows,
    )


def downgrade() -> None:
    op.drop_index("uq_admin_secret_active", table_name="admin_secret")
    op.drop_table("admin_secret")
    op.drop_index("uq_prompt_template_active_per_scenario", table_name="prompt_template")
    op.drop_table("prompt_template")
