"""Deleting an account list — the storage behaviour underneath the rule.

These exercise SQL directly. The **policy** — what may be deleted and what it
takes with it — is tested through the endpoint in `test_list_delete_policy.py`,
because it is a decision about dependencies rather than about rows.

The rule those tests enforce, in short: a list goes when nothing downstream
depends on it, and it takes with it only the accounts no other list holds.
That is a change from "only while it is empty", which was right for a worked
list and wrong for one imported five minutes ago with the columns mapped badly.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, AccountList, AccountListMember

pytestmark = pytest.mark.db

TEST_DB = os.getenv("TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


async def _list(session, label="Q3 DevOps ISVs") -> AccountList:
    row = AccountList(label=label, source="manual", created_by="bertie")
    session.add(row)
    await session.flush()
    return row


async def _member_count(session, list_id) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(AccountListMember)
        .where(AccountListMember.list_id == list_id)
    )


@requires_db
class TestAnEmptyListIsJustATypo:
    async def test_a_list_with_no_members_can_be_deleted(self, session):
        row = await _list(session, "ll")
        assert await _member_count(session, row.id) == 0

        await session.delete(row)
        await session.flush()

        assert (
            await session.execute(select(AccountList).where(AccountList.label == "ll"))
        ).scalar_one_or_none() is None

    async def test_the_member_count_is_what_decides(self, session):
        """Not the source, and not how old it is. A list imported from CSV that
        matched nothing is as empty as one created by mistake."""
        empty_csv = AccountList(label="bad import", source="csv", created_by="bertie")
        session.add(empty_csv)
        await session.flush()

        assert await _member_count(session, empty_csv.id) == 0


@requires_db
class TestAPopulatedListKeepsItsProvenance:
    async def test_a_list_holding_an_account_reports_a_count(self, session):
        lst = await _list(session)
        account = Account(name="Meridian Cloud", domain="MERIDIANCLOUD.IO")
        session.add(account)
        await session.flush()
        session.add(AccountListMember(list_id=lst.id, account_id=account.id))
        await session.flush()

        assert await _member_count(session, lst.id) == 1

    async def test_removing_membership_does_not_cascade_to_the_account(self, session):
        """The FK does not delete accounts; the endpoint decides that.

        Membership is a copy, not ownership — nothing in the schema removes an
        account when a list drops it. The endpoint deletes accounts that end up
        on *no* list, which is a policy choice made there and tested there.
        """
        lst = await _list(session)
        account = Account(name="Meridian Cloud", domain="MERIDIANCLOUD.IO")
        session.add(account)
        await session.flush()
        session.add(AccountListMember(list_id=lst.id, account_id=account.id))
        await session.flush()

        await session.execute(
            AccountListMember.__table__.delete().where(AccountListMember.list_id == lst.id)
        )
        await session.delete(lst)
        await session.flush()

        assert (
            await session.execute(select(Account).where(Account.name == "Meridian Cloud"))
        ).scalar_one_or_none() is not None
