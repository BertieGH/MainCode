"""Queues, campaigns, approval and execution.

The write surface for everything between a qualified account and a send. Two
routes here are irreversible and say so in their docstrings: `promote` locks a
queue forever, and `execute` freezes copy on the LGM lead.

Approval endpoints deliberately expose no way to choose a sample. The draw is
server-side and stored; `accept-sample` checks what comes back against what was
drawn. A rep may redraw as often as they like — that is the point of randomness
— but never hand-pick.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.api.deps import requires
from app.database import get_session
from app.models.account import Contact
from app.models.campaign import CampaignQueueContact
from app.models.campaign import (
    CampaignQueue,
    CampaignQueueMember,
    OutreachCampaign,
    OutreachCampaignSource,
    OutreachSequence,
)
from app.models.config import SalesRules
from app.models.content import Draft, Touch
from app.models.context import Qualification
from app.models.execution import ExecutionRecord
from app.models.governance import Approval, ApprovalSample, Evaluation
from app.models.identity import User
from app.models.strategy import StrategyThread
from app.services import access, anchoring, demo
from app.services import preflight as preflight_service
from app.services.approval import (
    Candidate,
    SampleEscalatedError,
    SampleTamperedError,
    accept_sample,
    draw,
    inherit,
    stratify,
)
from app.services.execution import (
    PreflightFailedError,
    execute,
    stop_campaign,
    stop_sequence,
)
from app.services import lgm_client
from app.services.lgm import StubLgmAdapter
from app.services.promotion import (
    QueueLockedError,
    NotEligibleError,
    add_contact,
    add_member,
    MixedTargetsError,
    clone_queue,
    person_of,
    promote,
)

router = APIRouter(tags=["campaigns"])


async def _lgm(session: AsyncSession):
    """The adapter to execute against: the live client, or the stub.

    Demo mode is resolved first and returns the stub whatever is stored — this
    is the one client in the system that can put a message in front of a real
    person, and a sandbox that can send is not a sandbox. With no key stored,
    the stub is returned too: pre-flight already refuses to execute without the
    outreach capability, so this path is only reached in tests.
    """
    if await demo.is_demo(session):
        return StubLgmAdapter()
    live = await lgm_client.from_credentials(session, mode_checked=True)
    return live or StubLgmAdapter()


# --------------------------------------------------------------------------
# queues
# --------------------------------------------------------------------------
class QueueIn(BaseModel):
    label: str = Field(min_length=1)
    description: str | None = None
    #: What everyone in the campaign is approached about, and the ICP it is
    #: built for. The campaign's qualification and strategy are scored against them.
    service_id: uuid.UUID | None = None
    icp_profile_id: uuid.UUID | None = None


class MemberIn(BaseModel):
    account_id: uuid.UUID
    source_list_id: uuid.UUID | None = None
    qualification_id: uuid.UUID | None = None


class QueueMemberOut(BaseModel):
    account_id: uuid.UUID
    account_name: str
    domain: str | None
    source_list_id: uuid.UUID | None
    priority_score: float | None
    priority_band: str | None


@router.post("/queues", status_code=201)
async def create_queue(payload: QueueIn, session: AsyncSession = Depends(get_session)):
    from app.services import campaign_strategy

    if (payload.service_id is None) != (payload.icp_profile_id is None):
        raise HTTPException(422, "choose both a service and an ICP")
    version = None
    if payload.service_id is not None:
        try:
            version = await campaign_strategy.choose_targets(
                session, payload.service_id, payload.icp_profile_id
            )
        except campaign_strategy.NotReadyError as exc:
            raise HTTPException(422, str(exc)) from exc
    row = CampaignQueue(
        label=payload.label, description=payload.description, status="draft",
        service_id=payload.service_id, icp_profile_id=payload.icp_profile_id, icp_version=version,
    )
    session.add(row)
    await session.commit()
    return {"id": str(row.id), "label": row.label, "status": row.status}


@router.get("/queues/{queue_id}/members", response_model=list[QueueMemberOut])
async def queue_members(queue_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    from app.models.account import Account

    rows = (
        await session.execute(
            select(CampaignQueueMember, Account)
            .join(Account, Account.id == CampaignQueueMember.account_id)
            .where(CampaignQueueMember.queue_id == queue_id)
            .order_by(Account.name)
        )
    ).all()

    out = []
    for member, account in rows:
        qual = (
            await session.get(Qualification, member.qualification_id)
            if member.qualification_id
            else None
        )
        if qual is None:
            qual = (
                await session.execute(
                    select(Qualification)
                    .where(Qualification.account_id == account.id)
                    .order_by(Qualification.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        out.append(
            QueueMemberOut(
                account_id=account.id,
                account_name=account.name,
                domain=account.domain,
                source_list_id=member.source_list_id,
                priority_score=float(qual.priority_score) if qual else None,
                priority_band=qual.priority_band if qual else None,
            )
        )
    return out


@router.post("/queues/{queue_id}/members", status_code=201)
async def add_queue_member(
    queue_id: uuid.UUID, payload: MemberIn, session: AsyncSession = Depends(get_session)
):
    try:
        member = await add_member(
            session,
            queue_id=queue_id,
            account_id=payload.account_id,
            source_list_id=payload.source_list_id,
            qualification_id=payload.qualification_id,
            added_by="bertie",
        )
    except QueueLockedError as exc:
        raise HTTPException(409, str(exc)) from exc
    except NotEligibleError as exc:
        raise HTTPException(409, f"not eligible for a queue: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    await session.commit()
    # None means the account was already a member — a queue built from
    # overlapping lists must not double-count.
    return {"added": member is not None}


class BulkMembersIn(BaseModel):
    account_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    #: Provenance stamp only — which list the selection came from.
    source_list_id: uuid.UUID | None = None


class BulkMembersOut(BaseModel):
    added: int = 0
    #: Already in the queue. Not an error: a queue built from overlapping lists
    #: must not double-count, and the rep asked for a state that already holds.
    already: int = 0
    #: Could not be added, each with its reason, so a partial run says what it
    #: left behind instead of reporting a smaller number and nothing else.
    refused: list[dict] = Field(default_factory=list)


@router.post("/queues/{queue_id}/members/bulk", response_model=BulkMembersOut)
async def add_queue_members_bulk(
    queue_id: uuid.UUID,
    payload: BulkMembersIn,
    session: AsyncSession = Depends(get_session),
):
    """Add a selection to a queue, account by account, reporting each outcome.

    Runs on what it can. One account the queue refuses — deleted since the
    screen loaded, say — must not cost the other forty, and must not vanish
    from the count either; it is named in `refused`.

    A **locked** queue refuses the whole call with 409, because that is a fact
    about the queue rather than about any account: it has been promoted to a
    campaign, and nothing may join it after that.
    """
    from app.models.account import Account

    out = BulkMembersOut()
    wanted = list(dict.fromkeys(payload.account_ids))

    # Checked up front, not caught afterwards. `add_member` does not look the
    # account up, so a stale id reaches the INSERT and fails on the foreign
    # key — and a failed statement aborts the whole transaction, taking every
    # account added before it. Found by a live run: one id deleted since the
    # screen loaded turned a forty-account add into a 500 that added nothing.
    existing = {
        r[0]
        for r in (
            await session.execute(select(Account.id).where(Account.id.in_(wanted)))
        ).all()
    }
    for account_id in wanted:
        if account_id not in existing:
            out.refused.append(
                {"account_id": str(account_id), "reason": "account no longer exists"}
            )
            continue
        try:
            member = await add_member(
                session,
                queue_id=queue_id,
                account_id=account_id,
                source_list_id=payload.source_list_id,
                qualification_id=None,
                added_by="bertie",
            )
        except QueueLockedError as exc:
            await session.rollback()
            raise HTTPException(409, str(exc)) from exc
        except NotEligibleError as exc:
            out.refused.append({"account_id": str(account_id), "reason": str(exc)})
            continue
        except ValueError as exc:
            out.refused.append({"account_id": str(account_id), "reason": str(exc)})
            continue
        if member is None:
            out.already += 1
        else:
            out.added += 1

    await session.commit()
    return out


class QueueContactOut(BaseModel):
    contact_id: uuid.UUID
    full_name: str
    title: str | None = None
    account_id: uuid.UUID
    account_name: str
    email: str | None = None
    email_status: str | None = None
    linkedin_url: str | None = None
    #: `email` (verified), `LinkedIn`, or `not reachable` — it may have changed since.
    reachable_by: str
    source_list_id: uuid.UUID | None = None
    #: Their company's rating, read for the ICP this queue is built for.
    qualification_score: float | None = None
    qualification_band: str | None = None
    icp_name: str | None = None
    gate: str = "not_qualified"
    gate_detail: str = ""


@router.get("/queues/{queue_id}/contacts", response_model=list[QueueContactOut])
async def queue_contacts(queue_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """The people chosen for this queue."""
    from app.models.account import Account

    rows = (
        await session.execute(
            select(CampaignQueueContact, Contact, Account)
            .join(Contact, Contact.id == CampaignQueueContact.contact_id)
            .join(Account, Account.id == CampaignQueueContact.account_id)
            .where(CampaignQueueContact.queue_id == queue_id)
            .order_by(Account.name, Contact.full_name)
        )
    ).all()
    from app.api.lists import _ratings

    queue = await session.get(CampaignQueue, queue_id)
    ratings = await _ratings(
        session,
        [a.id for _, _, a in rows],
        [queue.icp_profile_id] if queue and queue.icp_profile_id else None,
    )
    return [
        QueueContactOut(
            **(ratings.get(a.id) or {}),
            contact_id=c.id,
            full_name=c.full_name,
            title=c.title,
            account_id=a.id,
            account_name=a.name,
            email=c.email,
            email_status=c.email_status,
            linkedin_url=c.linkedin_url,
            reachable_by=(
                "email" if c.email and c.email_status == "verified"
                else "LinkedIn" if c.linkedin_url else "not reachable"
            ),
            source_list_id=m.source_list_id,
        )
        for m, c, a in rows
    ]


class BulkContactsIn(BaseModel):
    contact_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    #: Provenance stamp only — which list the selection came from.
    source_list_id: uuid.UUID | None = None


class BulkContactsOut(BaseModel):
    added: int = 0
    already: int = 0
    refused: list[dict] = Field(default_factory=list)


@router.post("/queues/{queue_id}/contacts/bulk", response_model=BulkContactsOut)
async def add_queue_contacts_bulk(
    queue_id: uuid.UUID,
    payload: BulkContactsIn,
    session: AsyncSession = Depends(get_session),
):
    """Choose people for a queue, each outcome reported.

    A person must be reachable (verified email or LinkedIn) and their company
    must pass the queue rule; each refusal is named. A locked queue refuses the
    whole call.
    """
    out = BulkContactsOut()
    wanted = list(dict.fromkeys(payload.contact_ids))
    existing = set(
        (await session.execute(select(Contact.id).where(Contact.id.in_(wanted)))).scalars()
    )
    for contact_id in wanted:
        if contact_id not in existing:
            out.refused.append({"contact_id": str(contact_id), "reason": "contact no longer exists"})
            continue
        try:
            row = await add_contact(
                session, queue_id=queue_id, contact_id=contact_id,
                source_list_id=payload.source_list_id, added_by="bertie",
            )
        except QueueLockedError as exc:
            await session.rollback()
            raise HTTPException(409, str(exc)) from exc
        except (NotEligibleError, ValueError) as exc:
            out.refused.append({"contact_id": str(contact_id), "reason": str(exc)})
            continue
        if row is None:
            out.already += 1
        else:
            out.added += 1
    await session.commit()
    return out


@router.delete("/queues/{queue_id}/contacts/{contact_id}", status_code=204)
async def remove_queue_contact(
    queue_id: uuid.UUID, contact_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    queue = await session.get(CampaignQueue, queue_id)
    if queue is None:
        raise HTTPException(404, "queue not found")
    if queue.status == "locked":
        raise HTTPException(409, f"{queue.label!r} is locked; clone it to make a variant")
    row = (
        await session.execute(
            select(CampaignQueueContact).where(
                CampaignQueueContact.queue_id == queue_id,
                CampaignQueueContact.contact_id == contact_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        account_id = row.account_id
        await session.delete(row)
        await session.flush()
        await anchoring.release(session, [account_id], reason=f"removed from queue {queue.label!r}")
    await session.commit()


@router.delete("/queues/{queue_id}/members/{account_id}", status_code=204)
async def remove_queue_member(
    queue_id: uuid.UUID, account_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    queue = await session.get(CampaignQueue, queue_id)
    if queue is None:
        raise HTTPException(404, "queue not found")
    if queue.status == "locked":
        raise HTTPException(
            409, f"{queue.label!r} is locked; clone it to make a variant"
        )
    await session.execute(
        CampaignQueueMember.__table__.delete().where(
            CampaignQueueMember.queue_id == queue_id,
            CampaignQueueMember.account_id == account_id,
        )
    )
    # Taken out of its last queue with no list holding it, the account goes
    # dormant rather than sitting on nothing.
    await anchoring.release(session, [account_id], reason=f"removed from queue {queue.label!r}")
    await session.commit()


@router.delete("/queues/{queue_id}", status_code=204)
async def delete_queue(queue_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Delete a queue that never fed a campaign.

    A locked queue is the only record of what a campaign was built from, and
    that question gets asked precisely when something has gone wrong — so it is
    refused. A draft queue has been promoted to nothing and committed to
    nothing, so deleting it is the same as never having made it.
    """
    queue = await session.get(CampaignQueue, queue_id)
    if queue is None:
        raise HTTPException(404, "queue not found")

    if queue.status == "locked":
        raise HTTPException(
            409,
            f"{queue.label!r} was promoted on "
            f"{queue.locked_at.date() if queue.locked_at else 'an earlier date'} and cannot be "
            "deleted — it is the only record of what fed that campaign",
        )

    # A clone carries `cloned_from_queue_id` as a provenance stamp. Detach it
    # rather than cascading the delete into someone else's queue — the column
    # is nullable exactly so provenance can outlive its target.
    await session.execute(
        CampaignQueue.__table__.update()
        .where(CampaignQueue.cloned_from_queue_id == queue_id)
        .values(cloned_from_queue_id=None)
    )
    members = list(
        (
            await session.execute(
                select(CampaignQueueMember.account_id).where(
                    CampaignQueueMember.queue_id == queue_id
                )
            )
        ).scalars()
    )
    members += list(
        (
            await session.execute(
                select(CampaignQueueContact.account_id).where(
                    CampaignQueueContact.queue_id == queue_id
                )
            )
        ).scalars()
    )
    label = queue.label
    await session.delete(queue)
    await session.flush()
    await anchoring.release(session, members, reason=f"queue {label!r} was deleted")
    await session.commit()


@router.post("/queues/{queue_id}/clone", status_code=201)
async def clone(
    queue_id: uuid.UUID, payload: QueueIn, session: AsyncSession = Depends(get_session)
):
    """The only way to get an editable copy of a promoted queue."""
    try:
        row = await clone_queue(session, queue_id, label=payload.label)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await session.commit()
    return {"id": str(row.id), "label": row.label, "status": row.status}


class PromoteIn(BaseModel):
    #: Optional. Defaults to the first source queue's label, because the queue
    #: and the campaign it became are the same piece of work to anyone
    #: following it — renaming at the boundary breaks the thread for no gain.
    label: str | None = None
    queue_ids: list[uuid.UUID] = Field(min_length=1)
    cadence_shape_id: uuid.UUID | None = None


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    """Delete a campaign that has never reached LGM.

    Same rule as a queue, one layer along: a campaign that has committed to
    nothing may be deleted, and one that has sent may not. The line is not the
    status badge — it is whether anything left this system.

    Three refusals, each for a different reason:

    * **It is executing, paused or completed.** Messages are in flight or have
      landed. Deleting the row would delete the only record of what was sent to
      whom, which is the record that matters most when a prospect complains.
    * **A sequence carries an LGM id.** Content is frozen on the LGM lead the
      moment it is written there. Deleting our row does not delete theirs — it
      just leaves a live sequence nobody here can stop.
    * **An execution record exists.** The interlock wrote it against an
      approval; the pair is the audit trail for a send that actually happened.

    **The source queues are unlocked.** The lock exists to keep "which version
    of this queue fed campaign 2?" answerable — and once campaign 2 is gone,
    having never sent anything, there is no campaign to trace back to and no
    send to explain. Leaving the queue locked would protect the answer to a
    question that can no longer be asked, and strand a queue whose only
    remaining use is to be cloned. The unlock fires on exactly the same
    precondition as the delete: nothing left this system.

    A queue that still feeds another campaign stays locked, because that
    campaign's question is still live.
    """
    campaign = await session.get(OutreachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    # Read now: the row is gone by the time the audit entry is written.
    deleted_label = campaign.label

    if campaign.status in ("executing", "paused", "completed"):
        raise HTTPException(
            409,
            f"{campaign.label!r} is {campaign.status} — it cannot be deleted. "
            "It is the record of what was sent and to whom.",
        )

    sequences = list(
        (
            await session.execute(
                select(OutreachSequence).where(
                    OutreachSequence.campaign_id == campaign_id
                )
            )
        ).scalars()
    )
    sequence_ids = [s.id for s in sequences]

    enrolled = [s for s in sequences if s.lgm_lead_id or s.lgm_campaign_id]
    if enrolled:
        raise HTTPException(
            409,
            f"{len(enrolled)} sequence(s) in {campaign.label!r} are enrolled in La Growth "
            "Machine. Deleting this campaign would leave them running there with nothing "
            "here able to stop them — stop the campaign first.",
        )

    if sequence_ids:
        executed = (
            await session.execute(
                select(func.count())
                .select_from(ExecutionRecord)
                .where(ExecutionRecord.sequence_id.in_(sequence_ids))
            )
        ).scalar_one()
        if executed:
            raise HTTPException(
                409,
                f"{campaign.label!r} has {executed} execution record(s) — something was "
                "sent. The record of a send outlives the campaign that made it.",
            )

    # --- nothing left this system. Take the whole subtree down. ---
    #
    # The sequences MUST go with it. `outreach_sequence` carries the enrolment
    # lock — a partial unique index over `lgm_identity_id` for any sequence in
    # a live status — so a sequence left behind at `pending_approval` would
    # silently bar that contact from every future campaign, with nothing on
    # screen to explain why.
    if sequence_ids:
        await session.execute(
            Approval.__table__.delete().where(
                Approval.subject_type == "outreach_sequence",
                Approval.subject_id.in_(sequence_ids),
            )
        )
        await session.execute(
            Evaluation.__table__.delete().where(
                Evaluation.subject_type == "outreach_sequence",
                Evaluation.subject_id.in_(sequence_ids),
            )
        )
        # touch → draft cascade from the FKs; the sequences do not.
        await session.execute(
            OutreachSequence.__table__.delete().where(
                OutreachSequence.id.in_(sequence_ids)
            )
        )

    await session.execute(
        ApprovalSample.__table__.delete().where(
            ApprovalSample.campaign_id == campaign_id
        )
    )
    # --- release the source queues ---
    #
    # Read the sources before deleting the campaign: `outreach_campaign_source`
    # cascades, so after the delete there is nothing left to say which queues
    # fed this and they would stay locked forever.
    source_ids = list(
        (
            await session.execute(
                select(OutreachCampaignSource.queue_id).where(
                    OutreachCampaignSource.campaign_id == campaign_id
                )
            )
        ).scalars()
    )
    # `promoted_to_campaign_id` is the older pointer and is set by the same
    # promotion; unioned rather than trusted alone, so a queue linked by only
    # one of the two is still released.
    pointed = list(
        (
            await session.execute(
                select(CampaignQueue.id).where(
                    CampaignQueue.promoted_to_campaign_id == campaign_id
                )
            )
        ).scalars()
    )
    queue_ids = set(source_ids) | set(pointed)

    # Cleared before the delete, not after: `promoted_to_campaign_id` is a
    # plain FK with no ON DELETE, so a queue still pointing here blocks the
    # delete outright.
    if queue_ids:
        await session.execute(
            CampaignQueue.__table__.update()
            .where(CampaignQueue.id.in_(queue_ids))
            .values(promoted_to_campaign_id=None)
        )

    await session.delete(campaign)
    await session.flush()

    for queue_id in queue_ids:
        # A queue feeding another campaign stays locked — that campaign's
        # "which version fed me?" is still a live question.
        still_sourced = (
            await session.execute(
                select(func.count())
                .select_from(OutreachCampaignSource)
                .where(OutreachCampaignSource.queue_id == queue_id)
            )
        ).scalar_one()
        if still_sourced:
            continue
        await session.execute(
            CampaignQueue.__table__.update()
            .where(CampaignQueue.id == queue_id)
            .values(
                status="draft",
                # Moved together or `locked_at_consistent` rejects the row —
                # "is this editable" and "when did it stop being editable"
                # are not allowed to disagree.
                locked_at=None,
            )
        )

    await access.record(
        session, user, "campaign.deleted", "outreach_campaign", str(campaign_id),
        {"label": deleted_label},
    )
    await session.commit()


# LLM only. Promotion locks the source queues and copies their strategy
# threads; nothing here reaches La Growth Machine, and drafting and approval do
# not either. Requiring a sending credential to *build* a campaign blocked
# hours of useful work to prevent a refusal that `execute` already gives.
@router.post(
    "/campaigns",
    status_code=201,
    dependencies=[Depends(requires("llm"))],
)
async def promote_queues(payload: PromoteIn, session: AsyncSession = Depends(get_session)):
    """Lock the source queues and open a campaign fed by them.

    Irreversible for the queues: a promoted queue is a historical record from
    this moment on, and making a variant means cloning it.
    """
    try:
        campaign = await promote(
            session,
            queue_ids=payload.queue_ids,
            label=payload.label,
            cadence_shape_id=payload.cadence_shape_id,
        )
    except MixedTargetsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except QueueLockedError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    sequences = await session.scalar(
        select(func.count())
        .select_from(OutreachSequence)
        .where(OutreachSequence.campaign_id == campaign.id)
    )
    notes = list(campaign.promotion_notes or [])
    await session.commit()
    return {
        "id": str(campaign.id),
        "label": campaign.label,
        "status": campaign.status,
        "sequences": sequences or 0,
        # What was skipped and why. A campaign that comes out smaller than the
        # queue that fed it has to say so.
        "notes": notes,
    }


# --------------------------------------------------------------------------
# approval
# --------------------------------------------------------------------------
class ThreadCardOut(BaseModel):
    sequence_id: uuid.UUID
    contact_name: str
    contact_title: str | None
    account_name: str
    problem_hypothesis: str
    thread_status: str
    confidence: float | None
    touch_count: int
    approved: bool
    flag_reasons: list[str] = Field(default_factory=list)
    in_sample: bool = False


class ApprovalOut(BaseModel):
    campaign_id: uuid.UUID
    campaign_label: str
    #: So the screen can offer the one remaining way out of a campaign that
    #: cannot execute. Deleting is refused server-side once anything has been
    #: written to LGM; this lets the button say so before it is pressed rather
    #: than after.
    campaign_status: str = ""
    deletable: bool = False
    sample_rate: float
    #: Never sampled — every one is read individually.
    flagged: list[ThreadCardOut]
    clean: list[ThreadCardOut]
    sample_size: int
    stratum_size: int
    sample_id: uuid.UUID | None
    escalated: bool
    #: Everyone not saved for approval yet, with where their drafts stand.
    #: Carried in full rather than as a sentence: they are the people blocking
    #: the campaign, and a screen that cannot list them cannot act on them.
    #: Why the campaign is smaller than the queue that fed it, if it is.
    promotion_notes: list[str] = Field(default_factory=list)
    #: People not yet saved for approval, and where their drafts stand.
    waiting: list[dict] = Field(default_factory=list)


async def _cards(session: AsyncSession, campaign_id: uuid.UUID):
    from app.models.account import Account

    sequences = list(
        (
            await session.execute(
                select(OutreachSequence).where(OutreachSequence.campaign_id == campaign_id)
            )
        ).scalars()
    )
    from app.services import campaign_drafts

    # An approval counts only for words still as approved — see `approved_ids`.
    approved = await campaign_drafts.approved_ids(session, sequences)
    waiting: list[dict] = []

    candidates: list[Candidate] = []
    cards: dict[uuid.UUID, ThreadCardOut] = {}
    for sequence in sequences:
        contact, thread = await person_of(session, sequence)
        arc = await campaign_drafts.arc_of(session, sequence.id)
        if sequence.status == "cancelled":
            account = await session.get(Account, contact.account_id) if contact else None
            waiting.append({
                "sequence_id": str(sequence.id),
                "contact_id": str(contact.id) if contact else None,
                "name": contact.full_name if contact else "?",
                "account_name": account.name if account else "?",
                "state": f"withdrawn — {sequence.withdraw_reason}",
                "touch_count": len(arc),
                "withdrawn": True,
            })
            continue
        if sequence.status not in ("pending_approval", *campaign_drafts.APPROVED):
            # Approval reads saved drafts. Anyone not saved yet is listed, not sampled.
            state = campaign_drafts.state_of(sequence, thread is not None, arc)
            account = await session.get(Account, contact.account_id) if contact else None
            waiting.append({
                "sequence_id": str(sequence.id),
                "contact_id": str(contact.id) if contact else None,
                "name": contact.full_name if contact else "?",
                "account_name": account.name if account else "?",
                "state": campaign_drafts.STATE_LABELS[state],
                "touch_count": len(arc),
                "withdrawn": False,
            })
            continue
        account = await session.get(Account, contact.account_id) if contact else None
        touches = await session.scalar(
            select(Touch.id).where(Touch.sequence_id == sequence.id).limit(1)
        )
        count = len(
            list(
                (
                    await session.execute(
                        select(Touch).where(Touch.sequence_id == sequence.id)
                    )
                ).scalars()
            )
        ) if touches else 0

        from app.services import draft_evaluation

        verdict, issues = await draft_evaluation.latest_verdict(session, sequence.id)

        candidates.append(
            Candidate(
                sequence_id=sequence.id,
                contact_name=contact.full_name if contact else "?",
                evaluation_verdict=verdict or "unevaluated",
                evaluation_issue=(issues[0].get("detail") if issues else None),
                contact_verified=bool(contact and contact.email_status == "verified"),
                strategy_confidence=float(thread.confidence)
                if thread and thread.confidence is not None
                else None,
                chosen_by_rep=bool(thread and thread.chosen_by_rep),
                without_live_trigger=bool(thread and thread.without_live_trigger),
                edited_by_rep=campaign_drafts.edited(arc),
            )
        )
        cards[sequence.id] = ThreadCardOut(
            sequence_id=sequence.id,
            contact_name=contact.full_name if contact else "?",
            contact_title=contact.title if contact else None,
            account_name=account.name if account else "?",
            problem_hypothesis=thread.problem_hypothesis if thread else "",
            # A person promoted before a strategy exists: said, not blank.
            thread_status=thread.thread_status if thread else "strategy needed",
            confidence=float(thread.confidence)
            if thread and thread.confidence is not None
            else None,
            touch_count=count,
            approved=sequence.id in approved,
        )
    return candidates, cards, waiting


@router.get("/campaigns/{campaign_id}/approval", response_model=ApprovalOut)
async def get_approval(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """The two strata and the current draw.

    Flagged threads are listed separately and are **never** in the sample —
    stratifying before sampling is what stops a random 6 of 18 missing all four
    threads that needed looking at.
    """
    campaign = await session.get(OutreachCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")

    candidates, cards, waiting = await _cards(session, campaign_id)
    stratum = stratify(candidates)

    sample = (
        await session.execute(
            select(ApprovalSample).where(
                ApprovalSample.campaign_id == campaign_id,
                ApprovalSample.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    drawn = {uuid.UUID(s) for s in (sample.sequence_ids if sample else [])}

    for candidate in stratum.flagged:
        cards[candidate.sequence_id].flag_reasons = stratum.reasons[candidate.sequence_id]
    for sequence_id in drawn:
        if sequence_id in cards:
            cards[sequence_id].in_sample = True

    rules = (
        await session.execute(select(SalesRules).where(SalesRules.is_active.is_(True)))
    ).scalar_one_or_none()

    return ApprovalOut(
        campaign_id=campaign_id,
        campaign_label=campaign.label,
        campaign_status=campaign.status,
        # The same line the delete route draws, asked early. It re-checks on
        # the call itself — a campaign can start sending between this page
        # rendering and the click.
        deletable=campaign.status in ("draft", "pending_approval", "cancelled"),
        promotion_notes=list(campaign.promotion_notes or []),
        waiting=waiting,
        sample_rate=float(rules.sample_rate) if rules else 0.4,
        flagged=[cards[c.sequence_id] for c in stratum.flagged],
        clean=[cards[c.sequence_id] for c in stratum.clean],
        sample_size=sample.sample_size if sample else 0,
        stratum_size=sample.stratum_size if sample else len(stratum.clean),
        sample_id=sample.id if sample else None,
        escalated=bool(sample and sample.escalated_to_individual),
    )


@router.post("/campaigns/{campaign_id}/approval/redraw", response_model=ApprovalOut)
async def redraw(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Draw a fresh random sample. Server-side, never client-chosen.

    A rep may redraw as often as they like — randomness that can be re-rolled is
    still random. What they cannot do is name which threads are in it.
    """
    candidates, _, _ = await _cards(session, campaign_id)
    stratum = stratify(candidates)
    rules = (
        await session.execute(select(SalesRules).where(SalesRules.is_active.is_(True)))
    ).scalar_one_or_none()

    previous = (
        await session.execute(
            select(ApprovalSample).where(
                ApprovalSample.campaign_id == campaign_id,
                ApprovalSample.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    # One rejection doubles the next draw. Two escalated the batch already, and
    # `draw` refuses to shrink back below that.
    doublings = 1 if (previous and previous.rejections == 1) else 0

    await draw(
        session,
        campaign_id=campaign_id,
        stratum=stratum,
        rate=float(rules.sample_rate) if rules else 0.4,
        doublings=doublings,
        escalated=bool(previous and previous.escalated_to_individual),
    )
    await session.commit()
    return await get_approval(campaign_id, session)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reject_reason: str | None = None
    comment: str | None = None


@router.post("/sequences/{sequence_id}/decision")
async def decide(
    sequence_id: uuid.UUID,
    payload: DecisionIn,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    """Approve or reject one thread, read individually."""
    if payload.decision == "reject" and not payload.reject_reason:
        raise HTTPException(422, "a rejection must carry a reason")

    sequence = await session.get(OutreachSequence, sequence_id)
    if sequence is None:
        raise HTTPException(404, "sequence not found")
    if sequence.status not in ("pending_approval", "approved"):
        # Approval reads words. With none saved there is nothing to approve.
        raise HTTPException(
            409, "save this person's cadence drafts for approval first — there is nothing to read yet"
        )
    session.add(
        Approval(
            subject_type="outreach_sequence",
            subject_id=sequence_id,
            decision=payload.decision,
            reject_reason=payload.reject_reason,
            comment=payload.comment,
            reviewer_id=access.reviewer_id(user),
            review_depth="individual",
        )
    )
    # A rejection sends the person back to their drafts.
    sequence.status = "approved" if payload.decision == "approve" else "draft"
    await access.record(
        session, user, f"sequence.{payload.decision}", "outreach_sequence", str(sequence_id),
        {"reject_reason": payload.reject_reason} if payload.reject_reason else None,
    )
    await session.commit()
    return {"ok": True}


class SampleDecisionsIn(BaseModel):
    #: sequence_id → approve | reject. Must cover exactly the drawn ids.
    decisions: dict[uuid.UUID, str]


@router.post("/campaigns/{campaign_id}/approval/accept-sample")
async def accept(
    campaign_id: uuid.UUID,
    payload: SampleDecisionsIn,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    """Approve the sample and inherit the rest of the stratum.

    Refuses a set of ids that is not exactly what was drawn — accepting a
    substitution would let a rep choose which threads counted as read.
    """
    sample = (
        await session.execute(
            select(ApprovalSample).where(
                ApprovalSample.campaign_id == campaign_id,
                ApprovalSample.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if sample is None:
        raise HTTPException(404, "no current sample; draw one first")

    try:
        written = await accept_sample(
            session, sample=sample, reviewed=payload.decisions, reviewer_id=access.reviewer_id(user)
        )
    except SampleTamperedError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SampleEscalatedError as exc:
        await session.commit()  # the rejection count must survive
        raise HTTPException(409, str(exc)) from exc

    candidates, _, _ = await _cards(session, campaign_id)
    stratum = stratify(candidates)
    drawn = {uuid.UUID(s) for s in sample.sequence_ids}
    remainder = [c.sequence_id for c in stratum.clean if c.sequence_id not in drawn]
    for row in inherit(sample=sample, unsampled=remainder, reviewer_id=access.reviewer_id(user)):
        session.add(row)

    for sequence_id in drawn | set(remainder):
        sequence = await session.get(OutreachSequence, sequence_id)
        if sequence is not None:
            sequence.status = "approved"

    await access.record(
        session, user, "campaign.sample_accepted", "outreach_campaign", str(campaign_id),
        {"sampled": len(written), "inherited": len(remainder)},
    )
    await session.commit()
    return {"sampled": len(written), "inherited": len(remainder)}


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------
class PersonRefOut(BaseModel):
    sequence_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    name: str


class CheckOut(BaseModel):
    key: str
    label: str
    passed: bool
    detail: str
    subjects: list[str]
    #: Who the check is about, so the screen can take a rep straight to them.
    people: list[PersonRefOut] = Field(default_factory=list)


class PreflightOut(BaseModel):
    campaign_id: uuid.UUID
    passed: bool
    checks: list[CheckOut]


@router.get("/campaigns/{campaign_id}/preflight", response_model=PreflightOut)
async def get_preflight(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await preflight_service.run(session, campaign_id)
    return PreflightOut(
        campaign_id=campaign_id,
        passed=result.passed,
        checks=[
            CheckOut(
                key=c.key, label=c.label, passed=c.passed,
                detail=c.detail, subjects=c.subjects,
                people=[PersonRefOut(**person) for person in c.people],
            )
            for c in result.checks
        ],
    )


class CadenceSwapIn(BaseModel):
    cadence_shape_id: uuid.UUID


@router.patch("/campaigns/{campaign_id}/cadence")
async def change_campaign_cadence(
    campaign_id: uuid.UUID, payload: CadenceSwapIn, session: AsyncSession = Depends(get_session)
):
    """Move a campaign to a different registered cadence, before anything sends.

    Exists because an LGM campaign can be deleted and rebuilt, which kills the
    registration while the strategy and approved drafts behind it are still
    good. Refused once anything has been written to LGM, and refused when the
    steps would not line up — see `promotion.change_cadence`.
    """
    from app.services.promotion import CadenceSwapRefused, change_cadence

    try:
        result = await change_cadence(
            session, campaign_id=campaign_id, shape_id=payload.cadence_shape_id
        )
    except CadenceSwapRefused as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await session.commit()
    return result


@router.post(
    "/campaigns/{campaign_id}/execute",
    # The send path. Outreach is exactly what this needs, and the only
    # place a missing LGM credential should stop anybody.
    dependencies=[Depends(requires("outreach"))],
)
async def run_execute(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    """The irreversible one. After this the copy is frozen on the LGM lead."""
    try:
        outcome = await execute(session, campaign_id=campaign_id, lgm=await _lgm(session))
    except PreflightFailedError as exc:
        raise HTTPException(
            409,
            {
                "error": "preflight_failed",
                "summary": exc.result.summary(),
                "failed": [c.key for c in exc.result.failures],
            },
        ) from exc

    await access.record(
        session, user, "campaign.executed", "outreach_campaign", str(campaign_id),
        {"enrolled": len(outcome.enrolled), "failed": len(outcome.failed), "skipped": len(outcome.skipped)},
    )
    await session.commit()
    return {
        "enrolled": [str(s) for s in outcome.enrolled],
        "failed": outcome.failed,
        "skipped": outcome.skipped,
        "awaiting_launch": outcome.awaiting_launch,
        "audience": outcome.audience,
    }


@router.post("/sequences/{sequence_id}/stop")
async def stop_one(
    sequence_id: uuid.UUID,
    reason: str = "manual",
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    try:
        sequence = await stop_sequence(
            session, sequence_id=sequence_id, lgm=await _lgm(session), reason=reason
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await access.record(session, user, "sequence.stopped", "outreach_sequence", str(sequence_id), {"reason": reason})
    await session.commit()
    return {"status": sequence.status}


@router.post("/campaigns/{campaign_id}/stop")
async def stop_all(
    campaign_id: uuid.UUID,
    reason: str = "manual",
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    try:
        count = await stop_campaign(
            session, campaign_id=campaign_id, lgm=await _lgm(session), reason=reason
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await access.record(
        session, user, "campaign.stopped", "outreach_campaign", str(campaign_id),
        {"reason": reason, "stopped": count},
    )
    await session.commit()
    return {"stopped": count}


# --------------------------------------------------------------------------
# the arc a rep reviews
# --------------------------------------------------------------------------
class TouchOut(BaseModel):
    step_no: int
    #: Null for everything drafted since timing became LGM's — they schedule
    #: the steps and publish no delays. Typed `int` here until a nullable
    #: column met it, and the write succeeded while the response 500'd.
    day_offset: int | None
    channel: str
    purpose: str | None
    subject: str | None
    body: str
    signal_dependence: str
    status: str
    content_sync_status: str
    #: The current draft's version, and how it came to be: arc, regeneration or rep_edit.
    version: int = 0
    generated_as: str | None = None

    # --- where this content actually lands in LGM --------------------------
    #
    # The binding is the whole integration and it used to be invisible: a rep
    # could not tell which `customAttributeN` a draft occupied, nor whether a
    # subject line would appear at all.
    #
    #: The slot this body is written into, as LGM spells it, plus the name we
    #: derive for it. Null on a touch drafted before its step was mapped.
    lgm_attribute: str | None = None
    lgm_attribute_label: str | None = None
    #: The slot this step's *subject* reads, when its template names one.
    #: Null means LGM's own subject stands — or, on LinkedIn, that there is no
    #: subject at all.
    subject_attribute: str | None = None
    subject_attribute_label: str | None = None
    #: Whether a subject written here would appear. False for every LinkedIn
    #: step, and for an email step whose subject template is fixed copy.
    subject_allowed: bool = False
    #: The channel **LGM** runs this step on, which is the one that decides
    #: what actually sends. `channel` beside it is the model's, proposed while
    #: drafting, and the two can disagree — a step drafted as a LinkedIn
    #: message that LGM sends as an email. Shown in preference to it.
    lgm_channel: str | None = None
    #: Where this step sits in the LGM campaign, and what it is called there.
    #: A campaign's own steps include visits and connection requests that carry
    #: no copy, so step 1 here is rarely position 1 over there — and a name
    #: like "Not Accepted - Email" says this is a branch, not a follow-up.
    lgm_position: int | None = None
    lgm_step_name: str | None = None


class ArcOut(BaseModel):
    sequence_id: uuid.UUID
    contact_name: str
    account_name: str
    problem_hypothesis: str
    positioning: str
    cta: str
    trigger_summary: str
    status: str
    approved: bool
    touches: list[TouchOut]
    contact_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    cadence_label: str | None = None
    cadence_touches: int | None = None
    cadence_days: int | None = None
    #: How many of LGM's twenty per-lead slots this cadence occupies.
    attributes_used: int = 0
    attribute_budget: int = 0
    has_strategy: bool = False
    edited: bool = False
    #: strategy_needed, not_drafted, drafted, saved, approved or enrolled.
    state: str = ""
    state_label: str = ""


@router.get("/sequences/{sequence_id}/arc", response_model=ArcOut)
async def get_arc(sequence_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """All touches with their current drafts — what sequence-level approval reviews.

    One approval covers the arc, so the rep has to see the whole progression:
    it is the only way to judge whether touch 5 earns its place.
    """
    from app.models.account import Account

    sequence = await session.get(OutreachSequence, sequence_id)
    if sequence is None:
        raise HTTPException(404, "sequence not found")

    contact, thread = await person_of(session, sequence)
    account = await session.get(Account, contact.account_id) if contact else None

    touches = list(
        (
            await session.execute(
                select(Touch)
                .where(Touch.sequence_id == sequence_id)
                .order_by(Touch.step_no)
            )
        ).scalars()
    )
    drafts = {
        d.touch_id: d
        for d in (
            await session.execute(
                select(Draft).where(
                    Draft.touch_id.in_([t.id for t in touches]),
                    Draft.is_current.is_(True),
                )
            )
        ).scalars()
    } if touches else {}

    approved = await session.scalar(
        select(Approval.id).where(
            Approval.subject_type == "outreach_sequence",
            Approval.subject_id == sequence_id,
            Approval.decision == "approve",
        )
    )

    from app.services import campaign_drafts

    shape = await campaign_drafts.shape_of(session, sequence)
    # What each slot is called, and which steps can carry a subject at all.
    # Derived from the shape's live mapping so a re-check renames them without
    # anybody re-labelling anything.
    from app.services.lgm import ATTRIBUTE_BUDGET
    from app.services.lgm_client import labels_for

    labels = labels_for(shape) if shape else {}
    subject_map = (shape.subject_attribute_map or {}) if shape else {}
    step_channels = (shape.step_channels or {}) if shape else {}
    step_meta = (shape.step_meta or {}) if shape else {}
    pairs = [(t, drafts.get(t.id)) for t in touches]
    state = campaign_drafts.state_of(sequence, thread is not None, pairs)

    return ArcOut(
        sequence_id=sequence_id,
        contact_id=contact.id if contact else None,
        campaign_id=sequence.campaign_id,
        cadence_label=shape.label if shape else None,
        cadence_touches=shape.touch_count if shape else None,
        cadence_days=shape.span_days if shape else None,
        has_strategy=thread is not None,
        edited=campaign_drafts.edited(pairs),
        state=state,
        state_label=campaign_drafts.STATE_LABELS[state],
        contact_name=contact.full_name if contact else "?",
        account_name=account.name if account else "?",
        problem_hypothesis=thread.problem_hypothesis if thread else "",
        positioning=thread.positioning if thread else "",
        cta=thread.cta if thread else "",
        trigger_summary=thread.trigger_summary if thread else "",
        status=sequence.status,
        approved=approved is not None and sequence.status in campaign_drafts.APPROVED and bool(touches),
        attributes_used=len(
            {v for v in (shape.attribute_map or {}).values() if v}
            | {v for v in (shape.subject_attribute_map or {}).values() if v}
        ) if shape else 0,
        attribute_budget=ATTRIBUTE_BUDGET,
        touches=[
            TouchOut(
                step_no=t.step_no,
                day_offset=t.day_offset,
                channel=t.channel,
                purpose=t.purpose,
                # Read from the shape rather than the touch, so the screen
                # shows where the copy would land *now*: a template edited in
                # LGM moves the slot, and the stale one on the touch is
                # exactly what a rep needs to be able to see is stale.
                lgm_attribute=t.lgm_attribute,
                lgm_attribute_label=labels.get(t.lgm_attribute or ""),
                lgm_channel=step_channels.get(str(t.step_no)),
                lgm_position=(step_meta.get(str(t.step_no)) or {}).get("position"),
                lgm_step_name=(step_meta.get(str(t.step_no)) or {}).get("name"),
                subject_attribute=subject_map.get(str(t.step_no)),
                subject_attribute_label=labels.get(subject_map.get(str(t.step_no), "")),
                subject_allowed=bool(subject_map.get(str(t.step_no))),
                subject=drafts[t.id].subject if t.id in drafts else None,
                body=drafts[t.id].body if t.id in drafts else "",
                signal_dependence=drafts[t.id].signal_dependence if t.id in drafts else "durable",
                status=t.status,
                content_sync_status=t.content_sync_status,
                version=drafts[t.id].version if t.id in drafts else 0,
                generated_as=drafts[t.id].generated_as if t.id in drafts else None,
            )
            for t in touches
        ],
    )
