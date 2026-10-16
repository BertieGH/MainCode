"""Signing in (`docs/17`, phase 1).

Two halves. The token and the route guard need no database. Accounts, the
lockout and the ways a session ends early do, because each of them is a fact
on the user row.

What matters most is what *ends* a session: a password change, a reset and a
deactivation must each make every cookie that person holds stop working, at
once, without a session table — that is the whole reason for
`session_version`.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database import get_session
from app.services import auth


class _FakeUser:
    def __init__(self, version: int = 1) -> None:
        self.id = uuid.uuid4()
        self.session_version = version


# --------------------------------------------------------------------------
# tokens — no database
# --------------------------------------------------------------------------
def test_a_session_token_round_trips():
    user = _FakeUser(version=3)
    claims = auth.read_session(auth.issue_session(user))
    assert claims is not None
    assert claims.user_id == user.id
    assert claims.session_version == 3


def test_a_tampered_token_is_refused():
    token = auth.issue_session(_FakeUser())
    user_id, version, expires, sig = token.split(".")
    # Same signature, someone else's id: the forgery a signed cookie exists to stop.
    assert auth.read_session(f"{uuid.uuid4()}.{version}.{expires}.{sig}") is None
    # A later expiry, same signature.
    assert auth.read_session(f"{user_id}.{version}.{int(expires) + 99999}.{sig}") is None


def test_an_expired_token_is_refused():
    token = auth.issue_session(_FakeUser(), now=time.time() - auth.SESSION_TTL_SECONDS - 1)
    assert auth.read_session(token) is None


def test_garbage_is_refused_without_an_error():
    for junk in (None, "", "a.b", "a.b.c.d", "not-a-uuid.1.9999999999.sig"):
        assert auth.read_session(junk) is None


def test_a_session_token_is_not_signed_like_an_admin_gate_token():
    """Both sign with SECRET_KEY. The domain prefix is what keeps them apart."""
    import base64
    import hashlib
    import hmac

    user = _FakeUser()
    payload = f"{user.id}.1.{int(time.time()) + 600}"
    key = get_settings().secret_key.encode()
    bare = base64.urlsafe_b64encode(
        hmac.new(key, payload.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    assert auth.read_session(f"{payload}.{bare}") is None


# --------------------------------------------------------------------------
# the route guard — no database
# --------------------------------------------------------------------------
@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_required", True)


async def test_with_auth_required_an_anonymous_request_is_refused(client, auth_on):
    r = await client.get("/api/campaigns")
    assert r.status_code == 401
    assert r.json()["detail"] == "Sign in to continue."


async def test_health_stays_public(client, auth_on):
    r = await client.get("/api/health")
    assert r.status_code != 401


async def test_the_lgm_webhook_stays_public(client, auth_on, monkeypatch):
    """LGM cannot sign in. Its credential is the token in the path, so with
    sign-in enforced the route must still answer — with its own 404 for a bad
    token, not a 401 that would make LGM retry forever."""
    from app.api import outreach_events

    async def _no_token(_session):
        return None

    monkeypatch.setattr(outreach_events, "_stored_token", _no_token)
    r = await client.post("/api/lgm/inbox/whatever", json={})
    assert r.status_code == 404


async def test_me_without_a_session_is_401(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


# --------------------------------------------------------------------------
# accounts — real database
# --------------------------------------------------------------------------
needs_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)

PASSWORD = "correct horse battery"


@pytest.fixture
async def api(app):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _make_user(maker, *, email="priya@cgvak.com", role="demandgen", password=PASSWORD):
    async with maker() as s:
        user = await auth.create_user(
            s, email=email, full_name="Priya N.", role=role, password=password
        )
        await s.commit()
        return user.id


async def _update(maker, user_id, **fields):
    from app.models.identity import User

    async with maker() as s:
        user = await s.get(User, user_id)
        for k, v in fields.items():
            setattr(user, k, v)
        await s.commit()


@pytest.mark.db
@needs_db
async def test_sign_in_sets_a_cookie_and_me_answers(api):
    await _make_user(api.maker)
    r = await api.post("/api/auth/login", json={"email": "Priya@CGVAK.com ", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "demandgen"
    cookie = r.headers["set-cookie"]
    assert auth.COOKIE_NAME in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()

    me = await api.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "priya@cgvak.com"
    assert me.json()["user"]["last_login_at"] is not None
    # What the UI hides by: DemandGen sends, and has no API config.
    perms = me.json()["permissions"]
    assert "approve_send" in perms["actions"]
    assert perms["modules"]["api_config"] == "none"


@pytest.mark.db
@needs_db
async def test_a_wrong_password_and_an_unknown_email_read_the_same(api):
    await _make_user(api.maker)
    wrong = await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": "nope-nope-nope"})
    unknown = await api.post("/api/auth/login", json={"email": "nobody@cgvak.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "set-cookie" not in wrong.headers


@pytest.mark.db
@needs_db
async def test_five_wrong_passwords_lock_the_account_even_against_the_right_one(api):
    await _make_user(api.maker)
    for _ in range(auth.MAX_FAILED_LOGINS):
        r = await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": "wrong-password"})
        assert r.status_code == 401
    locked = await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": PASSWORD})
    assert locked.status_code == 429
    assert "Try again in" in locked.json()["detail"]


@pytest.mark.db
@needs_db
async def test_the_lock_lifts_after_its_time(api):
    user_id = await _make_user(api.maker)
    await _update(api.maker, user_id, locked_until=datetime.now(UTC) - timedelta(seconds=1))
    r = await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": PASSWORD})
    assert r.status_code == 200


@pytest.mark.db
@needs_db
async def test_a_deactivated_account_cannot_sign_in_and_its_sessions_end(api):
    user_id = await _make_user(api.maker)
    await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": PASSWORD})
    assert (await api.get("/api/auth/me")).status_code == 200

    await _update(api.maker, user_id, status="deactivated")
    assert (await api.get("/api/auth/me")).status_code == 401

    again = await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": PASSWORD})
    assert again.status_code == 403
    # A wrong password on a deactivated account says nothing about its state.
    guess = await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": "wrong-password"})
    assert guess.status_code == 401


@pytest.mark.db
@needs_db
async def test_changing_your_password_ends_your_other_sessions(api, app):
    await _make_user(api.maker)
    await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": PASSWORD})
    old_cookie = api.cookies.get(auth.COOKIE_NAME)

    bad = await api.post("/api/auth/password", json={"current_password": "not-it-at-all", "new_password": "a brand new one"})
    assert bad.status_code == 400
    short = await api.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422

    ok = await api.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "a brand new one"})
    assert ok.status_code == 200
    # This browser was re-issued a cookie and stays in.
    assert (await api.get("/api/auth/me")).status_code == 200

    # The cookie from before the change — another browser, say — is dead.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        other.cookies.set(auth.COOKIE_NAME, old_cookie)
        assert (await other.get("/api/auth/me")).status_code == 401

    old = await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": PASSWORD})
    assert old.status_code == 401
    new = await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": "a brand new one"})
    assert new.status_code == 200


@pytest.mark.db
@needs_db
async def test_sign_out_drops_the_cookie(api):
    await _make_user(api.maker)
    await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": PASSWORD})
    r = await api.post("/api/auth/logout")
    assert r.status_code == 204
    assert (await api.get("/api/auth/me")).status_code == 401


@pytest.mark.db
@needs_db
async def test_with_auth_required_a_signed_in_request_goes_through(api, auth_on):
    await _make_user(api.maker)
    assert (await api.get("/api/campaigns")).status_code == 401
    await api.post("/api/auth/login", json={"email": "priya@cgvak.com", "password": PASSWORD})
    assert (await api.get("/api/campaigns")).status_code == 200


@pytest.mark.db
@needs_db
async def test_account_rules(api):
    await _make_user(api.maker)
    async with api.maker() as s:
        with pytest.raises(ValueError, match="already exists"):
            await auth.create_user(s, email="PRIYA@cgvak.com", full_name="x", role="aiops", password=PASSWORD)
        with pytest.raises(ValueError, match="at least"):
            await auth.create_user(s, email="new@cgvak.com", full_name="x", role="aiops", password="short")
        with pytest.raises(ValueError, match="role"):
            await auth.create_user(s, email="new@cgvak.com", full_name="x", role="owner", password=PASSWORD)


@pytest.mark.db
@needs_db
async def test_the_database_refuses_a_second_account_for_the_same_address_in_any_case(api):
    """The app checks first; the index is what holds if two requests race."""
    from sqlalchemy.exc import IntegrityError

    from app.models.identity import User
    from app.services import passwords

    await _make_user(api.maker)
    h = passwords.hash_password(PASSWORD)
    async with api.maker() as s:
        org = await auth.organization(s)
        s.add(User(
            organization_id=org.id, email="PRIYA@cgvak.com", full_name="dup", role="aiops",
            password_hash=h.password_hash, salt=h.salt, n=h.n, r=h.r, p=h.p,
        ))
        with pytest.raises(IntegrityError):
            await s.commit()
