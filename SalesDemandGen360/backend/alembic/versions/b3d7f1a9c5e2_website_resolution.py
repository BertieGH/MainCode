"""Resolution reads the company's own website, between Apollo and the model.

Every account on the Test Data list ended at "check this" or "not identified",
and nothing said why: eight of twelve domains had no DNS record, three were
registered with no website, one redirected to another company. Apollo held
none of them, and the model may not confirm a domain it was shown — so a real
company on a correct domain Apollo does not hold could never be confirmed.

`website` (free, `services/site_identity.py`) says whether the domain exists,
answers, redirects or is parked, and confirms the company when its homepage on
the row's own domain names it. It runs after `apollo_org`, which still supplies
industry and headcount for the companies it knows, and before `llm_web`, so a
site that settles it spends no model call.

The active enrichment configuration gets a new version with `website` inserted
after `apollo_org` (or first, when Apollo is not in the order) — configuration
is versioned, never edited in place.

Revision ID: b3d7f1a9c5e2
Revises: a8c4e2f6b1d9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b3d7f1a9c5e2"
down_revision = "a8c4e2f6b1d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "enrichment_config", "resolution_order",
        server_default=sa.text("""'["apollo_org", "website", "llm_web"]'::jsonb"""),
    )
    op.execute(
        """
        DO $$
        DECLARE
            cur enrichment_config%ROWTYPE;
            next_order jsonb;
            next_version int;
        BEGIN
            SELECT * INTO cur FROM enrichment_config WHERE is_active;
            IF NOT FOUND OR cur.resolution_order ? 'website' THEN
                RETURN;
            END IF;
            IF cur.resolution_order ? 'apollo_org' THEN
                SELECT jsonb_agg(v ORDER BY pos) INTO next_order FROM (
                    SELECT e.v, e.ord::numeric AS pos
                    FROM jsonb_array_elements(cur.resolution_order) WITH ORDINALITY AS e(v, ord)
                    UNION ALL
                    SELECT '"website"'::jsonb, x.ord::numeric + 0.5
                    FROM jsonb_array_elements_text(cur.resolution_order) WITH ORDINALITY AS x(t, ord)
                    WHERE x.t = 'apollo_org'
                ) AS merged;
            ELSE
                next_order := '["website"]'::jsonb || cur.resolution_order;
            END IF;
            SELECT max(version) + 1 INTO next_version FROM enrichment_config;
            UPDATE enrichment_config SET is_active = false WHERE id = cur.id;
            INSERT INTO enrichment_config
                (provider_order, required_fields, resolution_order, suggestions_per_persona,
                 version, is_active)
            VALUES
                (cur.provider_order, cur.required_fields, next_order,
                 cur.suggestions_per_persona, next_version, true);
        END $$;
        """
    )


def downgrade() -> None:
    op.alter_column(
        "enrichment_config", "resolution_order",
        server_default=sa.text("""'["apollo_org", "llm_web"]'::jsonb"""),
    )
