"""The live role grid, user administration, and the audit trail.

The grid is read on every signed-in request, so it is cached for a few
seconds. A save clears the cache in this process; another worker sees the
change within the TTL — short enough that "I just took that away" holds by the
time anyone could try it.
"""

from __future__ import annotations

import logging
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import ROLES, AuditLog, RoleGrid, User
from app.services import auth, permissions

log = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 5.0
_cache: tuple[float, dict] | None = None


def forget_cached_grid() -> None:
    global _cache
    _cache = None


async def active_grid_row(session: AsyncSession) -> RoleGrid | None:
    return (
        await session.execute(select(RoleGrid).where(RoleGrid.is_active.is_(True)))
    ).scalar_one_or_none()


async def active_grid(session: AsyncSession) -> dict:
    """The grid in force. The shipped default if none has been saved — a
    database restored without the seed must still let people work."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    row = await active_grid_row(session)
    grid = row.grid if row is not None else permissions.DEFAULT_GRID
    _cache = (now, grid)
    return grid


async def save_grid(session: AsyncSession, grid: dict, *, by: User | None) -> RoleGrid:
    """Supersede the active grid with a new version. Never edits one in place."""
    clean = permissions.validate_grid(grid)
    current = await active_grid_row(session)
    latest = (await session.execute(select(func.max(RoleGrid.version)))).scalar() or 0
    if current is not None:
        current.is_active = False
        await session.flush()
    row = RoleGrid(
        version=latest + 1, grid=clean, is_active=True, created_by_id=by.id if by else None
    )
    session.add(row)
    await session.flush()
    forget_cached_grid()
    await record(
        session, by, "roles.saved", "role_grid", str(row.version),
        {"from_version": current.version if current else None},
    )
    return row


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------
async def record(
    session: AsyncSession,
    actor: User | None,
    action: str,
    subject_type: str | None = None,
    subject_id: str | None = None,
    detail: dict | None = None,
) -> None:
    """Append one row. Flushed with the change it describes, so the two
    commit or roll back together — an audit row for something that did not
    happen is worse than none."""
    session.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_label=actor.email if actor else "anonymous",
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            detail=detail,
        )
    )
    await session.flush()


def reviewer_id(user: User | None) -> str:
    """What `approval.reviewer_id` records.

    The user's id once someone is signed in. Before sign-in is enforced it
    stays the name every earlier approval carries, so the column does not mix
    two conventions for the same anonymous person.
    """
    return str(user.id) if user is not None else "bertie"


# --------------------------------------------------------------------------
# user administration
# --------------------------------------------------------------------------
class AccessRefused(ValueError):
    """Refused for a reason the admin should read."""


async def _active_admins(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(User).where(
                User.role == "admin", User.status == "active"
            )
        )
    ).scalar_one()


async def _would_strand_admins(session: AsyncSession, target: User) -> bool:
    return target.role == "admin" and target.status == "active" and await _active_admins(session) <= 1


async def change_role(session: AsyncSession, target: User, role: str, *, by: User | None) -> None:
    if role not in ROLES:
        raise AccessRefused(f"role must be one of {', '.join(ROLES)}")
    if role == target.role:
        return
    if by is not None and by.id == target.id:
        raise AccessRefused("you can't change your own role — ask another admin")
    if role != "admin" and await _would_strand_admins(session, target):
        raise AccessRefused("this is the last active admin")
    before = target.role
    target.role = role
    await record(session, by, "user.role_changed", "app_user", str(target.id),
                 {"from": before, "to": role})


async def deactivate(session: AsyncSession, target: User, *, by: User | None) -> None:
    if target.status == "deactivated":
        return
    if by is not None and by.id == target.id:
        raise AccessRefused("you can't deactivate yourself")
    if await _would_strand_admins(session, target):
        raise AccessRefused("this is the last active admin")
    target.status = "deactivated"
    # Ends every session they hold, now.
    target.session_version += 1
    await record(session, by, "user.deactivated", "app_user", str(target.id))


async def reactivate(session: AsyncSession, target: User, *, by: User | None) -> None:
    if target.status == "active":
        return
    target.status = "active"
    target.failed_login_count = 0
    target.locked_until = None
    await record(session, by, "user.reactivated", "app_user", str(target.id))


async def reset_password(session: AsyncSession, target: User, password: str, *, by: User | None) -> None:
    auth.set_password(target, password)
    # The fact of a reset, never the password.
    await record(session, by, "user.password_set", "app_user", str(target.id))


async def create(
    session: AsyncSession, *, email: str, full_name: str, role: str, password: str, by: User | None
) -> User:
    user = await auth.create_user(
        session, email=email, full_name=full_name, role=role, password=password, created_by=by
    )
    await record(session, by, "user.created", "app_user", str(user.id), {"role": role})
    return user


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)
