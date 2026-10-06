"""Stop choosing sources on an ICP. Derive them from its signal types.

An ICP carried two lists that could disagree about the same thing:
`signals_that_matter`, and `sources`. Each signal type already names where its
fact lives, in `produced_by` — so the second list was a *parallel* answer to a
question the first had already settled, and `build_plan` let it win.

Two gates with nothing reconciling them, and both directions failed inside one
week:

* `linkedin_serp` was claimed by all three contact types and **never ran**,
  because the ICP's list omitted it (§77);
* `reviews` **ran anyway** as an "extra", with no signal type claiming it at
  all, after the one type that did was deleted;
* and the sibling list had itself fallen eight types behind the registry (§80).

Sources are now the union of `produced_by` across the signal types the ICP
names, filtered as before by status, kind and scope. One list, one gate, and
both of those failures become unrepresentable rather than merely fixed.

**`sources_excluded` keeps the one thing the old list was good for.** It is a
subtraction, not a parallel answer: `d1a7e9c45b82` pruned `funding` and
`tech_stack` for a book of brokerages — sixteen calls for one passage — while
keeping the types, so they return the day a technology ICP exists. That is cost
control per ICP and it survives; what does not survive is the ability for the
two lists to describe different worlds.

**This changes nothing about what runs today**, which is why it is safe to do
in one step. The active ICP listed seven sources; the derived set is those
seven plus `ats_boards` and `manual`, and both are dropped downstream anyway —
one is paused, the other is a `manual` kind that `build_plan` never schedules.
So `sources_excluded` starts empty and no behaviour moves.

Only the **active** versions are rewritten. A historical version is the record
of what a finished run was told to read, and editing it would make that
unanswerable — the same rule `d8b3f1c62a95` followed.

Revision ID: e4a9c7d13b60
Revises: d8b3f1c62a95
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e4a9c7d13b60"
down_revision = "d8b3f1c62a95"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # `-` drops the key; `||` adds the empty exclusion list beside it. Done in
    # one statement so no version is ever left without either.
    conn.execute(
        sa.text(
            "UPDATE icp_profile_version "
            "   SET definition = (definition - 'sources') "
            "                    || '{\"sources_excluded\": []}'::jsonb "
            " WHERE is_active AND definition ? 'sources'"
        )
    )


def downgrade() -> None:
    """Put back a `sources` list holding what the ICP will now read.

    Reconstructed rather than remembered: the old value is gone, and writing an
    empty list would leave the plan falling back to the union of what the types
    claim — which is this migration's behaviour, not the one being restored.
    """
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE icp_profile_version v "
            "   SET definition = (v.definition - 'sources_excluded') || jsonb_build_object("
            "         'sources',"
            "         coalesce(("
            "           SELECT jsonb_agg(DISTINCT s) FROM signal_type st,"
            "                  unnest(st.produced_by) AS s"
            "            WHERE st.status = 'active'"
            "              AND v.definition->'signals_that_matter' ? st.key"
            "         ), '[]'::jsonb))"
            " WHERE v.is_active AND v.definition ? 'sources_excluded'"
        )
    )
