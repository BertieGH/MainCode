"""Signing people in, and knowing who a request is from.

**Accounts are made by an admin** (`docs/17`): name, email, role, and a
password the admin sets and passes on themselves. There is no registration and
no email. The first admin comes from `scripts/create_admin.py`.

**A session is a signed cookie, not a row.** It carries the user id, their
`session_version` and an expiry, HMAC'd with `SECRET_KEY` — the key that
already encrypts stored credentials, so anyone who could forge a session could
already read the API keys. Bumping `session_version` (password change, reset,
deactivation) invalidates every cookie that person holds at once, with no
session table to sweep and nothing stranded by a restart.

**Five wrong passwords lock an account for fifteen minutes.** Counted on the
user row rather than in memory, so a restart or a second worker does not hand
out a fresh five.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.identity import ROLES, Organization, User
from app.services import passwords

log = logging.getLogger(__name__)

COOKIE_NAME = "sdg_session"

#: A working day and then some. Long enough not to interrupt anyone; short
#: enough that a laptop left signed in overnight is signed out by morning.
SESSION_TTL_SECONDS = 60 * 60 * 12

MIN_PASSWORD_LENGTH = 10
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)

#: Signed into every session token and nothing else. `admin_gate` signs its
#: tokens with the same key; without a distinct prefix one kind of token could
#: be presented as the other.
_SESSION_DOMAIN = "session:"


class AuthError(Exception):
    """A sign-in that did not succeed. The message is safe to show."""

    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


WRONG_CREDENTIALS = "Wrong email or password."


# --------------------------------------------------------------------------
# accounts
# --------------------------------------------------------------------------
def normalise_email(email: str) -> str:
    return email.strip().lower()


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"the password must be at least {MIN_PASSWORD_LENGTH} characters")


async def organization(session: AsyncSession) -> Organization:
    """The one organisation, made if it is not there yet.

    The migration seeds it, but tests truncate every table and a fresh
    database restored from a dump might not carry it — and creating a user
    should not fail on bookkeeping.
    """
    org = (await session.execute(select(Organization).limit(1))).scalar_one_or_none()
    if org is None:
        org = Organization(name="CGVAK")
        session.add(org)
        await session.flush()
    return org


async def find_by_email(session: AsyncSession, email: str) -> User | None:
    return (
        await session.execute(select(User).where(func.lower(User.email) == normalise_email(email)))
    ).scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    role: str,
    password: str,
    created_by: User | None = None,
) -> User:
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    if not full_name.strip():
        raise ValueError("a name is required")
    if "@" not in email:
        raise ValueError("that is not an email address")
    check_password_rules(password)
    if await find_by_email(session, email) is not None:
        raise ValueError("an account with that email already exists")

    hashed = passwords.hash_password(password)
    user = User(
        organization_id=(await organization(session)).id,
        email=normalise_email(email),
        full_name=full_name.strip(),
        role=role,
        status="active",
        password_hash=hashed.password_hash,
        salt=hashed.salt,
        n=hashed.n,
        r=hashed.r,
        p=hashed.p,
        session_version=1,
        failed_login_count=0,
        created_by_id=created_by.id if created_by else None,
    )
    session.add(user)
    await session.flush()
    # Never the password. Invariant 9.
    log.info("auth.user_created id=%s role=%s", user.id, role)
    return user


def set_password(user: User, password: str) -> None:
    """Replace a password and sign the person out everywhere."""
    check_password_rules(password)
    hashed = passwords.hash_password(password)
    user.password_hash = hashed.password_hash
    user.salt = hashed.salt
    user.n, user.r, user.p = hashed.n, hashed.r, hashed.p
    user.session_version += 1
    user.failed_login_count = 0
    user.locked_until = None


def password_matches(user: User, password: str) -> bool:
    return passwords.matches(
        password, password_hash=user.password_hash, salt=user.salt, n=user.n, r=user.r, p=user.p
    )


async def authenticate(
    session: AsyncSession, email: str, password: str, *, now: datetime | None = None
) -> User:
    """The user these credentials belong to, or `AuthError`.

    Every refusal before the lock reads the same — an unknown address and a
    wrong password are indistinguishable, in wording and in time taken.
    """
    now = now or datetime.now(UTC)
    user = await find_by_email(session, email)
    if user is None:
        passwords.burn_time(password)
        log.info("auth.login_failed reason=unknown_email")
        raise AuthError(WRONG_CREDENTIALS)

    if user.locked_until is not None and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise AuthError(
            f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
            status_code=429,
        )

    if not password_matches(user, password):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + LOCKOUT
            user.failed_login_count = 0
            log.warning("auth.locked id=%s", user.id)
        else:
            log.info("auth.login_failed id=%s reason=password", user.id)
        await session.commit()
        raise AuthError(WRONG_CREDENTIALS)

    # Checked after the password, so a wrong guess learns nothing about
    # whether the account is live.
    if user.status != "active":
        raise AuthError("This account is deactivated. Ask an admin.", status_code=403)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    await session.commit()
    log.info("auth.login id=%s", user.id)
    return user


# --------------------------------------------------------------------------
# session tokens
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SessionClaims:
    user_id: uuid.UUID
    session_version: int
    expires: int


def _sign(payload: str) -> str:
    key = get_settings().secret_key.encode("utf-8")
    digest = hmac.new(key, (_SESSION_DOMAIN + payload).encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issue_session(user: User, *, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + SESSION_TTL_SECONDS)
    payload = f"{user.id}.{user.session_version}.{expires}"
    return f"{payload}.{_sign(payload)}"


def read_session(token: str | None, *, now: float | None = None) -> SessionClaims | None:
    """The claims in a token, if it is genuine and unexpired; otherwise None."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 4:
        return None
    user_raw, version_raw, expires_raw, signature = parts
    # Signature first: acting on fields parsed out of an unsigned string is how
    # a check like this becomes decorative.
    if not hmac.compare_digest(signature, _sign(f"{user_raw}.{version_raw}.{expires_raw}")):
        return None
    try:
        claims = SessionClaims(uuid.UUID(user_raw), int(version_raw), int(expires_raw))
    except ValueError:
        return None
    if claims.expires <= (now if now is not None else time.time()):
        return None
    return claims


async def user_for_session(session: AsyncSession, token: str | None) -> User | None:
    """The live user behind a cookie, or None.

    None also for a deactivated user and for a token minted before their last
    password change — those are the two ways a session ends early.
    """
    claims = read_session(token)
    if claims is None:
        return None
    user = await session.get(User, claims.user_id)
    if user is None or user.status != "active" or user.session_version != claims.session_version:
        return None
    return user
