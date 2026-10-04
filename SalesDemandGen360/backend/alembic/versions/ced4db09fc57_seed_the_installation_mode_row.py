"""seed the installation mode row

The previous migration created `installation_mode` and did not seed it, so a
database that has already run it has an empty table. `demo.current_mode`
defaults to `production` when no row exists, so nothing is unsafe — but the
table being empty is still wrong: `GET /config/mode` has nothing to return, and
the first switch numbers itself version 1, losing the fact that the
installation was production before that.

Written as an idempotent insert rather than by editing the applied migration.
Editing one that has already run is how two environments quietly diverge — this
one produces the same end state whether the table is empty or already has rows.

`production` is the seeded value for the same reason it is the code default: an
installation that has been running is a real one, and defaulting a live book to
`demo` would unlock its setup gate.

Revision ID: ced4db09fc57
Revises: f1180f61b92a
Create Date: 2026-09-06 14:05:00.000000
"""
from alembic import op

revision = 'ced4db09fc57'
down_revision = 'f1180f61b92a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO installation_mode (mode, reason, switched_by, version, is_active)
        SELECT 'production', 'default for an existing installation', 'migration', 1, true
        WHERE NOT EXISTS (SELECT 1 FROM installation_mode)
        """
    )


def downgrade() -> None:
    # Only the row this migration could have written. A mode somebody actually
    # chose is theirs, and removing it would silently reset the installation.
    op.execute(
        """
        DELETE FROM installation_mode
        WHERE version = 1 AND switched_by = 'migration'
          AND reason = 'default for an existing installation'
        """
    )
