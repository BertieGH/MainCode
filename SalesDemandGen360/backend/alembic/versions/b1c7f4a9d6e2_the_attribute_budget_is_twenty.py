"""The per-lead attribute cap is 20, not 10.

Ten came from the API documentation, along with the claim that LGM "silently
drops the overflow". Both were wrong, and a live account settled it: writing
`customAttribute11`, `customAttribute15` and `customAttribute20` stores each of
them and reads them all back. `customAttribute21` is **refused** — a 404, which
is how LGM answers a validation error — so nothing is dropped silently at any
size, and a lower cap on some other plan would fail loudly rather than lose a
touch.

The cap mattered: it is the ceiling on a cadence's length, since every step
spends one attribute and a custom subject spends another. At ten, a six-step
sequence could carry four custom subjects. At twenty it is not the binding
constraint at all.

Revision ID: b1c7f4a9d6e2
Revises: a7e4d2c9b5f3
"""

from __future__ import annotations

from alembic import op

revision = "b1c7f4a9d6e2"
down_revision = "a7e4d2c9b5f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("within_the_attribute_budget", "cadence_shape", type_="check")
    op.create_check_constraint(
        "within_the_attribute_budget", "cadence_shape", "attributes_used BETWEEN 0 AND 20"
    )


def downgrade() -> None:
    op.drop_constraint("within_the_attribute_budget", "cadence_shape", type_="check")
    op.create_check_constraint(
        "within_the_attribute_budget", "cadence_shape", "attributes_used BETWEEN 0 AND 10"
    )
