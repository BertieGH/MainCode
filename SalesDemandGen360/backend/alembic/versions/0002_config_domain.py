"""config domain — Domain 1

Nine tables. The interesting parts are not the columns but three guarantees the
database makes so application code does not have to:

* **Exactly one active row** for each versioned singleton, via a partial unique
  index on a constant expression. Two concurrent activations both pass a
  check-then-write in Python; only one survives an index.
* **One active row per scenario** for `llm_config`, the same trick scoped to a key.
* **`deprecated_at` consistent with `status`** on `signal_type`, so a type cannot
  be marked deprecated without recording when.

Revision ID: 0002_config_domain
Revises: 0001_baseline
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_config_domain"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

UUID_PK = dict(
    server_default=sa.text("gen_random_uuid()"), nullable=False
)


def _base_cols() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, **UUID_PK),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    # ---------------------------------------------------------------- org_profile
    op.create_table(
        "org_profile",
        *_base_cols(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "icp", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.UniqueConstraint("version", name="uq_org_profile_version"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_org_profile_single_active "
        "ON org_profile ((true)) WHERE is_active"
    )

    # ------------------------------------------------------------ service_catalog
    op.create_table(
        "service_catalog",
        *_base_cols(),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("positioning_angles", postgresql.JSONB(), nullable=True),
        sa.Column("target_personas", postgresql.JSONB(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.UniqueConstraint("code", name="uq_service_catalog_code"),
    )

    # ----------------------------------------------------------------- proof_point
    op.create_table(
        "proof_point",
        *_base_cols(),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("client_industry", sa.Text(), nullable=True),
        sa.Column("client_size_band", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column(
            "is_approved", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("source", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["service_catalog.id"],
            name="fk_proof_point_service_id_service_catalog",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "kind IN ('case_study','metric','logo','testimonial')",
            name="ck_proof_point_kind_valid",
        ),
    )
    op.create_index("ix_proof_point_service_id", "proof_point", ["service_id"])
    # Only approved proof points are ever selected for a draft, so index that path.
    op.execute(
        "CREATE INDEX ix_proof_point_approved ON proof_point (service_id) WHERE is_approved"
    )

    # -------------------------------------------------------------- writing_sample
    op.create_table(
        "writing_sample",
        *_base_cols(),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.CheckConstraint(
            "channel IN ('linkedin','email')", name="ck_writing_sample_channel_valid"
        ),
    )

    # ----------------------------------------------------------------- sales_rules
    op.create_table(
        "sales_rules",
        *_base_cols(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("priority_threshold", sa.Numeric(5, 2), nullable=False),
        sa.Column("persona_weight_threshold", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "max_concurrent_threads", sa.Integer(), server_default=sa.text("2"), nullable=False
        ),
        sa.Column(
            "thread_start_offset_days", sa.Integer(), server_default=sa.text("3"), nullable=False
        ),
        sa.Column(
            "signal_ttl_days",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "sample_rate", sa.Numeric(4, 3), server_default=sa.text("0.40"), nullable=False
        ),
        sa.Column("no_go", postgresql.JSONB(), nullable=True),
        sa.Column("compliance", postgresql.JSONB(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.UniqueConstraint("version", name="uq_sales_rules_version"),
        sa.CheckConstraint(
            "max_concurrent_threads > 0", name="ck_sales_rules_thread_cap_positive"
        ),
        sa.CheckConstraint(
            "sample_rate > 0 AND sample_rate <= 1", name="ck_sales_rules_sample_rate_range"
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_sales_rules_single_active "
        "ON sales_rules ((true)) WHERE is_active"
    )

    # -------------------------------------------------------------- scoring_config
    op.create_table(
        "scoring_config",
        *_base_cols(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("dimension_weights", postgresql.JSONB(), nullable=False),
        sa.Column(
            "archetype_multipliers",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "persona_role_weights",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("band_cutoffs", postgresql.JSONB(), nullable=False),
        sa.Column(
            "man_view_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.UniqueConstraint("version", name="uq_scoring_config_version"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_scoring_config_single_active "
        "ON scoring_config ((true)) WHERE is_active"
    )

    # ------------------------------------------------------------------ llm_config
    op.create_table(
        "llm_config",
        *_base_cols(),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column(
            "model", sa.Text(), server_default=sa.text("'claude-opus-5'"), nullable=False
        ),
        sa.Column("effort", sa.Text(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "thinking_mode", sa.Text(), server_default=sa.text("'adaptive'"), nullable=False
        ),
        sa.Column("output_contract", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.UniqueConstraint("scenario", "version", name="uq_llm_config_scenario_version"),
        sa.CheckConstraint(
            "effort IN ('low','medium','high','xhigh','max')",
            name="ck_llm_config_effort_valid",
        ),
        sa.CheckConstraint("max_tokens > 0", name="ck_llm_config_max_tokens_positive"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_llm_config_active_per_scenario "
        "ON llm_config (scenario) WHERE is_active"
    )

    # ------------------------------------------------------ integration_credential
    op.create_table(
        "integration_credential",
        *_base_cols(),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("credential_type", sa.Text(), nullable=False),
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("last_four", sa.String(4), nullable=True),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'untested'"), nullable=False
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spend_cap", sa.Numeric(12, 2), nullable=True),
        sa.UniqueConstraint(
            "provider", "credential_type", name="uq_credential_provider_type"
        ),
        sa.CheckConstraint(
            "provider IN ('anthropic','apollo','contactout','lgm','crm')",
            name="ck_integration_credential_provider_valid",
        ),
        sa.CheckConstraint(
            "credential_type IN ('api_key','token','webhook_secret','base_url')",
            name="ck_integration_credential_credential_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('valid','invalid','untested','expired')",
            name="ck_integration_credential_status_valid",
        ),
    )

    # ----------------------------------------------------------------- signal_type
    op.create_table(
        "signal_type",
        *_base_cols(),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("default_ttl_days", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(4, 2), server_default=sa.text("1.00"), nullable=False),
        sa.Column(
            "produced_by",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key", name="uq_signal_type_key"),
        sa.CheckConstraint(
            "scope IN ('company','contact')", name="ck_signal_type_scope_valid"
        ),
        sa.CheckConstraint(
            "status IN ('active','deprecated')", name="ck_signal_type_status_valid"
        ),
        sa.CheckConstraint("default_ttl_days > 0", name="ck_signal_type_ttl_positive"),
        sa.CheckConstraint("weight >= 0", name="ck_signal_type_weight_non_negative"),
        sa.CheckConstraint(
            "(status = 'deprecated') = (deprecated_at IS NOT NULL)",
            name="ck_signal_type_deprecated_at_consistent",
        ),
    )
    # Extraction reads only active types, and does so on every run.
    op.execute(
        "CREATE INDEX ix_signal_type_active ON signal_type (scope) WHERE status = 'active'"
    )


def downgrade() -> None:
    for table in (
        "signal_type",
        "integration_credential",
        "llm_config",
        "scoring_config",
        "sales_rules",
        "writing_sample",
        "proof_point",
        "service_catalog",
        "org_profile",
    ):
        op.drop_table(table)
