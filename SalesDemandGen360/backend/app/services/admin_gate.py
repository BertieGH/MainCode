"""The lock on the prompt editor.

**This is not authentication, and nothing here should be mistaken for it.**
Every other route in this application is open — there is no user table, no
session, no login. What this does is stop the one screen that can rewrite the
model's instructions from being as open as the rest. A lock on one door in a
building with no front door; recorded as exactly that in
`docs/14-prompt-config-plan.md`, with real auth named as the prerequisite
before this app is hosted or shared.

Three choices worth their reasons:

**scrypt, from the standard library.** A real KDF. Neither bcrypt nor argon2 is
installed, and adding a dependency to hash one password is a poor trade. The
cost parameters are stored per row so they can be raised later without
invalidating anyone.

**Unset means unconfigured, not locked.** If no password has been set, the API
says so and the UI offers to set one. The alternative — treating "no password"
as "refuse everything" — locks the owner out of their own installation with no
way back in short of a database edit.

**The token is an HMAC over an expiry, not a stored session.** There is no
session table to add, nothing to clean up, and a restart does not strand
anyone. It is signed with `SECRET_KEY`, which already encrypts stored
credentials, so an installation that can forge one of these could already
decrypt the API keys.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.config import AdminSecret
from app.services import passwords

log = logging.getLogger(__name__)

# Hashing lives in `passwords`, shared with sign-in; the names stay here so
# existing callers and tests read the same.
SCRYPT_N, SCRYPT_R, SCRYPT_P, KEY_LEN = (
    passwords.SCRYPT_N, passwords.SCRYPT_R, passwords.SCRYPT_P, passwords.KEY_LEN,
)

#: How long an unlock lasts. Short enough that a left-open browser tab stops
#: being a way in; long enough to edit several prompts without re-typing.
TOKEN_TTL_SECONDS = 60 * 30

#: The header the UI sends it back in.
TOKEN_HEADER = "X-Admin-Token"

MIN_PASSWORD_LENGTH = 8


_derive = passwords.derive


async def current(session: AsyncSession) -> AdminSecret | None:
    return (
        await session.execute(
            select(AdminSecret).where(AdminSecret.is_active.is_(True))
        )
    ).scalar_one_or_none()


async def is_configured(session: AsyncSession) -> bool:
    return await current(session) is not None


async def set_password(session: AsyncSession, password: str) -> AdminSecret:
    """Set or replace the password.

    Replacing supersedes rather than mutates, consistent with every other
    versioned row here — and it means a botched change can be diagnosed from
    the table rather than guessed at.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"the password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    existing = await current(session)
    if existing is not None:
        existing.is_active = False
        await session.flush()

    salt = os.urandom(16)
    row = AdminSecret(
        password_hash=_derive(password, salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        is_active=True,
    )
    session.add(row)
    await session.flush()
    # Never the password, never the hash. Invariant 9 is about credentials
    # reaching a log, and this is one.
    log.info("admin_gate.password_set")
    return row


async def verify(session: AsyncSession, password: str) -> bool:
    """Whether this password is the one.

    `compare_digest` rather than `==`: the difference is unobservable here in
    practice and the habit is worth keeping intact, because the next place this
    pattern gets copied might be reachable from the internet.
    """
    row = await current(session)
    if row is None:
        return False
    candidate = _derive(password, row.salt, n=row.n, r=row.r, p=row.p)
    return hmac.compare_digest(candidate, row.password_hash)


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------
def _sign(payload: str) -> str:
    key = get_settings().secret_key.encode("utf-8")
    digest = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issue_token(*, now: float | None = None) -> str:
    """A token good until it expires. Carries no identity, because there is none."""
    expires = int((now if now is not None else time.time()) + TOKEN_TTL_SECONDS)
    # The nonce makes two tokens issued in the same second differ, so one
    # appearing in a log or a screenshot cannot be matched against another.
    nonce = secrets.token_urlsafe(8)
    payload = f"{expires}.{nonce}"
    return f"{payload}.{_sign(payload)}"


def token_is_valid(token: str | None, *, now: float | None = None) -> bool:
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    expires_raw, nonce, signature = parts
    payload = f"{expires_raw}.{nonce}"
    # Signature first. Parsing an expiry out of an unsigned string and acting
    # on it is how a check like this becomes decorative.
    if not hmac.compare_digest(signature, _sign(payload)):
        return False
    try:
        expires = int(expires_raw)
    except ValueError:
        return False
    return expires > (now if now is not None else time.time())
