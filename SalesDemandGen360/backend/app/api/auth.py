"""Sign in, sign out, who am I, change my password.

Accounts are created by an admin (phase 2, `docs/17`); there is no route here
that makes one. The first admin comes from `scripts/create_admin.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models.identity import User
from app.services import access, auth, permissions

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


class MeOut(BaseModel):
    user: "UserOut"
    #: What this person can do, for the UI to hide what they cannot. The
    #: server re-checks every request; this is for clarity, not safety.
    permissions: dict


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    last_login_at: datetime | None = None

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            status=user.status,
            last_login_at=user.last_login_at,
        )


# --------------------------------------------------------------------------
# who is asking
# --------------------------------------------------------------------------
async def current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    """The signed-in user, or None. Never refuses on its own."""
    return await auth.user_for_session(session, request.cookies.get(auth.COOKIE_NAME))


def _route_template(request: Request) -> str:
    """The template FastAPI matched — `/api/campaigns/{campaign_id}/execute` —
    rather than the raw URL, which a crafted path could bend around a rule.

    Routes inside an included router report their path without the mount
    prefix, and every guarded router is mounted at `/api`, so it is put back.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    return path if path.startswith("/api/") else "/api" + path


async def require_user(
    request: Request,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Put on every router but sign-in, health and the LGM inbox.

    Anonymous: a 401 with `AUTH_REQUIRED` on; allowed with it off, so the
    running UI keeps working until it has a sign-in page (phase 3).
    Signed in: always checked against the role grid — a 403 that says which
    module or action the role lacks.
    """
    if user is None:
        if get_settings().auth_required:
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        return None
    reason = permissions.refusal(
        await access.active_grid(session), user.role, request.method, _route_template(request)
    )
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    return user


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=auth.SESSION_TTL_SECONDS,
        # Script never reads it, so script injection cannot take it.
        httponly=True,
        # Lax: not sent on cross-site POSTs, which is the forged-request case.
        samesite="lax",
        # Local dev is plain http; anywhere else the cookie travels only over TLS.
        secure=settings.environment not in ("local", "ci"),
        path="/",
    )


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@router.post("/login", response_model=UserOut)
async def login(payload: LoginIn, response: Response, session: AsyncSession = Depends(get_session)):
    try:
        user = await auth.authenticate(session, payload.email, payload.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from None
    _set_cookie(response, auth.issue_session(user))
    return UserOut.of(user)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> Response:
    """Drops this browser's cookie. Signing out *everywhere* is a password change."""
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut)
async def me(user: User | None = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return MeOut(
        user=UserOut.of(user),
        permissions=permissions.effective(await access.active_grid(session), user.role),
    )


@router.post("/password", response_model=UserOut)
async def change_password(
    payload: PasswordIn,
    response: Response,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Change your own password. Every other session you hold ends; this one is re-issued."""
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    if not auth.password_matches(user, payload.current_password):
        raise HTTPException(status_code=400, detail="Your current password is wrong.")
    try:
        auth.set_password(user, payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    await session.commit()
    _set_cookie(response, auth.issue_session(user))
    return UserOut.of(user)


MeOut.model_rebuild()
