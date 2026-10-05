"""An ICP says which buyer it is for, and the argument follows from it.

Two tracks, and only two. `tech_company` is an ISV, a SaaS business or an IT
product company — software is what it sells. `enterprise` is everything else:
a non-technology business running internal IT. Insurance brokerages, the whole
of the current book, are inside `enterprise` rather than beside it.

The track rides in the ICP's `definition`, next to `sources` and
`signals_that_matter`, because it is the same kind of statement — what this list
is for — and because `load_prefix` already puts the definition in the cached
prefix. It therefore reaches `strategy_synthesis` and `outreach_drafting`
without any new plumbing.

Two prompts change with it, so the register follows the buyer: a CIO measured on
nothing going wrong does not read the argument written for a CTO measured on
what ships.

**Both halves of each prompt are updated.** `instructions.STAGE` is the shipped
baseline that "Reset to shipped" restores, and `prompt_template` is what
actually runs (§57). Changing only the table would leave Reset quietly
restoring the older text months later; changing only the code would leave the
new words unused. The new version is written here from the code, so the two
cannot disagree.

Revision ID: f4c8d2a91e57
Revises: e2b9f4c71d38
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4c8d2a91e57"
down_revision = "e2b9f4c71d38"
branch_labels = None
depends_on = None

#: The two tracks. Validated in the schema layer rather than by a CHECK, since
#: the definition is a JSON document and not a column.
TRACKS = ("enterprise", "tech_company")

RETRACKED = ("strategy_synthesis", "outreach_drafting")


def upgrade() -> None:
    # The existing profile is the brokerage book: non-technology businesses
    # running internal IT.
    op.execute(
        sa.text(
            """
            UPDATE icp_profile_version
            SET definition = definition || '{"track": "enterprise"}'::jsonb
            WHERE is_active AND NOT (definition ? 'track')
            """
        )
    )
    _bump_prompts()


def _bump_prompts() -> None:
    """A new active version of each retracked prompt, taken from the code.

    Imported rather than pasted, for the same reason the seeding migration
    imports it: the alternative is a second copy of several hundred words that
    drifts from the first. An installation upgrading later gets whatever its
    `STAGE` says, which is the text that installation actually ships.

    Skips a scenario whose live body has been edited away from the previous
    shipped text — someone changed it deliberately, and overwriting that from a
    migration would be the one way this feature could destroy a rep's work.
    """
    from app.services.instructions import STAGE

    conn = op.get_bind()
    for scenario in RETRACKED:
        shipped = STAGE[scenario].strip()
        row = conn.execute(
            sa.text(
                "SELECT id, body, version FROM prompt_template "
                "WHERE scenario = :s AND is_active"
            ).bindparams(s=scenario)
        ).first()
        if row is None:
            continue
        if row.body.strip() == shipped:
            continue
        # Has it been edited by hand, or is it simply the older shipped text?
        # Only v1 can be assumed untouched; beyond that, leave it alone.
        if row.version != 1:
            continue
        conn.execute(
            sa.text(
                "UPDATE prompt_template SET is_active = false WHERE id = :id"
            ).bindparams(id=row.id)
        )
        conn.execute(
            sa.text(
                "INSERT INTO prompt_template "
                "(scenario, body, note, version, is_active) "
                "VALUES (:s, :b, :n, :v, true)"
            ).bindparams(
                s=scenario,
                b=shipped,
                n="buyer track: enterprise IT versus technology company",
                v=row.version + 1,
            )
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE icp_profile_version SET definition = definition - 'track' "
            "WHERE is_active"
        )
    )
