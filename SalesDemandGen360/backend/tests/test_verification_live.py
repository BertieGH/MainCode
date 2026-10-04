"""Enrichment against a real database, because the stubs hid a crash.

`test_verification.py` drives this code with hand-written stand-ins —
`_StubProfile`, `_StubIcp`, `_Session`. They are fast and they proved the
waterfall logic, but a stub's `.name` is a plain attribute. The real
`IcpProfileVersion.profile` is a lazy relationship, and reading it outside the
async context raises `MissingGreenlet`.

So `verify_list` crashed with a 500 on **every list**, and the whole suite was
green. The failure reached a person before it reached a test.

These tests exist to keep the parts that only a real session can prove:
relationships that must be eagerly loaded, and counts that must come from SQL.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set — these need a real session",
    ),
]


@pytest.fixture
async def world():
    """A service with one ICP, a list, and one account carrying no contacts."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from sqlalchemy import update

    from app.models.account import Account, AccountList, AccountListMember
    from app.models.config import (
        EnrichmentConfig,
        IcpProfile,
        IcpProfileVersion,
        IntegrationCredential,
        ServiceCatalog,
        service_icp_link,
    )

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as s:
        service = ServiceCatalog(
            code=f"svc{uuid.uuid4().hex[:6]}", name="Svc", description="d"
        )
        profile = IcpProfile(name=f"Profile {uuid.uuid4().hex[:6]}")
        lst = AccountList(label="live", source="csv", created_by="tests")
        account = Account(name="Acme", resolution_status="resolved")
        s.add_all([service, profile, lst, account])
        await s.flush()
        s.add_all([
            IcpProfileVersion(
                icp_profile_id=profile.id,
                definition={"personas": [{"buying_role": "technical_buyer",
                                          "titles": ["CTO"]}]},
                version=1,
                is_active=True,
            ),
            AccountListMember(list_id=lst.id, account_id=account.id),
        ])
        await s.execute(
            service_icp_link.insert().values(
                service_id=service.id, icp_profile_id=profile.id
            )
        )
        # A configured, credentialled provider. Without one the pass is
        # blocked before it ever reaches the question these tests ask —
        # correctly, since being unable to run at all outranks having nothing
        # to run on, but it masks the message under test.
        await s.execute(update(EnrichmentConfig).values(is_active=False))
        s.add(
            EnrichmentConfig(
                provider_order=["apollo"],
                required_fields=["email"],
                resolution_order=["apollo_org"],
                version=9_000 + int(uuid.uuid4().int % 1000),
                is_active=True,
            )
        )
        existing = await s.scalar(
            select(IntegrationCredential).where(
                IntegrationCredential.provider == "apollo",
                IntegrationCredential.credential_type == "api_key",
            )
        )
        if existing is None:
            s.add(
                IntegrationCredential(
                    provider="apollo",
                    credential_type="api_key",
                    value_encrypted=b"unused - a client is injected",
                    last_four="test",
                    status="valid",
                )
            )
        else:
            existing.status = "valid"

        await s.commit()
        ids = {
            "service": service.id,
            "profile": profile.id,
            "profile_name": profile.name,
            "list": lst.id,
            "account": account.id,
        }

    async with maker() as s:
        yield s, ids
    await engine.dispose()


class TestRelationshipsAreLoadedBeforeTheyAreRead:
    async def test_the_run_names_the_icp_it_read(self, world):
        """The crash, as a test.

        `report.icp_versions` reads `version.profile.name`. Left lazy, that
        attribute access raises `MissingGreenlet` and the endpoint 500s — for
        any list, with any service, on the first line that touches it.
        """
        from app.services import verification

        session, ids = world
        report = await verification.verify_list(
            session, list_id=ids["list"], service_id=ids["service"]
        )
        assert report.icp_versions == [(ids["profile_name"], 1)]

    async def test_resolve_targeting_returns_versions_with_their_profile(self, world):
        """The eager load, asserted where it is configured rather than only
        where it is consumed — so moving the read does not silently lose it."""
        from app.services import verification

        session, ids = world
        service, versions = await verification.resolve_targeting(
            session, service_id=ids["service"]
        )
        assert service.id == ids["service"]
        # No await, no greenlet: this is the access that used to explode.
        assert versions[0].profile.name == ids["profile_name"]


class _Reachable:
    """A provider that is never actually asked anything.

    Injected only so the "no provider could be called" check passes: that
    check fires first and rightly so — being unable to run at all outranks
    having nothing to run on — but it would otherwise mask the message these
    tests are about.
    """

    from app.services.providers import Provider as _P

    name = _P.APOLLO

    async def enrich(self, **kw):  # pragma: no cover — never reached
        raise AssertionError("a provider was called for a list with no contacts")


class TestAnEmptyListSaysWhichKindOfEmpty:
    async def test_a_list_with_no_contacts_explains_itself(self, world):
        """"0 checked" reads as a broken run. It is a missing step.

        Enrichment works on contacts; an account-grain import creates none. A
        rep who uploaded a list of companies needs to be told that, not shown
        a zero.
        """
        from app.services import verification

        session, ids = world
        report = await verification.verify_list(
            session, list_id=ids["list"], service_id=ids["service"],
            clients={"apollo": _Reachable()},
        )
        assert report.checked == 0
        assert report.blocked is not None
        assert "no contacts yet" in report.blocked
        assert "contact columns" in report.blocked

    async def test_a_fully_verified_list_says_something_different(self, world):
        """Both report zero. They mean opposite things."""
        from app.models.account import Contact
        from app.services import verification

        session, ids = world
        session.add(
            Contact(
                account_id=ids["account"],
                full_name="Dana Reid",
                title="CTO",
                email="dana@acme.example",
                email_status="verified",
            )
        )
        await session.flush()

        report = await verification.verify_list(
            session, list_id=ids["list"], service_id=ids["service"],
            clients={"apollo": _Reachable()},
        )
        assert report.checked == 0
        assert "already has a verified address" in report.blocked
        assert "no contacts yet" not in report.blocked


class TestTheEndpointItself:
    """The service worked and the route did not.

    `VerifyOut` asked for `icp_version: int` — a field the report stopped
    having when a run learned to target several ICPs. Every call to
    `verify-contacts` raised `AttributeError` and returned a 500, so the Enrich
    button did nothing, and every service-level test still passed. A response
    model is code; nothing had exercised it.
    """

    async def test_enrichment_returns_a_report_rather_than_a_500(self, world):
        from httpx import ASGITransport, AsyncClient

        from app.api.deps import get_session
        from app.main import create_app

        session, ids = world
        app = create_app()

        async def _session():
            yield session

        app.dependency_overrides[get_session] = _session
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/api/lists/{ids['list']}/verify-contacts",
                params={"service_id": str(ids["service"])},
            )
        app.dependency_overrides.clear()

        # The regression was a 500 from the response model, not whether a
        # provider happened to be reachable — this database's credential is a
        # placeholder, so the pass reports itself blocked, which is correct.
        assert r.status_code == 200, r.text
        body = r.json()
        # Pinned before the provider check, so it survives a blocked run and
        # the answer stays explainable after the ICP moves on.
        assert body["icp_versions"] == [{"name": ids["profile_name"], "version": 1}]
        assert "ran" in body and "blocked" in body

    async def test_a_service_with_no_icp_is_a_409_not_a_crash(self, world):
        from httpx import ASGITransport, AsyncClient

        from app.api.deps import get_session
        from app.main import create_app
        from app.models.config import ServiceCatalog

        session, ids = world
        bare = ServiceCatalog(
            code=f"bare{uuid.uuid4().hex[:6]}", name="Bare", description="d"
        )
        session.add(bare)
        await session.flush()

        app = create_app()

        async def _session():
            yield session

        app.dependency_overrides[get_session] = _session
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/api/lists/{ids['list']}/verify-contacts",
                params={"service_id": str(bare.id)},
            )
        app.dependency_overrides.clear()

        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "service_not_ready"
