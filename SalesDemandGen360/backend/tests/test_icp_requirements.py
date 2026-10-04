"""What readiness asks of the ICPs before anything is enriched or researched.

It used to ask that every service be linked to an ICP. A service no longer
needs one — it is what you sell, and the ICP picks the products/services it is
for. What has to exist instead is **one ICP that is for an active service and
names buyer personas**: enrichment and research pick people by those personas,
and an ICP naming nobody would satisfy a looser check while giving them no one
to look for.
"""

from __future__ import annotations

import os

import pytest

from app.services import readiness

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set — these write real config rows",
    ),
]

PERSONAS = {"personas": [{"buying_role": "technical_buyer", "titles": ["CTO"]}]}


@pytest.fixture
async def maker():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def seed(maker, *, definition: dict | None, service_active: bool = True) -> None:
    """One service and, unless `definition` is None, one ICP for it."""
    from app.models.config import IcpProfile, IcpProfileVersion, ServiceCatalog, service_icp_link

    async with maker() as s:
        svc = ServiceCatalog(code="EIA", name="EIA", description="x", is_active=service_active)
        s.add(svc)
        await s.flush()
        if definition is not None:
            icp = IcpProfile(name="Default")
            s.add(icp)
            await s.flush()
            s.add(IcpProfileVersion(icp_profile_id=icp.id, definition=definition,
                                    version=1, is_active=True))
            await s.execute(service_icp_link.insert().values(
                service_id=svc.id, icp_profile_id=icp.id))
        await s.commit()


async def requirements(maker) -> list[str]:
    async with maker() as s:
        return await readiness._configuration_requirements(s)


class TestWhatReadinessAsksOfTheIcps:
    async def test_a_service_with_no_icp_asks_for_one(self, maker):
        await seed(maker, definition=None)
        [message] = await requirements(maker)
        assert "No ICP is for an active product or service" in message

    async def test_an_icp_naming_nobody_asks_for_buyer_personas(self, maker):
        await seed(maker, definition={"industries": ["SaaS"]})
        [message] = await requirements(maker)
        assert "buyer personas" in message
        assert "Default" in message, "names which ICP needs them"

    async def test_an_icp_only_for_an_inactive_service_does_not_count(self, maker):
        """Nothing will be pitched through a switched-off service."""
        await seed(maker, definition=PERSONAS, service_active=False)
        # No active service at all is its own, earlier message.
        [message] = await requirements(maker)
        assert "No active service" in message

    async def test_an_icp_with_personas_satisfies_it(self, maker):
        await seed(maker, definition=PERSONAS)
        assert await requirements(maker) == []
