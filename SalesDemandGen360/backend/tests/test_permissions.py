"""Roles, the user admin screen and the audit trail (`docs/17`, phase 2).

The rule most worth holding is the first one: **every route maps to a module
or is deliberately public.** A route added later and forgotten in
`permissions.RULES` is admin-only — closed, not open — and this test names it.
"""

from __future__ import annotations

import copy
import os
import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.database import get_session
from app.services import access, auth, permissions

#: What the UI sends on every call; see the CSRF check in `main.py`.
UI = {auth.CSRF_HEADER: "1"}
from app.services.permissions import DEFAULT_GRID, refusal, rule_for

#: Answer without a session, by design. Anything else here is a finding.
PUBLIC = {
    ("GET", "/api/health"),
    ("GET", "/api/health/ready"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/password"),
    ("POST", "/api/lgm/inbox/{token}"),
}


def _all_routes() -> list[tuple[str, str]]:
    from app.main import create_app

    spec = create_app().openapi()
    return [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops]


# --------------------------------------------------------------------------
# the map — no database
# --------------------------------------------------------------------------
def test_every_route_belongs_to_a_module_or_is_deliberately_public():
    unmapped = [
        f"{m} {p}" for m, p in _all_routes() if (m, p) not in PUBLIC and rule_for(m, p) is None
    ]
    assert unmapped == [], "add these to permissions.RULES: " + ", ".join(unmapped)


def test_the_irreversible_routes_carry_their_action():
    assert rule_for("POST", "/api/campaigns/{campaign_id}/execute").action == "approve_send"
    assert rule_for("POST", "/api/sequences/{sequence_id}/decision").action == "approve_send"
    assert rule_for("POST", "/api/campaigns/{campaign_id}/approval/accept-sample").action == "approve_send"
    assert rule_for("DELETE", "/api/campaigns/{campaign_id}").action == "delete_campaign"
    assert rule_for("POST", "/api/lists/{list_id}/run-research").action == "paid_research"


@pytest.mark.parametrize(
    ("role", "method", "path", "allowed"),
    [
        # Only DemandGen (and admin) sends.
        ("demandgen", "POST", "/api/campaigns/{campaign_id}/execute", True),
        ("marketing", "POST", "/api/campaigns/{campaign_id}/execute", False),
        ("aiops", "POST", "/api/campaigns/{campaign_id}/execute", False),
        # Marketing writes drafts but cannot approve them.
        ("marketing", "POST", "/api/sequences/{sequence_id}/drafts/write", True),
        ("marketing", "POST", "/api/sequences/{sequence_id}/decision", False),
        # Promoting a queue is queue work: Marketing views queues only.
        ("marketing", "POST", "/api/campaigns", False),
        ("demandgen", "POST", "/api/campaigns", True),
        # AIOps tunes models; others read them.
        ("aiops", "PUT", "/api/config/llm/{scenario}", True),
        ("marketing", "PUT", "/api/config/llm/{scenario}", False),
        ("marketing", "GET", "/api/config/llm", True),
        # Keys and people are admin's alone.
        ("demandgen", "GET", "/api/config/credentials", False),
        ("aiops", "GET", "/api/users", False),
        ("admin", "PUT", "/api/config/credentials", True),
        # Readable by anyone signed in; never writable through the shared rule.
        ("marketing", "GET", "/api/config/readiness", True),
        ("marketing", "GET", "/api/cadence-shapes", True),
        ("marketing", "POST", "/api/cadence-shapes", False),
        # Not in the map at all: closed.
        ("demandgen", "GET", "/api/something-new", False),
        ("admin", "GET", "/api/something-new", True),
    ],
)
def test_the_default_grid(role, method, path, allowed):
    assert (refusal(DEFAULT_GRID, role, method, path) is None) is allowed


def test_a_refusal_says_what_was_missing():
    assert refusal(DEFAULT_GRID, "marketing", "POST", "/api/campaigns/{campaign_id}/execute") == (
        "Your role can't approve & send to LGM."
    )
    assert refusal(DEFAULT_GRID, "marketing", "PUT", "/api/config/llm/{scenario}") == (
        "Your role can't change Model & Prompts config."
    )


def test_admin_is_not_in_the_grid_so_no_grid_can_lock_admin_out():
    empty = {"modules": {}, "actions": {}}
    assert refusal(empty, "admin", "PUT", "/api/roles") is None
    assert permissions.effective(empty, "admin")["modules"]["users"] == "edit"


def test_a_malformed_grid_is_refused_not_trimmed():
    good = copy.deepcopy(DEFAULT_GRID)
    assert permissions.validate_grid(good) == {
        "modules": good["modules"],
        "actions": {r: sorted(a) for r, a in good["actions"].items()},
    }
    for mutate in (
        lambda g: g["modules"]["aiops"].update(prompts="edit"),         # unknown module
        lambda g: g["modules"]["aiops"].pop("lists"),                   # missing module
        lambda g: g["modules"]["aiops"].update(lists="write"),          # unknown level
        lambda g: g["actions"]["aiops"].append("send_everything"),      # unknown action
        lambda g: g["modules"].update(admin={}),                        # admin in the grid
    ):
        bad = copy.deepcopy(DEFAULT_GRID)
        mutate(bad)
        with pytest.raises(ValueError):
            permissions.validate_grid(bad)


def test_reviewer_id_is_the_user_once_there_is_one():
    class U:
        id = uuid.uuid4()

    assert access.reviewer_id(None) == "bertie"
    assert access.reviewer_id(U()) == str(U.id)


async def test_users_need_a_signed_in_admin_even_with_auth_off(client):
    """Everything else is open to anonymous callers until phase 3. Not this:
    an anonymous admin created now would outlive the switch."""
    assert get_settings().auth_required is False
    r = await client.post("/api/users", json={"email": "x@y.z", "full_name": "x", "role": "admin", "password": "p" * 12})
    assert r.status_code == 401
    assert (await client.put("/api/roles", json={"grid": {}})).status_code == 401


# --------------------------------------------------------------------------
# through the API — real database
# --------------------------------------------------------------------------
needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
PW = "correct horse battery"


@pytest.fixture
async def api(app):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=UI) as c:
        c.maker = maker  # type: ignore[attr-defined]
        c.app = app  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _user(maker, email, role):
    async with maker() as s:
        u = await auth.create_user(s, email=email, full_name=email.split("@")[0].title(), role=role, password=PW)
        await s.commit()
        return u.id


@asynccontextmanager
async def _as(api, email, password=PW):
    """A second client signed in as someone else, sharing the database."""
    async with AsyncClient(transport=ASGITransport(app=api.app), base_url="http://test", headers=UI) as c:
        r = await c.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        yield c


async def _audit(maker, action):
    from app.models.identity import AuditLog

    async with maker() as s:
        return (await s.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()


@pytest.mark.db
@needs_db
async def test_a_role_is_refused_with_a_reason_and_allowed_where_it_may(api):
    await _user(api.maker, "divya@cgvak.com", "marketing")
    async with _as(api, "divya@cgvak.com") as divya:
        r = await divya.post(f"/api/campaigns/{uuid.uuid4()}/execute")
        assert r.status_code == 403
        assert "approve & send" in r.json()["detail"]
        assert (await divya.get("/api/campaigns")).status_code == 200
        assert (await divya.get("/api/config/credentials")).status_code == 403


@pytest.mark.db
@needs_db
async def test_an_admin_manages_people_and_every_change_is_audited(api):
    await _user(api.maker, "bert@cgvak.com", "admin")
    async with _as(api, "bert@cgvak.com") as bert:
        made = await bert.post("/api/users", json={
            "email": "Arun@cgvak.com", "full_name": "Arun K.", "role": "aiops", "password": PW,
        })
        assert made.status_code == 201, made.text
        arun_id = made.json()["id"]
        assert made.json()["email"] == "arun@cgvak.com"

        dup = await bert.post("/api/users", json={"email": "ARUN@cgvak.com", "full_name": "x", "role": "aiops", "password": PW})
        assert dup.status_code == 422

        async with _as(api, "arun@cgvak.com") as arun:
            assert (await arun.get("/api/auth/me")).status_code == 200

            role = await bert.patch(f"/api/users/{arun_id}", json={"role": "demandgen"})
            assert role.json()["role"] == "demandgen"

            reset = await bert.post(f"/api/users/{arun_id}/password", json={"password": "a different one"})
            assert reset.status_code == 200
            # A reset ends the sessions they hold.
            assert (await arun.get("/api/auth/me")).status_code == 401

        async with _as(api, "arun@cgvak.com", "a different one") as arun:
            off = await bert.post(f"/api/users/{arun_id}/deactivate")
            assert off.json()["status"] == "deactivated"
            assert (await arun.get("/api/auth/me")).status_code == 401

        listed = await bert.get("/api/users")
        assert [u["email"] for u in listed.json()] == ["bert@cgvak.com", "arun@cgvak.com"]

    for action in ("user.created", "user.role_changed", "user.password_set", "user.deactivated"):
        rows = await _audit(api.maker, action)
        assert len(rows) == 1, action
        assert rows[0].actor_label == "bert@cgvak.com"
    # The fact of a reset, never the password.
    (reset_row,) = await _audit(api.maker, "user.password_set")
    assert reset_row.detail is None


@pytest.mark.db
@needs_db
async def test_the_last_admin_cannot_be_removed_and_nobody_changes_their_own_role(api):
    bert_id = await _user(api.maker, "bert@cgvak.com", "admin")
    async with _as(api, "bert@cgvak.com") as bert:
        assert (await bert.patch(f"/api/users/{bert_id}", json={"role": "marketing"})).status_code == 409
        assert (await bert.post(f"/api/users/{bert_id}/deactivate")).status_code == 409

        other = (await bert.post("/api/users", json={"email": "suresh@cgvak.com", "full_name": "Suresh", "role": "admin", "password": PW})).json()
        async with _as(api, "suresh@cgvak.com") as suresh:
            # Two admins: one may now remove the other — but still not themselves.
            assert (await suresh.post(f"/api/users/{bert_id}/deactivate")).status_code == 200
            assert (await suresh.post(f"/api/users/{other['id']}/deactivate")).status_code == 409


@pytest.mark.db
@needs_db
async def test_a_non_admin_cannot_reach_users_or_roles(api):
    await _user(api.maker, "priya@cgvak.com", "demandgen")
    async with _as(api, "priya@cgvak.com") as priya:
        assert (await priya.get("/api/users")).status_code == 403
        assert (await priya.put("/api/roles", json={"grid": DEFAULT_GRID})).status_code == 403


@pytest.mark.db
@needs_db
async def test_saving_the_grid_makes_a_new_version_that_takes_effect(api):
    await _user(api.maker, "bert@cgvak.com", "admin")
    await _user(api.maker, "divya@cgvak.com", "marketing")
    async with _as(api, "bert@cgvak.com") as bert, _as(api, "divya@cgvak.com") as divya:
        before = await divya.post(f"/api/campaigns/{uuid.uuid4()}/execute")
        assert before.status_code == 403

        grid = copy.deepcopy(DEFAULT_GRID)
        grid["actions"]["marketing"].append("approve_send")
        saved = await bert.put("/api/roles", json={"grid": grid})
        assert saved.status_code == 200, saved.text
        # The DB had no row (tests truncate), so the first save is version 1.
        assert saved.json()["version"] == 1
        assert saved.json()["saved_by"] == "Bert"

        after = await divya.post(f"/api/campaigns/{uuid.uuid4()}/execute")
        assert after.status_code != 403  # past the gate; the campaign itself does not exist

        grid["actions"]["marketing"] = ["paid_research"]
        again = await bert.put("/api/roles", json={"grid": grid})
        assert again.json()["version"] == 2
        versions = (await bert.get("/api/roles/versions")).json()
        assert [(v["version"], v["is_active"]) for v in versions] == [(2, True), (1, False)]

        bad = copy.deepcopy(grid)
        bad["modules"]["aiops"]["lists"] = "write"
        assert (await bert.put("/api/roles", json={"grid": bad})).status_code == 422

    assert len(await _audit(api.maker, "roles.saved")) == 2
