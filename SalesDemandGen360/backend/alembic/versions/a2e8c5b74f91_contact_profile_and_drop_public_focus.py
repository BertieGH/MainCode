"""Rename `contact_profile_headline_change` to `contact_profile`, delete `public_focus`.

Two owner decisions on 2026-10-05, both needing a migration because the API
refuses them by design.

**`contact_profile_headline_change` -> `contact_profile`.** The type was defined
as *a headline change*, which is one observation about a profile rather than the
profile itself. What it is wanted for is keeping the contact profile current
from the public LinkedIn index, so the key says that now. `SignalTypePatch`
omits `key` on purpose — it is written into the extraction output schema — so
only a migration can do this. It has produced no signals, so nothing pointed at
the old name.

**`public_focus` deleted outright, with its signals.** It carries two, so
`DELETE /api/config/signal-types/{key}` answers 409 and is right to: the rule
exists so a qualification decided partly on a type stays explainable. The owner
has confirmed these are test data and asked for the type and the data to go.

**The two evidence rows survive.** Invariant 2 is not suspended by a reset, and
`b4f8d1a27c95` already set the precedent: a passage that was read is still a
passage that was read, it is simply no longer cited. Only the interpretations
and their citation links go, and interpretations are reproducible — the next
extraction run reads the same evidence against the current registry.

Everything holding either key is remapped or cleared in the same transaction:

* `signal_type.key`
* `signal_evidence` -> `signal` (the citation links, then the interpretations)
* `icp_profile_version.definition -> signals_that_matter`

Historical ICP versions are rewritten as well, following `b4f8d1a27c95`.

Revision ID: a2e8c5b74f91
Revises: f7b3d9e24a16
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "a2e8c5b74f91"
down_revision = "f7b3d9e24a16"
branch_labels = None
depends_on = None

OLD = "contact_profile_headline_change"
NEW = "contact_profile"
DROPPED = "public_focus"


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("UPDATE signal_type SET key = :new WHERE key = :old").bindparams(
            new=NEW, old=OLD
        )
    )

    # Citation links first, then the interpretations. The `evidence` rows
    # themselves are deliberately untouched.
    conn.execute(
        sa.text(
            "DELETE FROM signal_evidence WHERE signal_id IN "
            "(SELECT id FROM signal WHERE signal_type = :k)"
        ).bindparams(k=DROPPED)
    )
    conn.execute(
        sa.text("DELETE FROM signal WHERE signal_type = :k").bindparams(k=DROPPED)
    )
    conn.execute(
        sa.text("DELETE FROM signal_type WHERE key = :k").bindparams(k=DROPPED)
    )

    _remap_icps(conn, {OLD: NEW}, retired={DROPPED})


def downgrade() -> None:
    """Puts the name back, not the history.

    The deleted type and its two signals are not restored: they were test data
    the owner asked to clear, and a downgrade that resurrected them would make
    the registry disagree with the evidence again.
    """
    _remap_icps(op.get_bind(), {NEW: OLD}, retired=set())
    op.get_bind().execute(
        sa.text("UPDATE signal_type SET key = :old WHERE key = :new").bindparams(
            new=NEW, old=OLD
        )
    )


def _remap_icps(conn, renames: dict[str, str], retired: set[str]) -> None:
    """Point every ICP at the current names and drop the retired ones.

    Read, rewritten and written back in Python rather than with a jsonb
    expression, for the reason `b4f8d1a27c95` gives: the value is an array of
    strings and a SQL version of that is a `jsonb_array_elements` subquery
    nobody will be able to read in six months.
    """
    rows = conn.execute(
        sa.text(
            "SELECT id, definition FROM icp_profile_version "
            "WHERE definition ? 'signals_that_matter'"
        )
    ).all()
    for row_id, definition in rows:
        current = definition.get("signals_that_matter") or []
        remapped = [renames.get(k, k) for k in current if k not in retired]
        if remapped == current:
            continue
        # dict.fromkeys rather than set(): a rename can collapse two keys into
        # one, and the order a rep put them in is worth keeping.
        definition["signals_that_matter"] = list(dict.fromkeys(remapped))
        conn.execute(
            sa.text(
                "UPDATE icp_profile_version SET definition = CAST(:d AS jsonb) "
                "WHERE id = :i"
            ).bindparams(d=json.dumps(definition), i=row_id)
        )
