"""Convert articles.keyword_hits to JSONB + add GIN index

Revision ID: 017
Revises: 016
Create Date: 2026-05-06

The keyword filter on /articles previously loaded all matching rows then
post-filtered in Python (articles.py: `_matches`). With JSONB + GIN we can
push it to SQL via the `?|` (any-of) and `?&` (all-of) operators, which
the GIN index serves directly.

No-op on SQLite (its TEXT-typed JSON column needs no schema change; the
SQLAlchemy with_variant() in the model handles the dialect difference).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return  # SQLite dev: model's with_variant keeps the column as JSON
    op.execute(
        "ALTER TABLE articles "
        "ALTER COLUMN keyword_hits TYPE JSONB USING keyword_hits::jsonb"
    )
    op.create_index(
        "ix_articles_keyword_hits_gin",
        "articles",
        ["keyword_hits"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_index("ix_articles_keyword_hits_gin", table_name="articles")
    op.execute(
        "ALTER TABLE articles "
        "ALTER COLUMN keyword_hits TYPE JSON USING keyword_hits::json"
    )
