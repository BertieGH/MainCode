"""A signal type that carries its own search, and types that share one.

Research ran a closed set of families defined in code, so wanting a new thing
found meant a deploy — and the set was closed for a good reason: a family name
no agent runs is indistinguishable from one that ran and found nothing.

Moving the instruction onto the type removes the deploy without reopening that
hole, because the instruction *is* the runner. What it introduces instead is
cost: one call per type, most of them reading the same pages. `search_group` is
the answer, and these tests are mostly about those two things — that a type can
be found at all, and that finding several does not cost several searches.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.config import SignalType
from app.services.research import (
    GROUP_SEARCH,
    TYPE_SEARCH,
    build_plan,
    merged_instruction,
    search_brief,
)

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


def a_type(key, **over) -> SignalType:
    fields = {
        "key": key, "label": key.replace("_", " ").title(), "scope": "company",
        "default_ttl_days": 120, "produced_by": [], "status": "active",
    }
    fields.update(over)
    return SignalType(**fields)


async def plan_for(session, *types):
    session.add_all(types)
    await session.flush()
    return await build_plan(session)


class TestATypeCanCarryItsOwnSearch:
    async def test_it_is_planned_without_any_family(self, session):
        plan = await plan_for(
            session,
            a_type("budget_cycle", search_instruction="Public mention of a fiscal year end."),
        )
        assert plan.keys == [f"{TYPE_SEARCH}budget_cycle"]
        planned = plan.families[0]
        assert planned.feeds == ("budget_cycle",)
        assert planned.instruction == "Public mention of a fiscal year end."
        assert planned.type_owned is True

    async def test_a_source_and_an_instruction_both_run(self, session):
        """An instruction beside a source is an exception, not a replacement.

        Sources decide what gets opened and extraction reads every document
        against every type, so most types need no words of their own. The ones
        that do need them *as well*: a filing only found by name is missed by a
        sweep of the ordinary places, and dropping the instruction because a
        source was also claimed would silently lose the thing it was for.
        """
        plan = await plan_for(
            session,
            a_type("launch", produced_by=["company_site"], search_instruction="Named filings."),
        )
        assert plan.keys == ["company_site", "type:launch"]
        assert plan.family("company_site").type_owned is False
        assert plan.family("type:launch").instruction == "Named filings."

    async def test_a_type_with_neither_never_runs_and_is_named(self, session):
        """Registering a type before deciding how to find it is allowed. What
        is not allowed is it disappearing: an unrunnable type must not read as
        a prospect nobody could find anything about."""
        plan = await plan_for(session, a_type("someday"))
        assert plan.keys == []
        assert plan.orphan_types == ["someday"]

    async def test_paused_types_are_left_out(self, session):
        plan = await plan_for(
            session,
            a_type("paused_one", status="paused", paused_at=__import__("datetime").datetime.now(
                __import__("datetime").UTC
            ), search_instruction="something"),
        )
        assert plan.keys == []


class TestGroupedTypesShareOneSearch:
    async def test_three_types_one_call(self, session):
        plan = await plan_for(
            session,
            a_type("product_launch", search_group="announcements",
                   search_instruction="Launches and GA announcements."),
            a_type("partnership", search_group="announcements",
                   search_instruction="Partnerships and integrations."),
            a_type("award", search_group="announcements",
                   search_instruction="Awards and list placements."),
        )
        assert plan.keys == [f"{GROUP_SEARCH}announcements"], "three calls where one would do"
        planned = plan.families[0]
        assert planned.feeds == ("award", "partnership", "product_launch")

    async def test_the_brief_names_every_type_in_the_group(self, session):
        """A prose merge quietly drops the third one, so the brief is a list
        and each line is labelled with the type it answers."""
        types = [
            a_type("product_launch", search_group="announcements",
                   search_instruction="Launches and GA announcements."),
            a_type("partnership", search_group="announcements",
                   search_instruction="Partnerships and integrations."),
        ]
        brief = merged_instruction(types)
        assert "product_launch" in brief and "partnership" in brief
        assert "Launches and GA announcements." in brief
        assert "Partnerships and integrations." in brief
        assert brief.count("\n- ") == 2

    async def test_one_member_is_just_its_own_instruction(self):
        only = a_type("solo", search_instruction="Just this.")
        assert merged_instruction([only]) == "Just this."

    async def test_ungrouped_types_keep_their_own_searches(self, session):
        plan = await plan_for(
            session,
            a_type("a_type_one", search_group="shared", search_instruction="One."),
            a_type("a_type_two", search_group="shared", search_instruction="Two."),
            a_type("loner", search_instruction="Alone."),
        )
        assert sorted(plan.keys) == [f"{GROUP_SEARCH}shared", f"{TYPE_SEARCH}loner"]


class TestTheRunnerReadsTheBriefBack:
    """The runner is handed a key and nothing else, the same as a family
    runner. Reading the brief back also means the instruction that runs is the
    one on the row now, not the one planning happened to see."""

    async def test_a_group_key_rebuilds_the_brief(self, session):
        await plan_for(
            session,
            a_type("alpha", search_group="feeds", search_instruction="Alpha things."),
            a_type("beta", search_group="feeds", search_instruction="Beta things."),
        )
        brief = await search_brief(session, f"{GROUP_SEARCH}feeds")
        assert brief["feeds"] == ["alpha", "beta"]
        assert "Alpha things." in brief["instruction"]
        assert brief["label"] == "feeds"

    async def test_a_type_key_rebuilds_the_brief(self, session):
        await plan_for(session, a_type("solo_one", search_instruction="Only this."))
        brief = await search_brief(session, f"{TYPE_SEARCH}solo_one")
        assert brief["instruction"] == "Only this."
        assert brief["feeds"] == ["solo_one"]

    async def test_a_family_key_is_not_one_of_ours(self, session):
        assert await search_brief(session, "funding") is None

    async def test_a_group_nobody_is_in_any_more_is_none(self, session):
        assert await search_brief(session, f"{GROUP_SEARCH}gone") is None


class TestTheKeysCannotCollide:
    async def test_a_type_named_after_a_family_keeps_its_own_coverage(self, session):
        """There is already a `funding` family *and* a `funding` type. Without
        the prefix their coverage rows would be one row, and "the funding
        search found nothing" would become unanswerable."""
        plan = await plan_for(
            session,
            a_type("funding", search_instruction="Rounds and investors."),
        )
        assert plan.keys == [f"{TYPE_SEARCH}funding"]
        assert plan.keys != ["funding"]
