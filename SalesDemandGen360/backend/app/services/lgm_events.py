"""What came back from La Growth Machine, by webhook or by polling.

Outreach was write-only: we enrolled a lead and never heard anything again. LGM
reports back two ways, and both land here as `outreach_event` rows of the same
shape:

* **The inbox webhook** pushes LinkedIn and email messages as they happen. It
  needs a public URL, and LGM signs nothing — so the URL carries an
  unguessable token and the payload is treated as a claim, not a fact.
* **Polling** `/conversations/search` and `/campaigns/:id/statsleads` needs no
  public URL at all. It is the fallback for a laptop install, and the
  reconciler for anything the webhook dropped: `external_id` is unique per
  source, so the same message pushed and then polled is one row.

**Everything here is provider data, read as data.** A message body is written
by a prospect, or by whoever can post to the webhook URL; it reaches a prompt
only as quoted content and never as instruction (invariant 10).

Matching a message to a person goes by `crm_id` first, then by lead id, then
by address. The last is a guess and is recorded as one.

**In practice the lead id is what matches.** `crm_id` was meant to be the exact
tier — our own contact id, written onto the lead at enrolment, surviving a
change of address. LGM accepts the field and does not store it: a lead written
with one reads it back empty, while an unrecognised spelling like `crmId` is
refused outright, so the field is real and simply not ours to set. It is still
sent and still tried first, in case a future lead carries one from their own
CRM integrations — but the tier that actually does the work is the lead id we
record at execution.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Contact
from app.models.campaign import OutreachCampaign, OutreachSequence
from app.models.execution import OutreachEvent

log = logging.getLogger(__name__)

#: How LGM names a channel, in our words.
CHANNELS = {"EMAIL": "email", "LINKEDIN": "linkedin", "TWITTER": "twitter", "GOOGLE": "email"}
#: Its log types, as far as they map. Anything else is kept as `other` with the
#: payload — an unknown event is still a fact about this person.
EVENT_TYPES = {
    "MESSAGE_SENT": "message_sent",
    "MESSAGE_RECEIVED": "message_received",
    "REPLY": "message_received",
    "UNSUBSCRIBE": "unsubscribed",
    "STATUS": "status_change",
    # Lead-log vocabulary. LGM names the action rather than the message.
    "EMAIL_SENT": "message_sent",
    "LINKEDIN_MESSAGE_SENT": "message_sent",
    "LINKEDIN_INVITE_SENT": "message_sent",
    "LINKEDIN_VISIT": "other",
    "CONNECT": "other",
}


@dataclass
class Ingested:
    stored: int = 0
    duplicates: int = 0
    unmatched: int = 0
    replies: int = 0
    #: Lead ids we could not tie to anybody here, so a rep can see the gap
    #: rather than wonder why a reply never appeared.
    orphans: list[str] = field(default_factory=list)


def _when(value) -> datetime:
    """LGM sends ISO strings in some places and epoch milliseconds in others."""
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(UTC)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _text(value, limit: int = 300) -> str | None:
    if not isinstance(value, str):
        return None
    flat = " ".join(value.split())
    return flat[:limit] or None


async def match_person(
    session: AsyncSession, *, crm_id=None, lead_id=None, email=None, linkedin_url=None
) -> tuple[Contact | None, str]:
    """Who this is about, and how confidently we know.

    `crm_id` is our own contact id, written onto the lead when it was enrolled:
    exact, and it survives the person changing address. A lead id matched
    against a sequence is nearly as good. An address is a guess — the same
    person may hold two — and is reported as one.
    """
    if crm_id:
        try:
            contact = await session.get(Contact, uuid.UUID(str(crm_id)))
        except ValueError:
            contact = None
        if contact is not None:
            return contact, "crm_id"

    if lead_id:
        sequence = (
            await session.execute(
                select(OutreachSequence)
                .where(OutreachSequence.lgm_lead_id == str(lead_id))
                .order_by(OutreachSequence.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if sequence is not None and sequence.contact_id:
            return await session.get(Contact, sequence.contact_id), "lead_id"

    for column, value in ((Contact.email, email), (Contact.linkedin_url, linkedin_url)):
        if not value:
            continue
        found = (
            await session.execute(select(Contact).where(column == str(value)).limit(2))
        ).scalars().all()
        # Two people on one address is not a match, it is a coin toss.
        if len(found) == 1:
            return found[0], "address"
    return None, "none"


async def _sequence_for(session: AsyncSession, contact: Contact | None, lead_id=None):
    """The sequence this event belongs to: the live one, else the most recent."""
    if lead_id:
        by_lead = (
            await session.execute(
                select(OutreachSequence)
                .where(OutreachSequence.lgm_lead_id == str(lead_id))
                .order_by(OutreachSequence.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if by_lead is not None:
            return by_lead
    if contact is None:
        return None
    rows = (
        await session.execute(
            select(OutreachSequence)
            .where(OutreachSequence.contact_id == contact.id)
            .order_by(OutreachSequence.created_at.desc())
        )
    ).scalars().all()
    live = [s for s in rows if s.status in ("executing", "paused")]
    return (live or rows or [None])[0]


async def record(
    session: AsyncSession,
    *,
    received_via: str,
    event_type: str,
    occurred_at: datetime,
    external_id: str | None = None,
    channel: str | None = None,
    direction: str | None = None,
    lead_id: str | None = None,
    lgm_campaign_id: str | None = None,
    conversation_id: str | None = None,
    preview: str | None = None,
    payload: dict | None = None,
    crm_id: str | None = None,
    email: str | None = None,
    linkedin_url: str | None = None,
    into: Ingested | None = None,
) -> OutreachEvent | None:
    """Store one event, or nothing when we have already seen it."""
    into = into or Ingested()
    if external_id:
        seen = (
            await session.execute(
                select(OutreachEvent).where(
                    OutreachEvent.source == "lgm", OutreachEvent.external_id == str(external_id)
                )
            )
        ).scalar_one_or_none()
        if seen is not None:
            into.duplicates += 1
            return None

    contact, how = await match_person(
        session, crm_id=crm_id, lead_id=lead_id, email=email, linkedin_url=linkedin_url
    )
    sequence = await _sequence_for(session, contact, lead_id)
    if contact is None and sequence is None:
        into.unmatched += 1
        if lead_id:
            into.orphans.append(str(lead_id))

    event = OutreachEvent(
        source="lgm",
        received_via=received_via,
        external_id=str(external_id) if external_id else None,
        event_type=event_type,
        channel=channel,
        direction=direction,
        occurred_at=occurred_at,
        lgm_lead_id=str(lead_id) if lead_id else None,
        lgm_campaign_id=lgm_campaign_id,
        conversation_id=conversation_id,
        preview=preview,
        contact_id=contact.id if contact else None,
        sequence_id=sequence.id if sequence else None,
        campaign_id=sequence.campaign_id if sequence else None,
        payload={**(payload or {}), "matched_by": how},
    )
    session.add(event)
    into.stored += 1

    if sequence is not None:
        if sequence.last_event_at is None or sequence.last_event_at < occurred_at:
            sequence.last_event_at = occurred_at
        if event_type == "message_received":
            into.replies += 1
            if sequence.first_reply_at is None:
                sequence.first_reply_at = occurred_at
    await session.flush()
    return event


# ==========================================================================
# the webhook
# ==========================================================================
def _lead_of(body: dict) -> dict:
    lead = body.get("lead") or body.get("contact") or {}
    return lead if isinstance(lead, dict) else {}


async def ingest_webhook(session: AsyncSession, body: dict, *, into: Ingested | None = None) -> Ingested:
    """One inbox event, as LGM posts it.

    Shapes vary between LinkedIn and email and between their own versions, so
    every field is read defensively and the whole body is kept: an event we
    half-understand is still evidence that something happened to this person.
    """
    into = into or Ingested()
    if not isinstance(body, dict):
        return into

    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    lead = _lead_of(body)
    raw_type = str(body.get("type") or body.get("event") or message.get("type") or "").upper()
    direction_raw = str(body.get("direction") or message.get("direction") or "").lower()
    direction = "received" if direction_raw in ("received", "inbound", "in") else (
        "sent" if direction_raw in ("sent", "outbound", "out") else None
    )
    event_type = EVENT_TYPES.get(raw_type) or (
        "message_received" if direction == "received"
        else "message_sent" if direction == "sent" else "other"
    )
    if direction is None and event_type in ("message_received", "message_sent"):
        direction = "received" if event_type == "message_received" else "sent"

    channel_raw = str(body.get("channel") or message.get("channel") or "").upper()
    await record(
        session,
        received_via="webhook",
        event_type=event_type,
        occurred_at=_when(
            body.get("createdAt") or body.get("date") or message.get("createdAt")
        ),
        external_id=body.get("messageId") or message.get("id") or body.get("id"),
        channel=CHANNELS.get(channel_raw, channel_raw.lower() or None),
        direction=direction,
        lead_id=lead.get("id") or body.get("leadId"),
        lgm_campaign_id=str(body.get("campaignId") or "") or None,
        conversation_id=str(body.get("conversationId") or "") or None,
        preview=_text(message.get("content") or body.get("content") or body.get("preview")),
        payload=body,
        crm_id=lead.get("crm_id") or lead.get("crmId") or body.get("crm_id"),
        email=lead.get("proEmail") or lead.get("email") or body.get("leadEmail"),
        linkedin_url=lead.get("linkedinUrl"),
        into=into,
    )
    return into


# ==========================================================================
# polling
# ==========================================================================
async def poll_campaign(
    session: AsyncSession, campaign: OutreachCampaign, adapter, *, since: datetime | None = None
) -> Ingested:
    """Ask LGM what has happened, for the campaigns this one enrolled into.

    Needs no public URL, which is what makes it the honest default: a laptop
    install has nowhere for a webhook to land. It is also the reconciler — a
    webhook that was down for an hour leaves a hole nothing else would close.
    """
    into = Ingested()
    lgm_ids = {
        s.lgm_campaign_id
        for s in (
            await session.execute(
                select(OutreachSequence).where(
                    OutreachSequence.campaign_id == campaign.id,
                    OutreachSequence.lgm_campaign_id.is_not(None),
                )
            )
        ).scalars()
        if s.lgm_campaign_id
    }
    if not lgm_ids:
        return into

    if since is None:
        since = await last_seen(session, campaign.id)
    for lgm_id in sorted(lgm_ids):
        for conversation in await adapter.conversations(lgm_id, since=since):
            messages = await adapter.conversation_messages(str(conversation.get("id")))
            for message in messages:
                when = _when(message.get("createdAt"))
                if since is not None and when <= since:
                    continue
                direction = "received" if message.get("direction") == "received" else "sent"
                channel_raw = str(message.get("channel") or "").upper()
                await record(
                    session,
                    received_via="poll",
                    event_type="message_received" if direction == "received" else "message_sent",
                    occurred_at=when,
                    external_id=message.get("id"),
                    channel=CHANNELS.get(channel_raw, channel_raw.lower() or None),
                    direction=direction,
                    lead_id=conversation.get("leadId"),
                    lgm_campaign_id=lgm_id,
                    conversation_id=str(conversation.get("id")),
                    preview=_text(message.get("content")),
                    payload={"conversation": conversation, "message": message},
                    into=into,
                )
    # Conversations only show what turned into a thread. A step that went out
    # and has not been answered leaves no conversation at all, so a campaign
    # that is sending perfectly well looks idle. The lead's own log is the
    # record of what LGM actually did, step by step — including failures, which
    # no conversation would ever show.
    await _poll_lead_logs(session, campaign, adapter, since=since, into=into)

    log.info(
        "lgm_events.polled campaign=%s stored=%d duplicates=%d unmatched=%d",
        campaign.id, into.stored, into.duplicates, into.unmatched,
    )
    return into


async def _poll_lead_logs(
    session: AsyncSession, campaign: OutreachCampaign, adapter, *, since, into: Ingested
) -> None:
    """What LGM did to each of this campaign's people, from their own logs.

    Optional: an adapter without `lead_logs` (the stub, or an older one) simply
    contributes nothing rather than failing the sync.
    """
    if not hasattr(adapter, "lead_logs"):
        return

    sequences = list(
        (
            await session.execute(
                select(OutreachSequence).where(
                    OutreachSequence.campaign_id == campaign.id,
                    OutreachSequence.lgm_lead_id.is_not(None),
                )
            )
        ).scalars()
    )
    for sequence in sequences:
        try:
            entries = await adapter.lead_logs(str(sequence.lgm_lead_id), limit=100)
        except Exception as exc:  # noqa: BLE001 - one lead must not fail the sync
            log.warning(
                "lgm_events.lead_logs_failed sequence=%s err=%s", sequence.id, exc
            )
            continue
        for entry in entries:
            when = _when(entry.get("createdAt"))
            if since is not None and when <= since:
                continue
            raw_type = str(entry.get("type") or "").upper()
            status = str(entry.get("status") or "").upper()
            event_type = EVENT_TYPES.get(raw_type, "other")
            # A failed action is not a send. Recorded as its own fact, because
            # "nothing happened" and "we tried and LGM could not" are
            # different problems with different fixes.
            if status in ("FAILED", "ERROR"):
                event_type = "failed"
            channel_raw = str(entry.get("channel") or "").upper()
            await record(
                session,
                received_via="poll",
                event_type=event_type,
                occurred_at=when,
                external_id=entry.get("id"),
                channel=CHANNELS.get(channel_raw, channel_raw.lower() or None),
                direction="sent" if event_type == "message_sent" else None,
                lead_id=sequence.lgm_lead_id,
                lgm_campaign_id=entry.get("campaignId") or sequence.lgm_campaign_id,
                preview=_text(entry.get("message")),
                payload={"lead_log": entry},
                into=into,
            )


async def last_seen(session: AsyncSession, campaign_id) -> datetime | None:
    """The newest event we hold for this campaign — where polling resumes."""
    return await session.scalar(
        select(OutreachEvent.occurred_at)
        .where(OutreachEvent.campaign_id == campaign_id)
        .order_by(OutreachEvent.occurred_at.desc())
        .limit(1)
    )
