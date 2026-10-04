"""A rep pastes what they saw on LinkedIn. Real rows, no model."""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_session
from app.main import create_app

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]

POST = (
    "https://www.linkedin.com/posts/maxkolysh_proxycurl-just-shut-down-after-linkedin-sued-"
    "activity-7351297064502206466-W_4c"
)


@pytest.fixture
async def api():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.account import Account, Contact

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as seed:
        mine = Account(name="Meridian Cloud", resolution_status="resolved")
        other = Account(name="Other Co", resolution_status="resolved")
        seed.add_all([mine, other])
        await seed.flush()
        dana = Contact(account_id=mine.id, full_name="Dana Reid", title="CTO")
        stranger = Contact(account_id=other.id, full_name="Sam Lee", title="CTO")
        seed.add_all([dana, stranger])
        await seed.commit()
        ids = {"account": mine.id, "dana": dana.id, "stranger": stranger.id}

    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.ids = ids  # type: ignore[attr-defined]
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


def url(api) -> str:
    return f"/api/accounts/{api.ids['account']}/pasted-evidence"


class TestAPastedPost:
    async def test_it_is_stored_attributed_and_dated_from_its_link(self, api):
        response = await api.post(url(api), json={
            "text": "We are hiring six QA engineers to speed up our release train.",
            "url": POST, "contact_id": str(api.ids["dana"]),
        })
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["dated_from"] == "post link"
        assert body["evidence"]["observed_at"] == "2025-07-16"
        assert body["evidence"]["source_type"] == "manual"
        assert body["evidence"]["source_name"] == "LinkedIn, pasted by a rep"

        from sqlalchemy import select

        from app.models.signal import Evidence

        async with api.maker() as s:
            row = (await s.execute(select(Evidence))).scalar_one()
        assert (row.author_id, row.capture_method, row.family) == ("rep", "other", "manual")
        assert row.contact_id == api.ids["dana"]

    async def test_a_date_the_rep_gives_wins(self, api):
        response = await api.post(url(api), json={
            "text": "Our CTO spoke about migrating off the legacy monolith.",
            "url": POST, "observed_at": "2025-07-01",
        })
        assert response.json()["dated_from"] == "given"
        assert response.json()["evidence"]["observed_at"] == "2025-07-01"

    async def test_no_link_and_no_date_is_undated_never_today(self, api):
        response = await api.post(url(api), json={"text": "Mentioned a vendor review next quarter."})
        assert response.status_code == 201
        assert response.json()["dated_from"] == "unknown"
        assert response.json()["evidence"]["observed_at"] is None
        assert response.json()["evidence"]["source_name"] == "Pasted by a rep"


class TestWhatIsRefused:
    async def test_a_contact_at_another_company(self, api):
        response = await api.post(url(api), json={
            "text": "A post by someone at a different company.", "contact_id": str(api.ids["stranger"]),
        })
        assert response.status_code == 422

    async def test_the_same_passage_twice(self, api):
        body = {"text": "We are consolidating our cloud vendors this year.", "url": POST}
        assert (await api.post(url(api), json=body)).status_code == 201
        assert (await api.post(url(api), json=body)).status_code == 409

    async def test_a_date_in_the_future(self, api):
        response = await api.post(url(api), json={
            "text": "Something that has not happened yet.", "observed_at": str(date(2999, 1, 1)),
        })
        assert response.status_code == 422

    @pytest.mark.parametrize("body", [{"text": "   short   "}, {"text": "A real sentence here.", "url": "linkedin.com/in/x"}])
    async def test_too_short_or_a_link_without_a_scheme(self, api, body):
        assert (await api.post(url(api), json=body)).status_code == 422

    async def test_an_account_that_does_not_exist(self, api):
        response = await api.post(
            f"/api/accounts/{uuid.uuid4()}/pasted-evidence", json={"text": "A sentence about nobody."}
        )
        assert response.status_code == 404
