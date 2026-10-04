"""Qualification and strategy belong to the campaign: its service and ICP.

A strategy is the case for approaching one person about one service, for one
kind of buyer. It was keyed to the company alone, so the same person could hold
only one argument however many campaigns reached them, and a company's score
was one number whichever ICP a campaign was built for.

* `campaign_queue` and `outreach_campaign` carry the service and ICP chosen when
  the queue is created (and the ICP version in force then). Promotion copies
  them; every person in the campaign is approached about that service.
* `qualification` gains `campaign_id` and the ICP it was scored against. Rows
  without a campaign are the company-wide scores the lists show.
* `strategy` gains `campaign_id`, `service_id` and `icp_profile_id`.
* `strategy_thread` records the rep's overrides: `chosen_by_rep` (pursued
  although the sales rules left the person out) and `without_live_trigger`
  (built with no live signal to cite). A thread must still cite a trigger
  unless it is marked as built without one.

Existing strategies are left as they are — no migration of old strategies.

Revision ID: a4d9e2b7c1f6
Revises: e7a1c5d3b9f2
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a4d9e2b7c1f6"
down_revision = "e7a1c5d3b9f2"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _targets(table: str) -> None:
    op.add_column(table, sa.Column("service_id", UUID, nullable=True))
    op.add_column(table, sa.Column("icp_profile_id", UUID, nullable=True))
    op.add_column(table, sa.Column("icp_version", sa.Integer(), nullable=True))
    op.create_foreign_key(
        f"fk_{table}_service_id_service_catalog", table, "service_catalog",
        ["service_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        f"fk_{table}_icp_profile_id_icp_profile", table, "icp_profile",
        ["icp_profile_id"], ["id"], ondelete="SET NULL",
    )


def _drop_targets(table: str) -> None:
    op.drop_constraint(f"fk_{table}_icp_profile_id_icp_profile", table, type_="foreignkey")
    op.drop_constraint(f"fk_{table}_service_id_service_catalog", table, type_="foreignkey")
    op.drop_column(table, "icp_version")
    op.drop_column(table, "icp_profile_id")
    op.drop_column(table, "service_id")


def upgrade() -> None:
    _targets("campaign_queue")
    _targets("outreach_campaign")

    op.add_column("qualification", sa.Column("campaign_id", UUID, nullable=True))
    op.add_column("qualification", sa.Column("icp_profile_id", UUID, nullable=True))
    op.add_column("qualification", sa.Column("icp_version", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_qualification_campaign_id_outreach_campaign", "qualification", "outreach_campaign",
        ["campaign_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_qualification_icp_profile_id_icp_profile", "qualification", "icp_profile",
        ["icp_profile_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_qualification_campaign", "qualification", ["campaign_id", "account_id"])

    op.add_column("strategy", sa.Column("campaign_id", UUID, nullable=True))
    op.add_column("strategy", sa.Column("service_id", UUID, nullable=True))
    op.add_column("strategy", sa.Column("icp_profile_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_strategy_campaign_id_outreach_campaign", "strategy", "outreach_campaign",
        ["campaign_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_strategy_service_id_service_catalog", "strategy", "service_catalog",
        ["service_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_strategy_icp_profile_id_icp_profile", "strategy", "icp_profile",
        ["icp_profile_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_strategy_campaign", "strategy", ["campaign_id", "account_id"])

    op.add_column(
        "strategy_thread",
        sa.Column("chosen_by_rep", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "strategy_thread",
        sa.Column("without_live_trigger", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute("ALTER TABLE strategy_thread DROP CONSTRAINT ck_strategy_thread_threads_cite_a_trigger")
    op.execute(
        "ALTER TABLE strategy_thread ADD CONSTRAINT ck_strategy_thread_threads_cite_a_trigger "
        "CHECK (without_live_trigger OR jsonb_array_length(trigger_signal_ids) > 0)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM strategy_thread WHERE jsonb_array_length(trigger_signal_ids) = 0")
    op.execute("ALTER TABLE strategy_thread DROP CONSTRAINT ck_strategy_thread_threads_cite_a_trigger")
    op.execute(
        "ALTER TABLE strategy_thread ADD CONSTRAINT ck_strategy_thread_threads_cite_a_trigger "
        "CHECK (jsonb_array_length(trigger_signal_ids) > 0)"
    )
    op.drop_column("strategy_thread", "without_live_trigger")
    op.drop_column("strategy_thread", "chosen_by_rep")

    op.drop_index("ix_strategy_campaign", table_name="strategy")
    op.drop_constraint("fk_strategy_icp_profile_id_icp_profile", "strategy", type_="foreignkey")
    op.drop_constraint("fk_strategy_service_id_service_catalog", "strategy", type_="foreignkey")
    op.drop_constraint("fk_strategy_campaign_id_outreach_campaign", "strategy", type_="foreignkey")
    op.drop_column("strategy", "icp_profile_id")
    op.drop_column("strategy", "service_id")
    op.drop_column("strategy", "campaign_id")

    op.drop_index("ix_qualification_campaign", table_name="qualification")
    op.drop_constraint("fk_qualification_icp_profile_id_icp_profile", "qualification", type_="foreignkey")
    op.drop_constraint("fk_qualification_campaign_id_outreach_campaign", "qualification", type_="foreignkey")
    op.drop_column("qualification", "icp_version")
    op.drop_column("qualification", "icp_profile_id")
    op.drop_column("qualification", "campaign_id")

    _drop_targets("outreach_campaign")
    _drop_targets("campaign_queue")
