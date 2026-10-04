"""A signal type is either a dated event or an ongoing theme.

Dedupe keyed every signal on its date, which is right for an event — two funding
rounds are two facts — and wrong for a theme. What a company keeps publishing
about has no single date: each re-read dated it by whichever post the model
picked, and BlueWave collected four `public_focus` signals about one run of blog
posts, dated 11 Aug, 13 Aug, 25 Aug and 10 Sep.

`kind` says which a type is. A theme keeps one live signal per account (or
person) that moves forward only when a newer reading arrives.

`public_focus` and `delivery_quality_theme` are themes by their own descriptions
("what the company is pushing right now", "a recurring theme"); both are set here
if present. Everything else stays an event, which is the old behaviour.

Revision ID: b8d2f4a61c93
Revises: a3c6e820f7d1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8d2f4a61c93"
down_revision = "a3c6e820f7d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signal_type",
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'event'")),
    )
    # The naming convention supplies the `ck_signal_type_` prefix.
    op.create_check_constraint("kind_valid", "signal_type", "kind IN ('event','theme')")
    op.execute(
        "UPDATE signal_type SET kind = 'theme' "
        "WHERE key IN ('public_focus', 'delivery_quality_theme')"
    )


def downgrade() -> None:
    # Dropping the column takes its check constraint with it.
    op.drop_column("signal_type", "kind")
