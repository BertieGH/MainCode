"""Rename the signal type keys to the curated names, and clear what blocked it.

`signal.signal_type` carries a composite foreign key to
`signal_type(key, scope)`, so a key cannot be renamed while signals point at
it. The previous migration therefore changed labels only. The owner has since
confirmed the nine stored signals are test data and asked for the keys
themselves — so they are deleted here, with their evidence links, and the keys
renamed.

**The evidence rows survive.** Invariant 2 is not suspended by a reset: a
passage that was read is still a passage that was read, it is simply no longer
cited. Only the interpretations go, and interpretations are reproducible — the
next extraction run reads the same evidence against the new registry.

`mgt_change` is **deleted rather than renamed**. It was doing two jobs at once
— its own description said "Top Management change or Merger or Acquisition
etc" — which is why three of its five signals were acquisitions. The two
narrower types that replace it already exist.

Everything holding a key is remapped in the same transaction, or the rename
leaves the ICP pointing at names that no longer exist:

* `signal_type.key`
* `icp_profile_version.definition -> signals_that_matter`

Revision ID: b4f8d1a27c95
Revises: a9c3e7f21b64
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "b4f8d1a27c95"
down_revision = "a9c3e7f21b64"
branch_labels = None
depends_on = None

#: old key -> new key
RENAMES = {
    "contact_activity": "contact_content_activity",
    "linkedin_profile": "contact_profile_headline_change",
    "role_change": "contact_role_change",
    "engineering_scaling": "engineering_team_expansion",
    "funding": "funding_growth_milestone",
    "leadership_vendor_review": "leadership_change_executive",
    "partnership": "strategic_partnership_alliance",
    "product_launch": "product_feature_launch",
    "tech_adoption": "tech_stack_expansion",
}

#: Superseded rather than renamed: `leadership_change_executive` and
#: `m_and_a_integration` are the two jobs it was doing badly at once.
RETIRED = ["mgt_change"]


def upgrade() -> None:
    conn = op.get_bind()

    # Interpretations go; the evidence they cited stays.
    conn.execute(sa.text("DELETE FROM signal_evidence"))
    conn.execute(sa.text("DELETE FROM signal"))

    for old, new in RENAMES.items():
        conn.execute(
            sa.text("UPDATE signal_type SET key = :new WHERE key = :old").bindparams(
                new=new, old=old
            )
        )
    conn.execute(
        sa.text("DELETE FROM signal_type WHERE key = ANY(:k)").bindparams(k=RETIRED)
    )

    _remap_icps(conn)


def _remap_icps(conn) -> None:
    """Point every ICP at the new names, and drop the retired one.

    Read, rewritten and written back in Python rather than with a jsonb
    expression: the value is an array of strings and the mapping is a dict, and
    a SQL version of that is a `jsonb_array_elements` subquery nobody will be
    able to read in six months.
    """
    rows = conn.execute(
        sa.text(
            "SELECT id, definition FROM icp_profile_version "
            "WHERE definition ? 'signals_that_matter'"
        )
    ).all()
    for row_id, definition in rows:
        current = definition.get("signals_that_matter") or []
        remapped = [RENAMES.get(k, k) for k in current if k not in RETIRED]
        # dict.fromkeys rather than set(): a rename can collapse two keys into
        # one, and the order a rep put them in is worth keeping.
        definition["signals_that_matter"] = list(dict.fromkeys(remapped))
        conn.execute(
            sa.text(
                "UPDATE icp_profile_version SET definition = CAST(:d AS jsonb) "
                "WHERE id = :i"
            ).bindparams(d=json.dumps(definition), i=row_id)
        )


def downgrade() -> None:
    conn = op.get_bind()
    for old, new in RENAMES.items():
        conn.execute(
            sa.text("UPDATE signal_type SET key = :old WHERE key = :new").bindparams(
                new=new, old=old
            )
        )
    # The deleted signals and the retired type are not restored: a downgrade
    # puts the names back, not the history.
