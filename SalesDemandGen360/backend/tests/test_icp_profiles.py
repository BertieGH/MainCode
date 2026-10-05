"""ICP profiles: shared, versioned, and never linked to nothing.

Three rules this file holds, each a design decision rather than an
implementation detail:

**A profile and its links are created together.** Created separately, an ICP
could exist linked to no service between two requests — a state the model says
cannot occur, and one nothing downstream could read.

**A definition is versioned, never edited.** An enrichment run records the
version it read. Editing in place would make "why were these contacts chosen?"
unanswerable the moment somebody widened the profile.

**Deleting is refused once an account list has used it.** That run has to stay
able to say who it was looking for. Leaving a *service* with no ICP is fine: a
service is what you sell, and who to sell it to is chosen on the ICP.

Against the real test database, because the whole subject is link tables and a
partial unique index. A stub session that answered these queries would be
asserting my idea of the SQL rather than the schema's behaviour.
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_session
from app.main import create_app

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set — these write real config rows",
    ),
]


@pytest.fixture
async def api():
    """A client bound to the real test database, plus the services to link to.

    Services are seeded here rather than assumed: `_clean_database` truncates
    everything before each `db` test, so an ICP has nothing to link to unless
    this puts it there — and an ICP with no service cannot be created at all.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.config import ServiceCatalog

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as seed:
        seed.add_all(
            [
                ServiceCatalog(
                    code="qa_engineering", name="QA", description="QA outsourcing"
                ),
                ServiceCatalog(code="EIA", name="EIA", description="Intelligence"),
            ]
        )
        await seed.commit()

    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _create(api, name, *, services=("qa_engineering",), definition=None):
    return await api.post(
        "/api/config/icp-profiles",
        json={
            "name": name,
            "definition": definition or {},
            "service_codes": list(services),
        },
    )


async def _names(api) -> dict[str, dict]:
    r = await api.get("/api/config/icp-profiles")
    return {p["name"]: p for p in r.json()}


class TestCreation:
    async def test_a_profile_arrives_with_its_first_version_and_links(self, api):
        r = await api.post(
            "/api/config/icp-profiles",
            json={
                "name": "Eng-led SaaS",
                "description": "50-500, engineering buys",
                "definition": {"industries": ["SaaS"]},
                "service_codes": ["qa_engineering"],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["version"] == 1
        assert body["definition"] == {"industries": ["SaaS"]}
        assert body["service_codes"] == ["qa_engineering"]
        assert body["list_count"] == 0

    async def test_an_icp_linked_to_nothing_is_refused(self, api):
        """An ICP that sells nothing is a note, not configuration."""
        r = await _create(api, "Orphan", services=())
        assert r.status_code == 422
        assert "Orphan" not in await _names(api)

    async def test_an_unknown_service_is_refused_not_skipped(self, api):
        """Skipping would link fewer services than asked and report success."""
        r = await _create(api, "Typo", services=("qa_engineering", "qa_enginering"))
        assert r.status_code == 422
        assert "QA_ENGINERING" in r.text.upper()
        assert "Typo" not in await _names(api)

    async def test_a_duplicate_name_is_refused(self, api):
        assert (await _create(api, "Twice")).status_code == 201
        assert (await _create(api, "Twice")).status_code == 409


class TestVersioning:
    async def test_a_new_definition_becomes_a_new_version(self, api):
        pid = (
            await _create(api, "Versioned", definition={"industries": ["SaaS"]})
        ).json()["id"]

        r = await api.put(
            f"/api/config/icp-profiles/{pid}",
            json={"definition": {"industries": ["SaaS", "Fintech"]}},
        )
        assert r.status_code == 200
        assert r.json()["version"] == 2
        assert r.json()["definition"]["industries"] == ["SaaS", "Fintech"]

    async def test_only_one_version_is_ever_active(self, api):
        """The partial unique index enforces it; this proves the write order.

        Deactivate has to land before insert — inserting first violates the
        index. Getting it wrong leaves a profile with two active definitions
        and no way to say which one a run read.
        """
        pid = (await _create(api, "Churned")).json()["id"]
        for n in range(2, 6):
            r = await api.put(
                f"/api/config/icp-profiles/{pid}", json={"definition": {"n": n}}
            )
            assert r.status_code == 200, r.text
            assert r.json()["version"] == n
        assert (await _names(api))["Churned"]["definition"] == {"n": 5}

    async def test_a_missing_profile_is_404(self, api):
        r = await api.put(
            f"/api/config/icp-profiles/{uuid.uuid4()}", json={"definition": {}}
        )
        assert r.status_code == 404


class TestLinks:
    async def test_services_can_be_replaced(self, api):
        pid = (await _create(api, "Relinked")).json()["id"]
        r = await api.put(
            f"/api/config/icp-profiles/{pid}/services",
            json={"service_codes": ["EIA", "qa_engineering"]},
        )
        assert r.status_code == 200
        assert sorted(r.json()["service_codes"]) == ["EIA", "qa_engineering"]

    async def test_the_set_cannot_be_emptied(self, api):
        pid = (await _create(api, "Keeps one")).json()["id"]
        r = await api.put(
            f"/api/config/icp-profiles/{pid}/services", json={"service_codes": []}
        )
        assert r.status_code == 422
        assert (await _names(api))["Keeps one"]["service_codes"] == ["qa_engineering"]


class TestDeletion:
    async def test_an_unused_profile_can_be_deleted(self, api):
        """Nothing references it, so it has no history to protect."""
        await _create(api, "Keeper", services=("qa_engineering", "EIA"))
        pid = (await _create(api, "Spare")).json()["id"]
        r = await api.delete(f"/api/config/icp-profiles/{pid}")
        assert r.status_code == 204, r.text
        assert "Spare" not in await _names(api)

    async def test_a_service_may_be_left_with_no_icp(self, api):
        """It used to be refused. A service needs no ICP of its own now — the
        ICP picks the products/services it is for — so deleting a service's
        only ICP strands nothing."""
        pid = (await _create(api, "Only one", services=("qa_engineering",))).json()[
            "id"
        ]
        r = await api.delete(f"/api/config/icp-profiles/{pid}")
        assert r.status_code == 204, r.text
        assert "Only one" not in await _names(api)


class TestAServiceSaysWhoSignsOff:
    """`economic_buyer` replaced `target_personas`: one line of context about
    who signs off, broadly. The people to reach are an ICP's buyer personas."""

    async def test_a_service_is_created_with_its_economic_buyer(self, api):
        r = await api.post(
            "/api/config/services",
            json={"code": "data", "name": "Data", "description": "Pipelines",
                  "economic_buyer": "  CFO / Head of Data  "},
        )
        assert r.status_code == 201, r.text
        assert r.json()["economic_buyer"] == "CFO / Head of Data"
        assert "target_personas" not in r.json()

    async def test_a_service_can_be_edited_but_not_recoded(self, api):
        r = await api.put(
            "/api/config/services/EIA",
            json={"economic_buyer": "CIO", "description": "Intelligence, amplified"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["code"], body["economic_buyer"], body["description"]) == (
            "EIA", "CIO", "Intelligence, amplified",
        )
        assert body["name"] == "EIA", "a field not sent is left alone"

    async def test_a_blank_economic_buyer_is_stored_as_nothing(self, api):
        await api.put("/api/config/services/EIA", json={"economic_buyer": "CIO"})
        r = await api.put("/api/config/services/EIA", json={"economic_buyer": "   "})
        assert r.json()["economic_buyer"] is None

    async def test_editing_an_unknown_service_is_404(self, api):
        r = await api.put("/api/config/services/NOPE", json={"name": "x"})
        assert r.status_code == 404


class TestTheBuyerTrack:
    """Which buyer an ICP is for, and why a typo must not be silent.

    The definition is a free JSON document, so an unrecognised key is normally
    harmless. `track` is not: `strategy_synthesis` and `outreach_drafting`
    branch on it, and a value they do not know falls through to "no track
    stated" — safe, and silent. "enterprize" would cost every draft on that
    list its register with nothing anywhere saying so.
    """

    def test_the_two_tracks_are_accepted(self):
        from app.schemas.config import ICP_TRACKS, IcpDefinitionIn

        for track in ICP_TRACKS:
            row = IcpDefinitionIn(definition={"track": track})
            assert row.definition["track"] == track

    def test_an_unknown_track_is_refused(self):
        import pytest as _pytest

        from app.schemas.config import IcpDefinitionIn

        with _pytest.raises(ValueError, match="track must be one of"):
            IcpDefinitionIn(definition={"track": "enterprize"})

    def test_no_track_is_allowed(self):
        """Not every list has decided, and "neither" is a real answer — the
        prompts fall back to arguing from the evidence."""
        from app.schemas.config import IcpDefinitionIn

        row = IcpDefinitionIn(definition={"industries": ["Insurance"]})
        assert "track" not in row.definition

    def test_other_keys_are_still_free(self):
        """Only `track` is closed. The rest of the document stays open, which
        is what lets a rep describe an ICP this form has no field for."""
        from app.schemas.config import IcpDefinitionIn

        row = IcpDefinitionIn(definition={"anything": "at all", "track": "enterprise"})
        assert row.definition["anything"] == "at all"
