"""Settings › Users and Settings › Roles (`docs/17`, phase 2).

**Always a signed-in admin**, whatever `AUTH_REQUIRED` says. Every other route
stays open to anonymous callers until phase 3 so the running UI keeps working,
but an anonymous caller who could create an account here would hand
themselves an admin that outlives the switch being turned on.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import UserOut, current_user
from app.database import get_session
from app.models.identity import RoleGrid, User
from app.services import access, permissions


async def admin_only(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can do that.")
    return user


router = APIRouter(tags=["users"], dependencies=[Depends(admin_only)])


class UserCreateIn(BaseModel):
    email: str
    full_name: str
    role: str
    password: str


class UserPatchIn(BaseModel):
    full_name: str | None = None
    role: str | None = None


class PasswordSetIn(BaseModel):
    password: str


class AdminUserOut(UserOut):
    created_at: datetime
    #: What this user has done that a record points at, by kind. Empty means
    #: they can be deleted; anything here means deactivate instead.
    history: dict[str, int] = {}
    #: The super admin (`SUPERADMIN_EMAIL`): nobody else can change this account.
    protected: bool = False

    @classmethod
    def of(cls, user: User, history: dict[str, int] | None = None) -> AdminUserOut:  # type: ignore[override]
        return cls(
            **UserOut.of(user).model_dump(), created_at=user.created_at,
            history=history or {}, protected=access.is_super(user),
        )


async def _target(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await access.get_user(session, user_id)
    if user is None:
        raise HTTPException(404, "no such user")
    return user


def _refused(exc: ValueError) -> HTTPException:
    return HTTPException(409 if isinstance(exc, access.AccessRefused) else 422, str(exc))


# --------------------------------------------------------------------------
# users
# --------------------------------------------------------------------------
@router.get("/users", response_model=list[AdminUserOut])
async def list_users(session: AsyncSession = Depends(get_session)):
    """Active first, then by name. Deactivated people stay listed: they are
    who approved and sent things before they left."""
    rows = (await session.execute(select(User))).scalars().all()
    rows = sorted(rows, key=lambda u: (u.status != "active", u.full_name.lower()))
    done = await access.history(session, [u.id for u in rows])
    return [AdminUserOut.of(u, done[u.id]) for u in rows]


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID, session: AsyncSession = Depends(get_session), me: User = Depends(admin_only)
):
    """Only for an account with no history — one created by mistake. Anyone
    who has done something is deactivated instead, and the refusal says what."""
    target = await _target(session, user_id)
    try:
        await access.delete_user(session, target, by=me)
    except ValueError as e:
        raise _refused(e) from None
    await session.commit()


@router.post("/users", response_model=AdminUserOut, status_code=201)
async def create_user(
    payload: UserCreateIn,
    session: AsyncSession = Depends(get_session),
    me: User = Depends(admin_only),
):
    try:
        user = await access.create(
            session, email=payload.email, full_name=payload.full_name,
            role=payload.role, password=payload.password, by=me,
        )
    except ValueError as e:
        raise _refused(e) from None
    await session.commit()
    return AdminUserOut.of(user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserPatchIn,
    session: AsyncSession = Depends(get_session),
    me: User = Depends(admin_only),
):
    target = await _target(session, user_id)
    try:
        if payload.full_name is not None:
            if not payload.full_name.strip():
                raise ValueError("a name is required")
            target.full_name = payload.full_name.strip()
        if payload.role is not None:
            await access.change_role(session, target, payload.role, by=me)
    except ValueError as e:
        raise _refused(e) from None
    await session.commit()
    return AdminUserOut.of(target)


@router.post("/users/{user_id}/deactivate", response_model=AdminUserOut)
async def deactivate_user(
    user_id: uuid.UUID, session: AsyncSession = Depends(get_session), me: User = Depends(admin_only)
):
    """Signs them out everywhere. Never a delete — see `models/identity.User`."""
    target = await _target(session, user_id)
    try:
        await access.deactivate(session, target, by=me)
    except ValueError as e:
        raise _refused(e) from None
    await session.commit()
    return AdminUserOut.of(target)


@router.post("/users/{user_id}/reactivate", response_model=AdminUserOut)
async def reactivate_user(
    user_id: uuid.UUID, session: AsyncSession = Depends(get_session), me: User = Depends(admin_only)
):
    target = await _target(session, user_id)
    await access.reactivate(session, target, by=me)
    await session.commit()
    return AdminUserOut.of(target)


@router.post("/users/{user_id}/password", response_model=AdminUserOut)
async def set_user_password(
    user_id: uuid.UUID,
    payload: PasswordSetIn,
    session: AsyncSession = Depends(get_session),
    me: User = Depends(admin_only),
):
    """An admin sets a new password and tells the person. Their sessions end."""
    target = await _target(session, user_id)
    try:
        await access.reset_password(session, target, payload.password, by=me)
    except ValueError as e:
        raise _refused(e) from None
    await session.commit()
    return AdminUserOut.of(target)


# --------------------------------------------------------------------------
# roles
# --------------------------------------------------------------------------
class GridIn(BaseModel):
    grid: dict


@router.get("/roles")
async def get_roles(session: AsyncSession = Depends(get_session)):
    """The grid in force, plus the labels the screen draws it with."""
    row = await access.active_grid_row(session)
    author = await session.get(User, row.created_by_id) if row and row.created_by_id else None
    return {
        "version": row.version if row else 0,
        "saved_at": row.created_at if row else None,
        "saved_by": author.full_name if author else None,
        "grid": row.grid if row else permissions.DEFAULT_GRID,
        "roles": list(permissions.ROLES_IN_GRID),
        "modules": permissions.MODULES,
        "admin_modules": permissions.ADMIN_MODULES,
        "actions": permissions.ACTIONS,
        "levels": list(permissions.LEVELS),
    }


@router.put("/roles")
async def save_roles(
    payload: GridIn, session: AsyncSession = Depends(get_session), me: User = Depends(admin_only)
):
    try:
        row = await access.save_grid(session, payload.grid, by=me)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    await session.commit()
    return await get_roles(session)


@router.get("/roles/versions")
async def role_versions(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(RoleGrid).order_by(RoleGrid.version.desc()))).scalars().all()
    return [
        {"version": r.version, "is_active": r.is_active, "saved_at": r.created_at, "grid": r.grid}
        for r in rows
    ]
