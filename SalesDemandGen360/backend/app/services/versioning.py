"""Versioned configuration.

Every config surface in this system follows one rule: **a change writes a new
version and deactivates the old one. Nothing is ever mutated in place.**

That is not tidiness. A qualification computed last month was computed against a
particular `scoring_config`; if that row is edited, the qualification can no
longer explain itself, and the audit trail quietly becomes fiction.

The "exactly one active" guarantee is a partial unique index in the database,
not a check here. Two concurrent activations would both pass a check-then-write
in application code and leave two active rows with no error raised.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base


class VersioningError(RuntimeError):
    pass


async def next_version[T: Base](
    session: AsyncSession, model: type[T], *, scope_field: str | None = None,
    scope_value: object | None = None,
) -> int:
    """The next version number, optionally scoped to a key such as `scenario`."""
    stmt = select(func.coalesce(func.max(model.version), 0))  # type: ignore[attr-defined]
    if scope_field is not None:
        stmt = stmt.where(getattr(model, scope_field) == scope_value)
    current = (await session.execute(stmt)).scalar_one()
    return int(current) + 1


async def get_active[T: Base](
    session: AsyncSession, model: type[T], *, scope_field: str | None = None,
    scope_value: object | None = None,
) -> T | None:
    stmt = select(model).where(model.is_active.is_(True))  # type: ignore[attr-defined]
    if scope_field is not None:
        stmt = stmt.where(getattr(model, scope_field) == scope_value)
    return (await session.execute(stmt)).scalar_one_or_none()


async def activate_new_version[T: Base](
    session: AsyncSession,
    model: type[T],
    values: dict,
    *,
    scope_field: str | None = None,
) -> T:
    """Deactivate the current active row and insert a new active one.

    Order matters and is not interchangeable. The deactivate must land before
    the insert, because the partial unique index permits only one active row —
    inserting first would violate it.

    Both statements share the caller's transaction, so a failure leaves the
    previous version active rather than leaving the system with none.
    """
    scope_value = values.get(scope_field) if scope_field else None

    if scope_field is not None and scope_value is None:
        raise VersioningError(f"{scope_field} is required when scoping versions")

    deactivate = (
        update(model)
        .where(model.is_active.is_(True))  # type: ignore[attr-defined]
        .values(is_active=False)
    )
    if scope_field is not None:
        deactivate = deactivate.where(getattr(model, scope_field) == scope_value)
    await session.execute(deactivate)

    version = await next_version(
        session, model, scope_field=scope_field, scope_value=scope_value
    )
    row = model(**values, version=version, is_active=True)  # type: ignore[call-arg]
    session.add(row)

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise VersioningError(
            "could not activate the new version — a concurrent activation likely won"
        ) from exc

    return row
