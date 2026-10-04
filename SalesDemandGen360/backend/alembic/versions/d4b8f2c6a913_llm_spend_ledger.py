"""Every model call, with what it cost in tokens.

"how much it costed?" had no answer. The `run` table carries `input_tokens`
and `output_tokens` columns and **not one of its 54 rows had them filled**,
and the two most expensive stages — strategy and drafting — never created a
run row at all. Spend was invisible, which meant a stage could be misconfigured
into thinking for thirty thousand tokens a call and nothing would show it.

One row per call, written where every stage already funnels through
(`stages._run`). Tokens rather than currency: a price is a fact about a
contract with a vendor, it changes without notice, and a number invented here
would be worse than none. Rates can multiply this later.

Failures are recorded too, and they matter most — a call that burned its whole
budget and raised is the one nobody would otherwise count.

Revision ID: d4b8f2c6a913
Revises: c9e3b7d1a482
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4b8f2c6a913"
down_revision = "c9e3b7d1a482"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_call",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("effort", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        #: Why it failed, in the provider's words. Never a payload — a prompt
        #: carries account research and a prospect's own text.
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # Every table here carries both; the base model writes to it.
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_non_negative"),
    )
    op.create_index("ix_llm_call_created_at", "llm_call", ["created_at"])
    op.create_index("ix_llm_call_scenario", "llm_call", ["scenario", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_scenario", table_name="llm_call")
    op.drop_index("ix_llm_call_created_at", table_name="llm_call")
    op.drop_table("llm_call")
