"""Tell strategy to argue from the profiles, and not to deliberate over nothing.

A thread marked "pursue anyway" has no live signal to cite. The prompt already
told the model to "make the case from the company's situation and the person's
role" — and the payload gave it the company's name and postcode, and the
person's job title. There was no situation in it.

The result, measured over 44 calls: successes average 8.8 seconds, failures
average **35.6** — four times longer. A failure here is not a quick rejection,
it is the model deliberating itself into exhausting its token budget looking
for a trigger that does not exist. One such call ran 53 seconds before failing.

Two things changed together, and neither works without the other:

* the payload now carries `account.profile` and `contact.profile`, which is
  the material the instruction was already pointing at;
* the instruction says the material is all there is, and says plainly not to
  deliberate at length over a thread with no trigger — there is no hidden
  trigger to recover, and a long search produces the same answer as a short
  one.

It also gives the model somewhere to go when both profiles are empty: say so
in one sentence and mark the thread low confidence. Previously there was no
acceptable answer except an invented one, which is a poor thing to ask of a
model that is trying to comply.

Written as a new `prompt_template` version from the code, so the shipped
baseline and the stored row stay identical — and skipped if the live body is
past v1, because an admin edited that deliberately (§63).

Revision ID: e5c9b3a71f48
Revises: d1a7e9c45b82
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5c9b3a71f48"
down_revision = "d1a7e9c45b82"
branch_labels = None
depends_on = None

SCENARIO = "strategy_synthesis"


def upgrade() -> None:
    from app.services.instructions import STAGE

    conn = op.get_bind()
    shipped = STAGE[SCENARIO].strip()
    row = conn.execute(
        sa.text(
            "SELECT id, body, version FROM prompt_template "
            "WHERE scenario = :s AND is_active"
        ).bindparams(s=SCENARIO)
    ).first()
    if row is None or row.body.strip() == shipped:
        return
    # Only a version this migration chain wrote may be replaced. Past that,
    # someone edited it on the Prompts screen and overwriting their work from a
    # migration is the one way this feature destroys something.
    if row.version > 2:
        return
    conn.execute(
        sa.text("UPDATE prompt_template SET is_active = false WHERE id = :i").bindparams(
            i=row.id
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO prompt_template (scenario, body, note, version, is_active) "
            "VALUES (:s, :b, :n, :v, true)"
        ).bindparams(
            s=SCENARIO,
            b=shipped,
            n="argue a no-trigger thread from the profiles; do not deliberate",
            v=row.version + 1,
        )
    )


def downgrade() -> None:
    """The text goes back by editing, not by a schema step."""
