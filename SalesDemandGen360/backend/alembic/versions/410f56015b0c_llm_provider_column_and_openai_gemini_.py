"""llm provider column and openai/gemini credentials

Two changes, both about the same thing: which vendor a stage runs on.

`llm_config.model` was already free text, so a Gemini model id could always
have been typed into it. What was missing was the *provider* — and without it
nothing can tell whether `gpt-5.2` means "route to OpenAI" or is a typo, and
the UI cannot offer a scoped list of models. The column is added NOT NULL with
a default of `anthropic`, because every existing row is an Anthropic row and
backfilling anything else would be inventing history.

`integration_credential` gains `openai` and `gemini` as legal providers. The
check is dropped and recreated rather than widened in place — Postgres has no
ALTER CONSTRAINT for a CHECK expression.

The old constraint is found by *querying* `pg_constraint` rather than by name.
Its name on disk is `ck_integration_credential_ck_integration_credential_pro_483c`
— an earlier migration passed an already-prefixed name, the naming convention
prefixed it again, and Postgres truncated the result to 63 characters with a
hash. Hardcoding that string here would make this migration depend on a typo
surviving unchanged in a file nobody is going to read again.

Revision ID: 410f56015b0c
Revises: 5ef3ada57ace
Create Date: 2026-09-06 02:37:58.376934
"""
import sqlalchemy as sa
from alembic import op

revision = '410f56015b0c'
down_revision = '5ef3ada57ace'
branch_labels = None
depends_on = None

#: Model vendors first, then the integrations that hold a key but never run a
#: stage. Kept in one list here because the constraint is one expression.
_PROVIDERS_NEW = "'anthropic','openai','gemini','apollo','contactout','lgm','crm'"
_PROVIDERS_OLD = "'anthropic','apollo','contactout','lgm','crm'"


def _drop_provider_check(table: str) -> None:
    """Drop whichever CHECK on `table` constrains `provider`, by its real name."""
    op.execute(
        f"""
        DO $$
        DECLARE name text;
        BEGIN
            SELECT conname INTO name FROM pg_constraint
             WHERE conrelid = '{table}'::regclass
               AND contype = 'c'
               AND pg_get_constraintdef(oid) LIKE '%provider%';
            IF name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', name);
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    op.add_column(
        "llm_config",
        sa.Column(
            "provider",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'anthropic'"),
        ),
    )
    op.create_check_constraint(
        "provider_valid",
        "llm_config",
        "provider IN ('anthropic','openai','gemini')",
    )

    _drop_provider_check("integration_credential")
    op.create_check_constraint(
        "provider_valid",
        "integration_credential",
        f"provider IN ({_PROVIDERS_NEW})",
    )


def downgrade() -> None:
    # Any credential for a provider the old check does not know has to go, or
    # the recreated constraint cannot be applied. Deleting is correct here and
    # only here: a downgrade is a decision to un-support those providers.
    op.execute(
        "DELETE FROM integration_credential WHERE provider IN ('openai','gemini')"
    )
    _drop_provider_check("integration_credential")
    op.create_check_constraint(
        "provider_valid",
        "integration_credential",
        f"provider IN ({_PROVIDERS_OLD})",
    )

    _drop_provider_check("llm_config")
    op.drop_column("llm_config", "provider")
