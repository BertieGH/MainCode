"""What came back: the webhook, the poller, and the one row they agree on.

Outreach was write-only until this. The interesting behaviour is not storing a
message — it is who the message is matched to, what happens when it cannot be,
and the fact that the same message arriving twice by two routes is one row.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account, Contact
from app.models.campaign import OutreachCampaign, OutreachSequence
from app.models.execution import OutreachEvent
from app.services import lgm_events

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]


def tag() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


async def world(session, *, lead_id="lead-77"):
    """One enrolled person, as execution leaves them."""
    account = Account(name=f"Datadog {tag()}", domain=f"dd-{tag()}.example", resolution_status="resolved")
    session.add(account)
    await session.flush()
    contact = Contact(
        account_id=account.id, full_name="Enrico Bergamo", title="CTO",
        email=f"e{tag()}@{account.domain}", email_status="verified",
    )
    campaign = OutreachCampaign(label=f"EIA {tag()}", status="executing")
    session.add_all([contact, campaign])
    await session.flush()
    sequence = OutreachSequence(
        contact_id=contact.id, campaign_id=campaign.id, status="executing",
        lgm_lead_id=lead_id, lgm_campaign_id="lgm-camp-1",
    )
    session.add(sequence)
    await session.flush()
    return account, contact, campaign, sequence


def inbox_message(**over) -> dict:
    """An inbox event shaped the way LGM posts one."""
    body = {
        "type": "MESSAGE_RECEIVED",
        "channel": "LINKEDIN",
        "direction": "received",
        "messageId": f"msg-{tag()}",
        "conversationId": "conv-1",
        "campaignId": "lgm-camp-1",
        "createdAt": "2026-09-20T09:15:00.000Z",
        "message": {"content": "Thanks for reaching out, happy to talk next week."},
        "lead": {"id": "lead-77", "proEmail": "someone@else.example"},
    }
    body.update(over)
    return body


class TestMatchingAMessageToAPerson:
    async def test_our_own_id_on_the_lead_is_the_join(self, session):
        _, contact, campaign, sequence = await world(session)
        body = inbox_message(lead={"id": "unknown-lead", "crm_id": str(contact.id)})

        outcome = await lgm_events.ingest_webhook(session, body)
        assert (outcome.stored, outcome.unmatched, outcome.replies) == (1, 0, 1)

        [event] = (await session.execute(select(OutreachEvent))).scalars().all()
        assert event.contact_id == contact.id
        assert event.campaign_id == campaign.id
        assert event.payload["matched_by"] == "crm_id"

    async def test_the_lead_id_matches_when_the_crm_id_is_missing(self, session):
        _, contact, _, _ = await world(session)
        await lgm_events.ingest_webhook(session, inbox_message())
        [event] = (await session.execute(select(OutreachEvent))).scalars().all()
        assert event.contact_id == contact.id and event.payload["matched_by"] == "lead_id"

    async def test_an_unmatched_message_is_still_stored_and_counted(self, session):
        await world(session)
        outcome = await lgm_events.ingest_webhook(
            session, inbox_message(lead={"id": "somebody-else"})
        )
        assert (outcome.stored, outcome.unmatched) == (1, 1)
        assert outcome.orphans == ["somebody-else"]

        [event] = (await session.execute(select(OutreachEvent))).scalars().all()
        assert event.contact_id is None, "a gap a rep can see beats a reply that vanished"


class TestWhatAReplyChanges:
    async def test_the_first_reply_is_stamped_on_the_sequence(self, session):
        _, _, _, sequence = await world(session)
        await lgm_events.ingest_webhook(session, inbox_message(createdAt="2026-09-20T09:15:00.000Z"))
        first = sequence.first_reply_at
        assert first is not None and sequence.last_event_at == first

        await lgm_events.ingest_webhook(session, inbox_message(createdAt="2026-09-21T11:00:00.000Z"))
        assert sequence.first_reply_at == first, "the first reply does not move"
        assert sequence.last_event_at > first

    async def test_a_send_is_recorded_without_counting_as_a_reply(self, session):
        _, _, _, sequence = await world(session)
        outcome = await lgm_events.ingest_webhook(
            session, inbox_message(type="MESSAGE_SENT", direction="sent")
        )
        assert outcome.replies == 0 and sequence.first_reply_at is None
        [event] = (await session.execute(select(OutreachEvent))).scalars().all()
        assert (event.event_type, event.direction) == ("message_sent", "sent")

    async def test_an_event_we_do_not_understand_is_kept_as_a_fact(self, session):
        await world(session)
        await lgm_events.ingest_webhook(session, inbox_message(type="SOMETHING_NEW", direction=""))
        [event] = (await session.execute(select(OutreachEvent))).scalars().all()
        assert event.event_type == "other" and event.payload["type"] == "SOMETHING_NEW"


class TestTheTwoRoutesAgree:
    async def test_the_same_message_pushed_and_polled_is_one_row(self, session):
        _, _, campaign, _ = await world(session)
        body = inbox_message(messageId="msg-shared")
        await lgm_events.ingest_webhook(session, body)

        class OneConversation:
            async def conversations(self, lgm_campaign_id, *, since=None, limit=25):
                return [{"id": "conv-1", "leadId": "lead-77"}]

            async def conversation_messages(self, conversation_id):
                return [{
                    "id": "msg-shared", "channel": "LINKEDIN", "direction": "received",
                    "content": "Thanks for reaching out", "createdAt": "2026-09-20T09:15:00.000Z",
                }]

        # Polled from before that message, so the watermark cannot be what
        # skips it — the dedupe on `external_id` is.
        outcome = await lgm_events.poll_campaign(
            session, campaign, OneConversation(), since=datetime(2026, 9, 1, tzinfo=UTC)
        )
        assert (outcome.stored, outcome.duplicates) == (0, 1)
        assert len((await session.execute(select(OutreachEvent))).scalars().all()) == 1

    async def test_a_step_that_went_out_shows_up_without_a_reply(self, session):
        """A conversation only exists once there is a thread.

        A campaign sending its first step to everybody and hearing nothing back
        has no conversations at all, so the screen looked idle while it was
        working perfectly. The lead's own log is what LGM actually did.
        """
        _, contact, campaign, _ = await world(session)

        class WithLogs:
            async def conversations(self, lgm_campaign_id, *, since=None, limit=25):
                return []

            async def conversation_messages(self, conversation_id):
                return []

            async def lead_logs(self, lead_id, *, limit=100, skip=0):
                return [{
                    "id": "log-1", "type": "EMAIL_SENT", "status": "SUCCESS",
                    "channel": "EMAIL", "message": "Step 1 sent",
                    "createdAt": "2026-09-21T09:00:00.000Z", "campaignId": "lgm-camp-1",
                }]

        outcome = await lgm_events.poll_campaign(session, campaign, WithLogs())
        assert (outcome.stored, outcome.replies) == (1, 0)
        [event] = (await session.execute(select(OutreachEvent))).scalars().all()
        assert (event.event_type, event.direction) == ("message_sent", "sent")
        assert event.contact_id == contact.id and event.preview == "Step 1 sent"

    async def test_a_failed_step_is_recorded_as_a_failure_not_a_send(self, session):
        """"Nothing happened" and "we tried and LGM could not" are different
        problems, and only one of them is the rep's to fix."""
        _, _, campaign, _ = await world(session)

        class Failing:
            async def conversations(self, lgm_campaign_id, *, since=None, limit=25):
                return []

            async def conversation_messages(self, conversation_id):
                return []

            async def lead_logs(self, lead_id, *, limit=100, skip=0):
                return [{
                    "id": "log-2", "type": "EMAIL_SENT", "status": "FAILED",
                    "channel": "EMAIL", "message": "mailbox rejected",
                    "createdAt": "2026-09-21T09:00:00.000Z",
                }]

        await lgm_events.poll_campaign(session, campaign, Failing())
        [event] = (await session.execute(select(OutreachEvent))).scalars().all()
        assert event.event_type == "failed" and event.direction is None

    async def test_an_adapter_without_logs_still_syncs(self, session):
        """The stub has no `lead_logs`; a sync must not fail because of it."""
        _, _, campaign, _ = await world(session)

        class Old:
            async def conversations(self, lgm_campaign_id, *, since=None, limit=25):
                return []

            async def conversation_messages(self, conversation_id):
                return []

        outcome = await lgm_events.poll_campaign(session, campaign, Old())
        assert outcome.stored == 0

    async def test_polling_resumes_from_the_newest_event_it_holds(self, session):
        _, _, campaign, _ = await world(session)
        await lgm_events.ingest_webhook(session, inbox_message(createdAt="2026-09-20T09:15:00.000Z"))
        watermark = await lgm_events.last_seen(session, campaign.id)
        assert watermark == datetime(2026, 9, 20, 9, 15, tzinfo=UTC)

        asked: list = []

        class Recording:
            async def conversations(self, lgm_campaign_id, *, since=None, limit=25):
                asked.append(since)
                return []

            async def conversation_messages(self, conversation_id):
                return []

        await lgm_events.poll_campaign(session, campaign, Recording(), since=watermark)
        assert asked == [watermark], "the whole inbox is not re-read on every sync"

    async def test_messages_at_or_before_the_watermark_are_skipped(self, session):
        _, _, campaign, _ = await world(session)
        since = datetime.now(UTC) - timedelta(hours=1)

        class Old:
            async def conversations(self, lgm_campaign_id, *, since=None, limit=25):
                return [{"id": "conv-9", "leadId": "lead-77"}]

            async def conversation_messages(self, conversation_id):
                return [{
                    "id": "msg-old", "channel": "EMAIL", "direction": "received",
                    "content": "older than the watermark",
                    "createdAt": (since - timedelta(minutes=5)).isoformat(),
                }]

        outcome = await lgm_events.poll_campaign(session, campaign, Old(), since=since)
        assert outcome.stored == 0


@pytest.fixture
async def api():
    from app.api.deps import get_session
    from app.main import create_app

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


class TestTheReceiver:
    async def test_a_wrong_token_is_refused_and_says_nothing(self, api):
        r = await api.post("/api/lgm/inbox/not-the-token", json=inbox_message())
        assert r.status_code == 404
        assert "token" not in r.text.lower(), "a prober learns nothing from the answer"

    async def test_the_right_token_stores_the_event_and_the_screen_shows_it(self, api):
        from app.models.config import IntegrationCredential
        from app.services import crypto

        token = "test-token-" + tag()
        async with api.maker() as s:
            _, contact, campaign, _ = await world(s)
            s.add(
                IntegrationCredential(
                    provider="lgm", credential_type="webhook_secret",
                    value_encrypted=crypto.encrypt(token), last_four=token[-4:], status="valid",
                )
            )
            await s.commit()
            ids = {"campaign": campaign.id, "contact": contact.id}

        posted = await api.post(f"/api/lgm/inbox/{token}", json=inbox_message())
        assert posted.status_code == 202 and posted.json()["stored"] == 1

        activity = (await api.get(f"/api/campaigns/{ids['campaign']}/activity")).json()
        assert (activity["received"], activity["people_replied"]) == (1, 1)
        [event] = activity["events"]
        assert event["contact_name"] == "Enrico Bergamo"
        assert event["preview"].startswith("Thanks for reaching out")
        assert (event["received_via"], event["matched_by"]) == ("webhook", "lead_id")
