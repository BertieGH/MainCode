"""Extraction, wired to the end of a research run.

`extract_signals` was written, tested and called by nothing: research stored
evidence and stopped, so the Signals tab on every account read 0 beside a
coverage table full of passages. This is the step that reads them.

Two rules it must not break. Extraction is the *last* thing a run does, so a
failure there costs the signals and never the evidence — the next run can
interpret it again. And the guard still owns invariant 1: a conclusion citing
evidence that does not exist is dropped, and now recorded, not just logged.
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.config import SignalType
from app.models.governance import Evaluation
from app.models.signal import Evidence, Signal
from app.schemas.signal import DroppedSignal, ExtractedSignal, ExtractionOutcome, SignalBatch
from app.services.crm import StubCrmAdapter
from app.services.pipeline import llm_signal_extractor, run_research
from app.services.research import PlannedFamily, ResearchPlan

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
    ),
]


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
    await session.flush()
    contact = Contact(
        account_id=account.id, full_name="Dana Reyes", title="CTO",
        email="dana@meridiancloud.io", email_status="verified",
    )
    session.add_all(
        [
            contact,
            SignalType(key="funding", label="Funding", scope="company",
                       default_ttl_days=300, produced_by=["funding"]),
            SignalType(key="role_change", label="Role change", scope="contact",
                       default_ttl_days=180, produced_by=["leadership"]),
        ]
    )
    await session.flush()
    return account, contact


async def _evidence(session, account_id, excerpt="They raised a Series B.") -> Evidence:
    from app.services.evidence import excerpt_hash, source_hash

    url = f"https://example.com/{uuid.uuid4().hex[:8]}"
    row = Evidence(
        account_id=account_id, source_type="news", source_url=url, excerpt=excerpt,
        source_hash=source_hash(url, None), excerpt_hash=excerpt_hash(url, excerpt),
        raw_status="unavailable",
    )
    session.add(row)
    await session.flush()
    return row


def _one_family() -> ResearchPlan:
    return ResearchPlan(families=[PlannedFamily("funding", ("funding",), ("company",), False)])


async def _found_one(account, family):
    return 1


class TestWhatExtractionIsGiven:
    async def test_the_evidence_held_the_icps_types_and_the_people(self, session, world):
        """Everything held, not only this run's: a funding round found last week
        is part of what this week's hiring means."""
        account, contact = world
        await _evidence(session, account.id, "They raised a Series B.")
        await _evidence(session, account.id, "Dana Reyes was appointed CTO.")
        seen: dict = {}

        async def extractor(acc, evidence, type_keys, contacts):
            seen["excerpts"] = sorted(e.excerpt for e in evidence)
            seen["types"] = list(type_keys)
            seen["people"] = [c.full_name for c in contacts]
            return ExtractionOutcome(stored=2, dropped=[])

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=_found_one,
            company_plan=ResearchPlan(), contacts=[contact],
            run_extraction=extractor, signal_type_keys=("funding", "role_change"),
        )

        assert seen["excerpts"] == ["Dana Reyes was appointed CTO.", "They raised a Series B."]
        assert seen["types"] == ["funding", "role_change"]
        assert seen["people"] == ["Dana Reyes"], "a contact signal could not name anyone"
        assert result.signals_stored == 2

    async def test_no_types_means_no_call(self, session, world):
        """An ICP whose signals name no runnable family has nothing to extract,
        and a model call that can only return "none" is a call worth not making."""
        account, _ = world
        await _evidence(session, account.id)

        async def extractor(*a, **k):
            raise AssertionError("extraction ran with nothing to extract")

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=_found_one,
            company_plan=ResearchPlan(), run_extraction=extractor, signal_type_keys=(),
        )
        assert result.signals_stored == 0

    async def test_nothing_held_means_no_call(self, session, world):
        account, _ = world

        async def extractor(*a, **k):
            raise AssertionError("extraction ran with no evidence")

        await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=_found_one,
            company_plan=ResearchPlan(), run_extraction=extractor,
            signal_type_keys=("funding",),
        )


class TestAFailureCostsTheSignalsNotTheResearch:
    async def test_the_run_is_partial_and_the_evidence_stays(self, session, world):
        account, _ = world
        await _evidence(session, account.id)

        async def extractor(*a, **k):
            raise RuntimeError("model unavailable")

        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=_found_one,
            company_plan=_one_family(), run_extraction=extractor,
            signal_type_keys=("funding",),
        )

        assert "model unavailable" in (result.signals_failed or "")
        assert result.status == "partial", "a failed reading threw away the research"
        assert result.evidence_by_family == {"funding": 1}
        assert await session.scalar(select(func.count()).select_from(Evidence)) >= 1


class TestTheGuardStillOwnsTheInvariant:
    async def test_a_signal_citing_nothing_real_is_dropped_and_recorded(
        self, session, world, monkeypatch
    ):
        """Recorded, not only logged: a rising drop rate is the earliest sign
        an extraction prompt has drifted, and a log line nobody reads is
        indistinguishable from a clean run."""
        from app.services import llm

        account, _ = world
        held = await _evidence(session, account.id)
        batch = SignalBatch(
            signals=[
                ExtractedSignal(
                    signal_type="funding", summary="Series B closed", strength="high",
                    confidence=0.9, observed_at=date(2026, 8, 1),
                    evidence_ids=[str(held.id)],
                ),
                ExtractedSignal(
                    signal_type="funding", summary="Invented round", strength="low",
                    confidence=0.4, observed_at=date(2026, 8, 1),
                    evidence_ids=[str(uuid.uuid4())],
                ),
            ]
        )

        async def fake_extract(session, *, account, evidence, type_keys, contacts=None, client=None):
            return llm.CallResult(parsed=batch)

        monkeypatch.setattr("app.services.stages.extract_signals", fake_extract)
        run_id = uuid.uuid4()
        result = await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=_found_one,
            run_id=run_id, company_plan=ResearchPlan(),
            run_extraction=llm_signal_extractor(session, run_id=run_id),
            signal_type_keys=("funding",),
        )

        assert (result.signals_stored, result.signals_dropped) == (1, 1)
        stored = list((await session.execute(select(Signal))).scalars())
        assert [s.summary for s in stored] == ["Series B closed"]
        assert stored[0].run_id == run_id

        logged = list(
            (
                await session.execute(
                    select(Evaluation).where(Evaluation.subject_id == run_id)
                )
            ).scalars()
        )
        assert len(logged) == 1
        assert logged[0].verdict == "warn", "some signals stored, so not a failed pass"
        assert logged[0].scores["dropped"] == 1
        assert "does not exist" in logged[0].issues[0]["reason"]

    async def test_every_signal_dropped_is_a_failed_pass(self, session, world, monkeypatch):
        from app.services import llm

        account, _ = world
        await _evidence(session, account.id)
        batch = SignalBatch(
            signals=[
                ExtractedSignal(
                    signal_type="funding", summary="Invented", strength="low",
                    confidence=0.4, observed_at=date(2026, 8, 1),
                    evidence_ids=[str(uuid.uuid4())],
                )
            ]
        )

        async def fake_extract(session, *, account, evidence, type_keys, contacts=None, client=None):
            return llm.CallResult(parsed=batch)

        monkeypatch.setattr("app.services.stages.extract_signals", fake_extract)
        run_id = uuid.uuid4()
        await run_research(
            session, account=account, crm=StubCrmAdapter(), run_family=_found_one,
            run_id=run_id, company_plan=ResearchPlan(),
            run_extraction=llm_signal_extractor(session, run_id=run_id),
            signal_type_keys=("funding",),
        )
        logged = (
            await session.execute(select(Evaluation).where(Evaluation.subject_id == run_id))
        ).scalar_one()
        assert logged.verdict == "fail"
        assert await session.scalar(select(func.count()).select_from(Signal)) == 0


def _unused(_: DroppedSignal) -> None:  # keeps the import meaningful to readers
    """`DroppedSignal` is what the guard records; imported here to name it."""
