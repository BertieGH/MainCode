"""What came back: the webhook LGM posts to, and the poller that catches up.

Three things live here.

* `POST /lgm/inbox/{token}` — the receiver. LGM signs nothing, so the token in
  the path is the credential: unguessable, stored encrypted, compared in
  constant time. A payload that fails it is refused without saying why.
* `POST /campaigns/{id}/sync` — polling, for installations with no public URL
  and as the reconciler after a webhook outage. The same events, deduplicated.
* `GET /campaigns/{id}/activity` — what has happened, for the screen.

**Everything a prospect or a provider sends is data.** Bodies are stored and
displayed as quoted content, never followed as instruction (invariant 10).
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.account import Account, Contact
from app.models.campaign import OutreachCampaign, OutreachSequence
from app.models.execution import OutreachEvent
from app.services import lgm_events

router = APIRouter(tags=["outreach events"])

#: Mounted without the sign-in requirement. LGM is the caller, not a person,
#: and the token in the path is its credential — checked below.
public_router = APIRouter(tags=["outreach events"])

#: Where the token lives. `webhook_secret` already exists as a credential type.
WEBHOOK_PROVIDER = "lgm"
WEBHOOK_KIND = "webhook_secret"


async def _stored_token(session: AsyncSession) -> str | None:
    from app.models.config import IntegrationCredential
    from app.services import crypto

    row = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.provider == WEBHOOK_PROVIDER,
                IntegrationCredential.credential_type == WEBHOOK_KIND,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        return crypto.decrypt(row.value_encrypted).reveal()
    except crypto.CredentialError:
        return None


@public_router.post("/lgm/inbox/{token}", status_code=202)
async def lgm_inbox(
    token: str,
    request: Request,
    body: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
):
    """Receive one inbox event from La Growth Machine.

    Answers 202 for anything it accepts, because a webhook that returns errors
    for events it cannot match gets retried forever — and an unmatched event is
    still stored, which is the point.
    """
    stored = await _stored_token(session)
    if not stored or not hmac.compare_digest(stored, token):
        # No detail: a 404-shaped answer tells a prober nothing about whether
        # the route exists or the token was close.
        raise HTTPException(404, "not found")

    outcome = await lgm_events.ingest_webhook(session, body)
    await session.commit()
    return {
        "stored": outcome.stored,
        "duplicates": outcome.duplicates,
        "unmatched": outcome.unmatched,
    }


class WebhookSetupIn(BaseModel):
    #: Where LGM should post — the public origin of this installation, e.g.
    #: `https://gen360.example.com`. The token is added here, never by hand.
    public_url: str = Field(min_length=8, max_length=300)
    name: str = Field(default="Gen360 replies", max_length=100)


class WebhookOut(BaseModel):
    registered: bool
    url: str | None = None
    webhook_id: str | None = None
    detail: str = ""


class LgmCampaignOut(BaseModel):
    id: str
    name: str
    status: str | None = None
    audience_id: str | None = None
    audience_name: str | None = None
    #: How many leads that audience already holds — the difference between a
    #: campaign built for this and one somebody else is using.
    audience_size: int | None = None


@router.get("/lgm/campaigns", response_model=list[LgmCampaignOut])
async def lgm_campaigns(session: AsyncSession = Depends(get_session)):
    """The campaigns in the connected LGM account, for registering a shape.

    Read-only, and empty rather than an error when no key is stored: the
    registration screen falls back to typing an id, which is all it had before.
    """
    from app.services import lgm_client
    from app.services.lgm import LgmError

    adapter = await lgm_client.from_credentials(session)
    if adapter is None:
        return []
    try:
        rows = await adapter.campaigns()
    except LgmError:
        return []
    out: list[LgmCampaignOut] = []
    for row in rows:
        audience = row.get("audience") or {}
        out.append(
            LgmCampaignOut(
                id=str(row.get("id") or ""),
                name=str(row.get("name") or "(unnamed)"),
                status=row.get("status"),
                audience_id=str(audience.get("id")) if audience.get("id") else None,
                audience_name=audience.get("name") or row.get("audienceName"),
                audience_size=audience.get("size") if isinstance(audience.get("size"), int) else None,
            )
        )
    return [c for c in out if c.id]


@router.get("/lgm/inbox-webhooks", response_model=list[dict])
async def list_inbox_webhooks(session: AsyncSession = Depends(get_session)):
    """What LGM is currently pushing to, whether we registered it or not."""
    from app.services import lgm_client
    from app.services.lgm import LgmError

    adapter = await lgm_client.from_credentials(session)
    if adapter is None:
        return []
    try:
        return await adapter.inbox_webhooks()
    except LgmError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/lgm/inbox-webhooks", response_model=WebhookOut)
async def register_inbox_webhook(
    payload: WebhookSetupIn, session: AsyncSession = Depends(get_session)
):
    """Register this installation's receiver with LGM, minting the token.

    The token is generated here and stored encrypted: it is the whole of the
    webhook's security, since LGM signs nothing, so it is never typed by a
    person and never shown again after this call.
    """
    from app.models.config import IntegrationCredential
    from app.services import crypto, lgm_client
    from app.services.lgm import LgmError

    adapter = await lgm_client.from_credentials(session)
    if adapter is None:
        return WebhookOut(
            registered=False,
            detail=(
                "no La Growth Machine key is stored (or this is a demo installation), so nothing "
                "could be registered"
            ),
        )

    origin = payload.public_url.strip().rstrip("/")
    if not origin.startswith("https://"):
        raise HTTPException(
            422, "the public URL must be https — LGM will not post to an unencrypted endpoint"
        )

    token = secrets.token_urlsafe(32)
    url = f"{origin}/api/lgm/inbox/{token}"
    try:
        result = await adapter.register_inbox_webhook(url=url, name=payload.name)
    except LgmError as exc:
        raise HTTPException(409, str(exc)) from exc

    row = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.provider == WEBHOOK_PROVIDER,
                IntegrationCredential.credential_type == WEBHOOK_KIND,
            )
        )
    ).scalar_one_or_none()
    encrypted = crypto.encrypt(token)
    if row is None:
        session.add(
            IntegrationCredential(
                provider=WEBHOOK_PROVIDER,
                credential_type=WEBHOOK_KIND,
                value_encrypted=encrypted,
                last_four=token[-4:],
                status="valid",
            )
        )
    else:
        row.value_encrypted, row.last_four, row.status = encrypted, token[-4:], "valid"
    await session.commit()

    return WebhookOut(
        registered=True,
        url=url,
        webhook_id=str(result.get("id") or "") or None,
        detail="LGM will post replies here. The token is stored; it is not shown again.",
    )


class SyncOut(BaseModel):
    ran: bool
    blocked: str | None = None
    stored: int = 0
    duplicates: int = 0
    unmatched: int = 0
    replies: int = 0
    orphans: list[str] = Field(default_factory=list)
    since: str | None = None


@router.post("/campaigns/{campaign_id}/sync", response_model=SyncOut)
async def sync_campaign(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Pull everything LGM has for this campaign since the last event we hold."""
    from app.services import lgm_client
    from app.services.lgm import LgmError

    campaign = await session.get(OutreachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")

    adapter = await lgm_client.from_credentials(session)
    if adapter is None:
        return SyncOut(
            ran=False,
            blocked=(
                "no La Growth Machine key is stored (or this is a demo installation), so there is "
                "nothing to sync with"
            ),
        )

    since = await lgm_events.last_seen(session, campaign_id)
    try:
        outcome = await lgm_events.poll_campaign(session, campaign, adapter, since=since)
    except LgmError as exc:
        return SyncOut(ran=False, blocked=str(exc))
    await session.commit()
    return SyncOut(
        ran=True, stored=outcome.stored, duplicates=outcome.duplicates,
        unmatched=outcome.unmatched, replies=outcome.replies, orphans=outcome.orphans[:10],
        since=since.isoformat() if since else None,
    )


class EventOut(BaseModel):
    id: uuid.UUID
    occurred_at: str
    event_type: str
    channel: str | None = None
    direction: str | None = None
    preview: str | None = None
    contact_id: uuid.UUID | None = None
    contact_name: str | None = None
    account_name: str | None = None
    sequence_id: uuid.UUID | None = None
    #: `webhook` or `poll`, and how the person was matched — both are how a
    #: surprising row gets explained.
    received_via: str
    matched_by: str | None = None


class ActivityOut(BaseModel):
    campaign_id: uuid.UUID
    sent: int = 0
    received: int = 0
    people_replied: int = 0
    last_event_at: str | None = None
    events: list[EventOut] = Field(default_factory=list)


@router.get("/campaigns/{campaign_id}/activity", response_model=ActivityOut)
async def campaign_activity(
    campaign_id: uuid.UUID, limit: int = 100, session: AsyncSession = Depends(get_session)
):
    """What has happened to this campaign's people, newest first."""
    if await session.get(OutreachCampaign, campaign_id) is None:
        raise HTTPException(404, "campaign not found")

    rows = (
        await session.execute(
            select(OutreachEvent, Contact, Account)
            .outerjoin(Contact, Contact.id == OutreachEvent.contact_id)
            .outerjoin(Account, Account.id == Contact.account_id)
            .where(OutreachEvent.campaign_id == campaign_id)
            .order_by(OutreachEvent.occurred_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).all()

    sent = await session.scalar(
        select(func.count()).select_from(OutreachEvent).where(
            OutreachEvent.campaign_id == campaign_id, OutreachEvent.direction == "sent"
        )
    )
    received = await session.scalar(
        select(func.count()).select_from(OutreachEvent).where(
            OutreachEvent.campaign_id == campaign_id, OutreachEvent.direction == "received"
        )
    )
    replied = await session.scalar(
        select(func.count()).select_from(OutreachSequence).where(
            OutreachSequence.campaign_id == campaign_id,
            OutreachSequence.first_reply_at.is_not(None),
        )
    )

    events = [
        EventOut(
            id=e.id,
            occurred_at=e.occurred_at.astimezone(UTC).isoformat(),
            event_type=e.event_type,
            channel=e.channel,
            direction=e.direction,
            preview=e.preview,
            contact_id=c.id if c else None,
            contact_name=c.full_name if c else None,
            account_name=a.name if a else None,
            sequence_id=e.sequence_id,
            received_via=e.received_via,
            matched_by=(e.payload or {}).get("matched_by"),
        )
        for e, c, a in rows
    ]
    return ActivityOut(
        campaign_id=campaign_id,
        sent=sent or 0,
        received=received or 0,
        people_replied=replied or 0,
        last_event_at=events[0].occurred_at if events else None,
        events=events,
    )
