"""`leadership_change_executive` claims `linkedin_index`, so it runs at company scope.

Found on the first live run. `linkedin_index` never executed, and it is not a
bug in the source — it is the derivation rule working exactly as designed and
revealing a gap in the registry.

Sources are derived from the `produced_by` of the signal types **in scope**.
`linkedin_index` was claimed only by the three *contact* types, so it appeared
in the contact plan and not the company one. The run had no contacts — the book
was imported account-grain — so the contact plan never ran and the source was
never reached.

The awkward part is that the company-level query is what **finds** the people in
the first place: `site:linkedin.com/in "{company}"` returns nine or ten
employees with their roles, which is how a contact list gets built. Reaching it
only through contact-scoped types means it can only run once the contacts it
would have found already exist.

The fix is the one the architecture asks for: a **company-scoped type must say
its fact lives there**. `leadership_change_executive` genuinely does — its whole
subject is who holds a technology or operations seat, and a profile reading
"VP of Operations at X" is evidence about that seat whether or not the person is
a contact we track. Its description already says the overlap with
`contact_role_change` is deliberate.

So this is not a workaround for the plan; it is the registry catching up with
what the type was always about.

Revision ID: d9b2f45c17ae
Revises: c5e1a83d7b29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d9b2f45c17ae"
down_revision = "c5e1a83d7b29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE signal_type "
            "   SET produced_by = array_append(produced_by, 'linkedin_index'), "
            "       updated_at = now() "
            " WHERE key = 'leadership_change_executive' "
            "   AND NOT ('linkedin_index' = ANY(produced_by))"
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE signal_type "
            "   SET produced_by = array_remove(produced_by, 'linkedin_index'), "
            "       updated_at = now() "
            " WHERE key = 'leadership_change_executive'"
        )
    )
