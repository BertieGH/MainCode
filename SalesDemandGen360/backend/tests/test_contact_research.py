"""Contact research: the ICP's people, beside their company.

Research looked at companies only, so the ICP's contact signals — a role
change, a public statement of pain — could never be found. This is the pass
that looks for them: per account, up to three people who match the ICP's
buyer personas and can be written to, one search call per family for all of
them, and everything recorded per person so the reuse window works person by
person.

The rule that matters most is identity. A passage the model tags with an id we
did not send is dropped, never filed under the nearest match: a namesake's job
change recorded as a prospect's is worse than no evidence at all.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, AccountList, Contact, account_list_icp
from app.models.config import IcpProfile, IcpProfileVersion, SignalType
from app.models.research import ResearchCoverage
from app.models.signal import Evidence
from app.services.crm import StubCrmAdapter
from app.services.pipeline import ContactFamilyOutcome, llm_contact_runner, run_research
from app.services.research import (
    ResearchPlan,
    build_plan,
    contacts_to_research,
    plan_for_list,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
    ),
]

#: What the Default ICP's personas expand to.
TARGETS = ("economic_buyer", "ceo", "technical_buyer", "cto", "cio", "it head")


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
async def world(session):
    account = Account(
        name="Meridian Cloud", domain="meridiancloud.io", resolution_status="resolved"
    )
    session.add(account)
    session.add_all(
        [
            SignalType(key="funding", label="Funding", scope="company",
                       default_ttl_days=300, produced_by=["funding"]),
            SignalType(key="mgt_change", label="Leadership change", scope="company",
                       default_ttl_days=180, produced_by=["leadership"]),
            SignalType(key="role_change", label="Role change", scope="contact",
                       default_ttl_days=180, produced_by=["leadership"]),
        ]
    )
    await session.flush()

    def person(name, title, *, status="verified", linkedin=None):
        c = Contact(
            account_id=account.id, full_name=name, title=title, email_status=status,
            email=f"{name.split()[0].lower()}@meridiancloud.io", linkedin_url=linkedin,
        )
        session.add(c)
        return c

    people = {
        "cto": person("Dana Reyes", "CTO"),
        "cio": person("Sam Lee", "CIO", linkedin="https://www.linkedin.com/in/samlee"),
        "sales": person("Kim Ode", "VP of Sales"),
        "ceo": person("Ari Moss", "CEO", status="unverified"),
        "it": person("Lou Tan", "Head of IT"),
        "eng": person("Pat Ng", "VP of Engineering"),
    }
    await session.flush()
    return account, people


async def coverage(session, run_id) -> list[ResearchCoverage]:
    return list(
        (
            await session.execute(
                select(ResearchCoverage).where(ResearchCoverage.run_id == run_id)
            )
        ).scalars()
    )


class TestWhoIsResearched:
    async def test_verified_and_in_persona_only_linkedin_first_three_at_most(
        self, session, world
    ):
        """VP of Sales is out of persona; the CEO has no verified email. Of the
        rest, a LinkedIn profile first — it tells this person from a namesake —
        then seniority."""
        account, _ = world
        picked = await contacts_to_research(session, account.id, targets=TARGETS, limit=3)
        assert [c.full_name for c in picked] == ["Sam Lee", "Dana Reyes", "Pat Ng"]

    async def test_an_icp_naming_nobody_chooses_nobody(self, session, world):
        account, _ = world
        assert await contacts_to_research(session, account.id, targets=()) == []


class TestThePlanFollowsTheList:
    async def _list(self, session, definition: dict):
        lst = AccountList(label="EIA push", source="manual", created_by="tests")
        icp = IcpProfile(name=f"ICP {uuid.uuid4().hex[:6]}")
        session.add_all([lst, icp])
        await session.flush()
        version = IcpProfileVersion(
            icp_profile_id=icp.id, definition=definition, version=1, is_active=True
        )
        session.add(version)
        await session.execute(
            account_list_icp.insert().values(list_id=lst.id, icp_profile_id=icp.id)
        )
        await session.flush()
        return lst, version

    async def test_the_icps_signals_decide_both_passes(self, session, world):
        lst, version = await self._list(
            session,
            {
                "signals_that_matter": ["role_change"],
                "personas": [{"buying_role": "technical_buyer", "titles": ["CTO"]}],
            },
        )
        plan = await plan_for_list(session, lst.id)
        assert plan.company.keys == [], "researched company families nobody asked for"
        assert plan.contact.keys == ["leadership"]
        assert "cto" in plan.targets
        assert plan.icp_version_ids == [str(version.id)]

    async def test_an_icp_naming_no_signals_falls_back_to_the_registry(self, session, world):
        lst, _ = await self._list(session, {"industries": ["SaaS"]})
        plan = await plan_for_list(session, lst.id)
        assert plan.company.keys == ["funding", "leadership"]
        assert plan.contact.keys == ["leadership"]


class TestOneRunCoversTheCompanyAndEachPerson:
    async def _plans(self, session):
        return (
            await build_plan(session, scope="company"),
            await build_plan(session, scope="contact"),
        )

    async def test_one_call_per_family_for_everyone_recorded_per_person(
        self, session, world
    ):
        account, p = world
        company_plan, contact_plan = await self._plans(session)
        calls: list = []

        async def company(acc, family):
            return 1

        async def people(acc, family, who):
            calls.append((family, [c.full_name for c in who]))
            return ContactFamilyOutcome(
                stored_by_contact={p["cto"].id: 2},
                searched_by_contact={p["cio"].id: ("CIO appointment news",)},
            )

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=company,
            company_plan=company_plan, contacts=[p["cto"], p["cio"]],
            contact_plan=contact_plan, run_contact_family=people,
        )

        assert calls == [("leadership", ["Dana Reyes", "Sam Lee"])]
        rows = await coverage(session, result.run_id)
        company_rows = {r.family for r in rows if r.contact_id is None}
        person_rows = {r.contact_id: r for r in rows if r.contact_id is not None}
        assert company_rows == {"funding", "leadership"}, "company and person rows collide"
        assert person_rows[p["cto"].id].status == "ran"
        assert person_rows[p["cio"].id].status == "empty"
        assert person_rows[p["cio"].id].not_found == ["CIO appointment news"]
        assert result.contact_evidence == {p["cto"].id: 2, p["cio"].id: 0}
        assert set(result.contacts_researched) == {p["cto"].id, p["cio"].id}
        assert result.status == "complete"

    async def test_a_person_fresh_for_a_family_is_not_asked_about_it(self, session, world):
        account, p = world
        company_plan, contact_plan = await self._plans(session)
        calls: list = []

        async def people(acc, family, who):
            calls.append([c.full_name for c in who])
            return ContactFamilyOutcome()

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(),
            run_family=lambda a, f: _one(), company_plan=ResearchPlan(),
            contacts=[p["cto"], p["cio"]], contact_plan=contact_plan,
            run_contact_family=people, contact_skip={p["cio"].id: {"leadership"}},
        )
        assert calls == [["Dana Reyes"]]
        assert result.contact_reused == 1

    async def test_a_failing_contact_family_leaves_the_run_partial(self, session, world):
        account, p = world
        company_plan, contact_plan = await self._plans(session)

        async def company(acc, family):
            return 1

        async def people(acc, family, who):
            raise RuntimeError("search provider is down")

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=company,
            company_plan=company_plan, contacts=[p["cto"]], contact_plan=contact_plan,
            run_contact_family=people,
        )
        assert result.status == "partial"
        failed = [r for r in await coverage(session, result.run_id) if r.contact_id]
        assert [(r.status, "down" in (r.detail or "")) for r in failed] == [("failed", True)]


class TestTheRealRunnerFilesPerPerson:
    async def test_passages_land_on_their_person_and_strangers_are_dropped(
        self, session, world, monkeypatch
    ):
        from app.schemas.evidence import (
            ContactEvidenceBatch,
            ContactSearch,
            FoundContactEvidence,
        )
        from app.services import llm

        account, p = world
        batch = ContactEvidenceBatch(
            evidence=[
                FoundContactEvidence(
                    source_type="news", source_url="https://example.com/dana",
                    excerpt="Dana Reyes joined Meridian Cloud as CTO.",
                    contact_id=str(p["cto"].id),
                ),
                FoundContactEvidence(
                    source_type="news", source_url="https://example.com/other",
                    excerpt="A different Dana Reyes joined Acme.",
                    contact_id="not-one-we-sent",
                ),
            ],
            searched_for=[ContactSearch(contact_id=str(p["cio"].id), searched=["CIO move"])],
        )

        async def fake_research_contacts(session, *, account, family, people, client=None):
            return llm.CallResult(parsed=batch)

        monkeypatch.setattr("app.services.stages.research_contacts", fake_research_contacts)
        run_id = uuid.uuid4()
        contact_plan = await build_plan(session, scope="contact")
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=lambda a, f: _one(),
            run_id=run_id, company_plan=ResearchPlan(), contacts=[p["cto"], p["cio"]],
            contact_plan=contact_plan,
            run_contact_family=llm_contact_runner(session, run_id=run_id),
        )

        stored = list(
            (await session.execute(select(Evidence).where(Evidence.run_id == run_id))).scalars()
        )
        assert [(e.contact_id, e.family) for e in stored] == [(p["cto"].id, "leadership")]
        cio_row = next(
            r for r in await coverage(session, result.run_id) if r.contact_id == p["cio"].id
        )
        assert "CIO move" in cio_row.not_found
        assert any("not asked about" in n for n in cio_row.not_found)


async def _one() -> int:
    return 1
