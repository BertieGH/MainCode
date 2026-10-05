"""Rename `product_feature_launch` back to `product_launch`.

The type was redescribed on 2026-10-05 to mean a launch of whatever the company
actually sells — a scheme, programme, cover or service line for a broker; a
product or a named feature for an ISV. "Product **or feature** launch" was the
original reading, it reads as software, and a book of 57 insurance brokerages
had nowhere to file a launch that was not code. The description carries that
change; the key still said `feature`.

`SignalTypePatch` omits `key` on purpose — it is written into the extraction
output schema — so the API cannot do this and a migration must.

**Safe to rename rather than recreate:** `signal.signal_type` carries a
composite foreign key to `signal_type(key, scope)`, and this type has produced
no signals, so nothing points at the old name. Nothing is deleted here.

Everything else holding the key is remapped in the same transaction, or the
rename leaves the ICP naming something that does not exist:

* `signal_type.key`
* `icp_profile_version.definition -> signals_that_matter`

Historical ICP versions are rewritten too, following `b4f8d1a27c95`. A rename
is the same concept under a new name, so a version that recorded "this type
mattered" still records that; leaving the old string behind would make it read
as a type that no longer exists.

Revision ID: f7b3d9e24a16
Revises: e5c9b3a71f48
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "f7b3d9e24a16"
down_revision = "e5c9b3a71f48"
branch_labels = None
depends_on = None

OLD = "product_feature_launch"
NEW = "product_launch"


def upgrade() -> None:
    _rename(op.get_bind(), OLD, NEW)


def downgrade() -> None:
    _rename(op.get_bind(), NEW, OLD)


def _rename(conn, old: str, new: str) -> None:
    conn.execute(
        sa.text("UPDATE signal_type SET key = :new WHERE key = :old").bindparams(
            new=new, old=old
        )
    )
    # Read, rewritten and written back in Python rather than with a jsonb
    # expression, for the reason b4f8d1a27c95 gives: the value is an array of
    # strings and a SQL version of that is a `jsonb_array_elements` subquery
    # nobody will be able to read in six months.
    rows = conn.execute(
        sa.text(
            "SELECT id, definition FROM icp_profile_version "
            "WHERE definition ? 'signals_that_matter'"
        )
    ).all()
    for row_id, definition in rows:
        current = definition.get("signals_that_matter") or []
        if old not in current:
            continue
        # dict.fromkeys rather than set(): the order a rep put them in is worth
        # keeping, and this guards the case where both names somehow appear.
        definition["signals_that_matter"] = list(
            dict.fromkeys(new if k == old else k for k in current)
        )
        conn.execute(
            sa.text(
                "UPDATE icp_profile_version SET definition = CAST(:d AS jsonb) "
                "WHERE id = :i"
            ).bindparams(d=json.dumps(definition), i=row_id)
        )
