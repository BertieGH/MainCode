"""providers are data not schema

The previous migration widened the provider check from five values to seven.
That was the wrong move one step at a time: every new vendor would be another
migration, and the set of vendors a business buys from is not a fact about the
schema — it changes on a purchase order, not on a deploy.

So the membership check becomes a **format** check. A provider key must look
like a key (`lowercase`, digits, `_`, `-`), and which keys exist is data.

This does not make every provider usable. Storing a credential and being able
to *run* a stage on it are different things, and the second is decided by
whether `app/services/llm.py` has an adapter — checked at call time, with a
named error. The schema's job here is to stop typos and empty strings, not to
be the list.

`console_url` is added so a provider somebody adds can carry where its keys are
issued. Otherwise the next person to look at a credential for a vendor they did
not add has a four-character suffix and no idea where it came from.

Revision ID: 4d6fa083b322
Revises: 410f56015b0c
Create Date: 2026-09-06 02:44:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '4d6fa083b322'
down_revision = '410f56015b0c'
branch_labels = None
depends_on = None

#: Lowercase slug. Deliberately permissive about *which* words, strict about
#: shape — an empty string or " Anthropic " would otherwise become a distinct
#: provider that looks identical in the UI.
_SLUG = r"provider ~ '^[a-z][a-z0-9_-]{1,39}$'"

_PROVIDERS_SEVEN = "'anthropic','openai','gemini','apollo','contactout','lgm','crm'"


def _drop_provider_check(table: str) -> None:
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
    for table in ("integration_credential", "llm_config"):
        _drop_provider_check(table)
        op.create_check_constraint("provider_valid", table, _SLUG)

    op.add_column(
        "integration_credential", sa.Column("console_url", sa.Text(), nullable=True)
    )
    # Backfill only what we can state as fact. A provider somebody adds later
    # supplies its own; guessing a URL for one is worse than leaving it blank.
    op.execute(
        """
        UPDATE integration_credential SET console_url =
          CASE provider
            WHEN 'anthropic'  THEN 'https://console.anthropic.com/settings/keys'
            WHEN 'openai'     THEN 'https://platform.openai.com/api-keys'
            WHEN 'gemini'     THEN 'https://aistudio.google.com/apikey'
          END
        WHERE provider IN ('anthropic','openai','gemini')
        """
    )


def downgrade() -> None:
    op.drop_column("integration_credential", "console_url")

    # Rows for a provider outside the old list cannot survive the narrower
    # check. Deleting them is the honest reading of "un-support these".
    op.execute(
        f"DELETE FROM integration_credential WHERE provider NOT IN ({_PROVIDERS_SEVEN})"
    )
    _drop_provider_check("integration_credential")
    op.create_check_constraint(
        "provider_valid", "integration_credential", f"provider IN ({_PROVIDERS_SEVEN})"
    )

    op.execute(
        "UPDATE llm_config SET provider = 'anthropic' "
        "WHERE provider NOT IN ('anthropic','openai','gemini')"
    )
    _drop_provider_check("llm_config")
    op.create_check_constraint(
        "provider_valid", "llm_config", "provider IN ('anthropic','openai','gemini')"
    )
