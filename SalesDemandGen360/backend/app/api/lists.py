"""Account lists, accounts, and CSV import."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    Page,
    Sort,
    page_params,
    requires,
    sort_params,
    validate_sort,
)
from app.database import SessionLocal, get_session
from app.services.providers import ProviderError
from app.models.account import (
    Account,
    Contact,
    AccountList,
    AccountListMember,
    ContactSuggestion,
    account_list_icp,
    account_list_service,
)
from app.models.config import IcpProfile, ServiceCatalog, service_icp_link
from app.models.context import Qualification
from app.services import (
    anchoring, csv_import, resolution, sizing, spreadsheet, verification,
)

router = APIRouter(tags=["lists"])
log = logging.getLogger(__name__)

# The allowlist is a mapping to column objects, never to strings — see deps.py.
ACCOUNT_SORTS = {
    "name": Account.name,
    "domain": Account.domain,
    "industry": Account.industry,
    "employee_count": Account.employee_count,
    "icp_match_score": Account.icp_match_score,
    "status": Account.status,
    "research_status": Account.research_status,
    "enrichment_status": Account.enrichment_status,
    "created_at": Account.created_at,
    # Every column the account table can show has to be sortable, or clicking
    # its header returns 422 and the table reports an error for a click.
    "resolution_status": Account.resolution_status,
    "resolution_confidence": Account.resolution_confidence,
    "resolved_by": Account.resolved_by,
    "linkedin_url": Account.linkedin_url,
    "hq_country": Account.hq_country,
}

def _latest_qualification():
    """One row per account: its most recent qualification.

    A window rather than a join on MAX(created_at): two qualifications written
    in the same transaction share a timestamp, and the join would return both,
    silently duplicating the account in the list.
    """
    ranked = (
        select(
            Qualification.account_id.label("account_id"),
            Qualification.priority_score.label("priority_score"),
            Qualification.priority_band.label("priority_band"),
            func.row_number()
            .over(
                partition_by=Qualification.account_id,
                order_by=Qualification.created_at.desc(),
            )
            .label("rn"),
        ).subquery()
    )
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _account_sorts(latest) -> dict:
    """The account allowlist, plus the two columns that live on the join.

    `coalesce` because Postgres sorts NULLs first on DESC: without it, "best
    first" would open with every account nobody has qualified.
    """
    return {
        **ACCOUNT_SORTS,
        "priority_score": func.coalesce(latest.c.priority_score, -1),
        "priority_band": func.coalesce(latest.c.priority_band, ""),
    }


def _account_out(account: Account, score, band) -> AccountOut:
    row = AccountOut.model_validate(account)
    row.priority_score = float(score) if score is not None else None
    row.priority_band = band
    return row


LIST_SORTS = {
    "label": AccountList.label,
    "source": AccountList.source,
    "created_at": AccountList.created_at,
}


# --------------------------------------------------------------------------
# schemas
# --------------------------------------------------------------------------
class AccountListIn(BaseModel):
    label: str = Field(min_length=1)
    description: str | None = None
    source: str = "manual"


class AccountListOut(BaseModel):
    id: uuid.UUID
    label: str
    description: str | None
    source: str
    created_by: str
    account_count: int = 0
    #: What this list is worked for, resolved to names rather than ids so the
    #: index can be read without a second request per row.
    service_codes: list[str] = Field(default_factory=list)
    icp_names: list[str] = Field(default_factory=list)
    #: How far enrichment has got. Two numbers rather than a percentage: "0 of
    #: 40" and "0 of 0" mean completely different things, and a percentage
    #: renders both as nothing.
    contact_count: int = 0
    verified_count: int = 0
    #: When the list was made. The index sorts on this column and was showing
    #: `created_by` under a "Created" heading — a person where a time belongs.
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    domain: str | None
    linkedin_url: str | None = None
    #: Tier 0. The curation screen is the whole point of the step, so every
    #: field a rep needs in order to judge travels with the row — including the
    #: runners-up, so choosing does not mean going and searching again.
    resolution_status: str = "unresolved"
    resolution_confidence: float | None = None
    resolution_note: str | None = None
    resolved_by: str | None = None
    resolution_candidates: list | None = None
    industry: str | None
    employee_count: int | None
    #: When the count was observed — ours, not theirs. A directory page carries
    #: no date, so this is when we looked. Null on the accounts that held a
    #: number before dates existed; nothing was backfilled, because dating them
    #: today would claim we observed in October what arrived in a CSV.
    employee_count_as_of: date | None = None
    #: The last *different* count and when it was seen, so a reader can say
    #: "grew from 30 to 33 since March" rather than only "33". Carried rather
    #: than computed here: the screen decides how to phrase a change, and a
    #: number nothing can reach is the inert-field problem this session kept
    #: finding.
    employee_count_before: int | None = None
    employee_count_before_as_of: date | None = None
    hq_country: str | None
    icp_match_score: float | None
    status: str
    research_status: str
    enrichment_status: str
    pipeline_note: str | None
    #: Set while the account is on no list and in no queue. See `anchoring`.
    dormant_at: datetime | None = None
    dormant_reason: str | None = None
    #: The latest qualification's roll-up, so the book can be ranked from the
    #: list rather than opened one account at a time. Null until it is judged —
    #: which is different from, and must not read as, a score of zero.
    priority_score: float | None = None
    priority_band: str | None = None

    model_config = {"from_attributes": True}


class FieldOut(BaseModel):
    """One field the importer can fill, and what it is for."""

    key: str
    label: str
    #: `account` or `contact` — which record this column lands on.
    entity: str
    #: Why it matters, in a sentence. Shown beside the picker so a rep can tell
    #: a field that changes what happens next from one that is decoration.
    hint: str = ""
    #: Nothing imports without these.
    required: bool = False


class MappingOut(BaseModel):
    headers: list[str]
    suggested: dict[str, str | None]
    sample_rows: list[dict[str, str]]
    #: Every field, so the screen shows what *could* be filled rather than only
    #: what happened to match. An unmapped `title` is invisible otherwise, and
    #: an invisible unmapped title is how a file imports with no contacts.
    fields: list[FieldOut] = Field(default_factory=list)
    #: Columns in the file that no field claims. They are dropped on import,
    #: and dropping them silently is what made the last failure hard to see.
    unmapped_headers: list[str] = Field(default_factory=list)
    #: `account` or `contact`, from the suggested mapping and the sample rows.
    predicted_grain: str = "account"
    #: Things that will go wrong, said before the import rather than after.
    warnings: list[str] = Field(default_factory=list)


#: What each field is for, in the order a person fills them in. Account first
#: because a contact without a company has nowhere to live.
FIELD_GUIDE: tuple[tuple[str, str, str, str, bool], ...] = (
    ("name", "Company name", "account", "The account is created under this.", True),
    ("domain", "Website / domain", "account",
     "The identity key. Resolution, deduplication and Apollo all use it.", False),
    ("industry", "Industry", "account", "Feeds the industry scoring multiplier.", False),
    ("employee_count", "Employees", "account", "Derives the size band.", False),
    ("hq_country", "Country", "account", "", False),
    ("hq_region", "Region / state", "account", "", False),
    ("linkedin_url", "Company LinkedIn", "account",
     "A /company/ page. A /in/ URL is a person and is routed there instead.", False),
    ("funding_stage", "Funding stage", "account", "", False),
    ("full_name", "Contact name", "contact",
     "Map at least one contact column or the file imports companies only — "
     "and enrichment will have nobody to find.", False),
    ("first_name", "First name", "contact", "", False),
    ("last_name", "Last name", "contact", "", False),
    ("title", "Job title", "contact",
     "What enrichment matches against the ICP's target personas.", False),
    ("email", "Email", "contact", "Imported unverified until enrichment confirms it.", False),
    ("phone", "Phone", "contact", "", False),
    ("contact_linkedin_url", "Contact LinkedIn", "contact",
     "A /in/ profile. The strongest identifier enrichment can use.", False),
)


class RowOut(BaseModel):
    row_number: int
    name: str | None
    domain: str | None
    outcome: str
    detail: str
    #: The person this row described, on a contact-grain file.
    contact_name: str | None = None


class ImportOut(BaseModel):
    total_rows: int
    committed: bool
    counts: dict[str, int]
    rows: list[RowOut]
    #: `account` or `contact`, detected from the file rather than declared.
    #: Reported so the preview can say what the file actually is instead of
    #: leaving somebody to infer it from a wall of outcomes.
    grain: str = "account"
    accounts_touched: int = 0
    contacts_created: int = 0
    contacts_updated: int = 0


# --------------------------------------------------------------------------
# lists
# --------------------------------------------------------------------------
@router.get("/lists", response_model=list[AccountListOut])
async def get_lists(
    sort: Sort = Depends(sort_params),
    session: AsyncSession = Depends(get_session),
):
    sort = validate_sort(sort, LIST_SORTS)
    counts = (
        select(
            AccountListMember.list_id.label("lid"),
            func.count().label("n"),
        )
        .group_by(AccountListMember.list_id)
        .subquery()
    )
    # Contacts reached through the list's accounts, with how many already have
    # a verified address. Grouped in one pass rather than a query per row —
    # this is the index, and N+1 here is felt immediately.
    contacts = (
        select(
            AccountListMember.list_id.label("lid"),
            func.count(Contact.id).label("total"),
            func.count(Contact.id)
            .filter(Contact.email_status == "verified")
            .label("verified"),
        )
        .join(Contact, Contact.account_id == AccountListMember.account_id)
        .group_by(AccountListMember.list_id)
        .subquery()
    )
    stmt = select(
        AccountList,
        func.coalesce(counts.c.n, 0),
        func.coalesce(contacts.c.total, 0),
        func.coalesce(contacts.c.verified, 0),
    ).outerjoin(counts, counts.c.lid == AccountList.id).outerjoin(
        contacts, contacts.c.lid == AccountList.id
    )
    stmt = sort.apply(stmt, LIST_SORTS, AccountList.created_at.desc())
    rows = (await session.execute(stmt)).all()

    # Targeting, in two flat lookups. Kept out of the main statement because
    # joining two many-to-manys onto it would multiply the count columns.
    services: dict[uuid.UUID, list[str]] = {}
    for lid, code in (
        await session.execute(
            select(account_list_service.c.list_id, ServiceCatalog.code).join(
                ServiceCatalog, ServiceCatalog.id == account_list_service.c.service_id
            )
        )
    ).all():
        services.setdefault(lid, []).append(code)

    icps: dict[uuid.UUID, list[str]] = {}
    for lid, name in (
        await session.execute(
            select(account_list_icp.c.list_id, IcpProfile.name).join(
                IcpProfile, IcpProfile.id == account_list_icp.c.icp_profile_id
            )
        )
    ).all():
        icps.setdefault(lid, []).append(name)

    return [
        AccountListOut(**{
            **{k: getattr(lst, k) for k in
               ("id", "label", "description", "source", "created_by", "created_at")},
            "account_count": n,
            "contact_count": total,
            "verified_count": verified,
            "service_codes": sorted(services.get(lst.id, [])),
            "icp_names": sorted(icps.get(lst.id, [])),
        })
        for lst, n, total, verified in rows
    ]


@router.post("/lists", response_model=AccountListOut, status_code=201)
async def create_list(payload: AccountListIn, session: AsyncSession = Depends(get_session)):
    row = AccountList(**payload.model_dump(), created_by="bertie")
    session.add(row)
    await session.commit()
    return AccountListOut.model_validate(row)


# ==========================================================================
# building a list out of the Apollo contacts this account already owns
# ==========================================================================
class ApolloBuildIn(BaseModel):
    """What to look for among the contacts already paid for.

    Not a search of Apollo's database — that is the Suggested tab, where a
    person is a proposal to spend a credit. These people are already bought,
    so reading them is free however often it is done.
    """

    #: Apollo's own bands, as `apollo_list_builder.SIZE_BANDS` spells them.
    size_bands: list[str] = Field(default_factory=lambda: ["51-200"], max_length=6)
    #: Which buyer personas each company must be able to field. A company that
    #: cannot fill every one of these is skipped, because a list quietly
    #: missing the persona it was built for looks complete and is not.
    personas: list[str] = Field(
        default_factory=lambda: ["economic buyer", "technical buyer"], max_length=2
    )
    #: Apollo's own industry names, from `apollo_list_builder.INDUSTRIES`.
    #: Empty means every industry — an empty array sent to Apollo would filter
    #: to nothing and read as an empty account.
    industries: list[str] = Field(default_factory=list, max_length=12)
    #: Only `verified` passes the send gate, so anything else is a contact
    #: nobody may write to.
    verified_only: bool = True
    per_company: int = Field(default=2, ge=1, le=5)
    limit: int = Field(default=100, ge=1, le=500)


class ApolloBuildOut(BaseModel):
    ran: bool
    blocked: str | None = None
    #: Where the numbers fall away. Free to compute — four one-row queries.
    funnel: dict = Field(default_factory=dict)
    note: str = ""
    #: Set only by the build, not the preview.
    list_id: uuid.UUID | None = None
    created: int = 0
    merged: int = 0
    contacts: int = 0
    #: A sample for the preview, with no addresses — the screen shows who and
    #: where, and the list itself carries the rest.
    sample: list[dict] = Field(default_factory=list)


async def _apollo_candidates(session: AsyncSession, payload: ApolloBuildIn):
    from app.services import apollo_list_builder as builder
    from app.services import apollo_people

    client = await apollo_people.from_credentials(session)
    if client is None:
        return None, "No Apollo key is configured, so there are no saved contacts to read."
    build = await builder.gather(
        client,
        size_bands=tuple(payload.size_bands),
        verified_only=payload.verified_only,
        personas=tuple(payload.personas),
        per_company=payload.per_company,
        limit=payload.limit,
        industries=tuple(payload.industries),
    )
    # The coarse counts are the four cheap queries; the rest came from the read.
    coarse = await builder.counts(
        client,
        size_bands=tuple(payload.size_bands),
        verified_only=payload.verified_only,
        industries=tuple(payload.industries),
    )
    build.funnel.saved_total = coarse.saved_total
    build.funnel.verified = coarse.verified
    build.funnel.titled = coarse.titled
    build.funnel.in_band = coarse.in_band
    return build, None


@router.get("/lists/from-apollo/industries", response_model=list[str])
async def apollo_industries():
    """Apollo's industry names, in this account's order of volume.

    Served rather than hard-coded in the screen so there is one list, and
    because a wrong name fails *silently* — an industry Apollo does not know
    returns zero, exactly like a real one nobody is in. Every name here was
    checked against the live account and returns results.
    """
    from app.services import apollo_list_builder as builder

    return list(builder.INDUSTRIES)


@router.post("/lists/from-apollo/preview", response_model=ApolloBuildOut)
async def preview_from_apollo(
    payload: ApolloBuildIn,
    deep: bool = Query(
        False,
        description="Also read the pages, to count companies that can field every "
                    "persona. Slower, still free.",
    ),
    session: AsyncSession = Depends(get_session),
):
    """What these filters would give, without writing or charging anything.

    **Two speeds, because the costs differ by twenty times.** The coarse
    funnel is four one-row queries and returns in a couple of seconds, so the
    screen can recount on every keystroke. Counting the companies that can
    field *every* persona means reading the pages behind those numbers, which
    measured at sixty-four seconds, so it happens only when asked for.

    Nothing here is charged either way — that is why the preview is a separate
    route rather than a dry-run flag. A dry run that might spend money is not
    something anybody presses twice.
    """
    from app.services import apollo_list_builder as builder
    from app.services import apollo_people

    if not deep:
        client = await apollo_people.from_credentials(session)
        if client is None:
            return ApolloBuildOut(
                ran=False,
                blocked="No Apollo key is configured, so there are no saved contacts to read.",
            )
        try:
            funnel = await builder.counts(
                client,
                size_bands=tuple(payload.size_bands),
                verified_only=payload.verified_only,
                industries=tuple(payload.industries),
            )
        except ProviderError as exc:
            # Apollo being busy is an answer about Apollo, not a fault in this
            # request. Left to propagate it reached the screen as "Internal
            # Server Error", which says nothing anybody can act on — where
            # "rate limit reached, try again in a few minutes" is a next step.
            return ApolloBuildOut(ran=False, blocked=str(exc))
        return ApolloBuildOut(
            ran=True,
            funnel=asdict(funnel),
            note=f"{funnel.in_band:,} contacts match. Check availability to see how many "
                 f"companies can field every persona.",
        )

    try:
        build, blocked = await _apollo_candidates(session, payload)
    except ProviderError as exc:
        return ApolloBuildOut(ran=False, blocked=str(exc))
    if build is None:
        return ApolloBuildOut(ran=False, blocked=blocked)
    return ApolloBuildOut(
        ran=True,
        funnel=asdict(build.funnel),
        note=build.note,
        sample=[
            {
                "company": c.company,
                "domain": c.domain,
                "title": c.title,
                "persona": c.persona,
                "email_status": c.email_status,
                # No name and no address. The preview answers "is this the
                # right shape of list", which needs neither.
            }
            for c in build.chosen[:20]
        ],
    )


@router.post("/lists/from-apollo", response_model=ApolloBuildOut, status_code=201)
async def build_from_apollo(
    label: str = Query(..., min_length=1, max_length=200),
    payload: ApolloBuildIn = Body(...),
    session: AsyncSession = Depends(get_session),
):
    """Create a list and fill it from the saved Apollo contacts. No credits.

    **Imported through `csv_import`, not written directly.** The people arrive
    as rows in the shape an Apollo export has, and the importer already knows
    how to resolve an account by domain, merge a company it has seen before,
    refresh a headcount and attach a contact — all of it tested. A second
    write path here would be the one that forgets a step.
    """
    from app.services import csv_import

    try:
        build, blocked = await _apollo_candidates(session, payload)
    except ProviderError as exc:
        return ApolloBuildOut(ran=False, blocked=str(exc))
    if build is None:
        return ApolloBuildOut(ran=False, blocked=blocked)
    if not build.chosen:
        return ApolloBuildOut(
            ran=True, funnel=asdict(build.funnel),
            blocked=(
                "Nothing matched. "
                + (build.note or "Widen the size band or ask for one persona.")
            ),
        )

    rows = [
        {
            "Company": c.company,
            "Website": c.domain,
            "Company Linkedin Url": c.company_linkedin or "",
            "First Name": (c.full_name.split(" ", 1) + [""])[0],
            "Last Name": (c.full_name.split(" ", 1) + [""])[1],
            "Title": c.title or "",
            "Email": c.email or "",
            # Apollo's own verdict, carried rather than assumed. Without it
            # the importer marks every address rep-supplied and unverified —
            # correct for a spreadsheet, and it made this feature produce
            # contacts that cannot pass the send gate.
            "Email Status": c.email_status or "",
            "Person Linkedin Url": c.linkedin_url or "",
        }
        for c in build.chosen
    ]
    new_list = await csv_import.ensure_list(
        session, label=label, source="apollo", created_by="bertie"
    )
    report = await csv_import.run_import(
        session,
        list_id=new_list.id,
        rows=rows,
        mapping=csv_import.suggest_mapping(list(rows[0].keys())),
        added_by="bertie",
        dry_run=False,
        # These rows are provider output, not a rep's file: they were read
        # from `contacts/search` moments ago and carry Apollo's verdict.
        provider="apollo",
    )
    await session.commit()
    log.info(
        "apollo_build.done list=%s contacts=%d companies=%d",
        new_list.id, report.counts.get("contact_created", 0), report.accounts_touched,
    )
    return ApolloBuildOut(
        ran=True,
        funnel=asdict(build.funnel),
        note=build.note,
        list_id=new_list.id,
        # **`accounts_touched`, not `created` + `merged`.** Those two are
        # *account-grain outcomes*, and this import is contact-grain — every
        # row reports a contact outcome instead, so both are structurally
        # zero and the build announced "0 accounts" for a list holding ten.
        #
        # §99 found and fixed exactly this on the import button, and it was
        # written again here three days later. The counts dictionary makes it
        # easy: `created` reads like the obvious field and is only correct on
        # one of the two grains.
        created=report.accounts_touched,
        merged=report.counts.get("merged", 0),
        contacts=report.counts.get("contact_created", 0)
        + report.counts.get("contact_updated", 0),
    )


@router.get("/lists/{list_id}", response_model=AccountListOut)
async def get_list(list_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """One list, so the detail page can name what you are looking at."""
    row = await session.get(AccountList, list_id)
    if row is None:
        raise HTTPException(404, "list not found")
    members = await session.scalar(
        select(func.count())
        .select_from(AccountListMember)
        .where(AccountListMember.list_id == list_id)
    )
    return AccountListOut(
        **{
            k: getattr(row, k)
            for k in ("id", "label", "description", "source", "created_by", "created_at")
        },
        account_count=members or 0,
    )


class DeleteListOut(BaseModel):
    """What the deletion actually removed."""

    #: Nobody had done anything with them — the undo of a bad import.
    accounts_deleted: int = 0
    #: Still in use: on another list, or in a campaign queue.
    accounts_kept: int = 0
    #: On nothing else, with work behind them. Hidden, nothing deleted.
    accounts_dormant: int = 0


class DeletePreviewOut(BaseModel):
    """What deleting a list would do to its accounts. Nothing is written."""

    accounts: int = 0
    on_other_lists: int = 0
    #: On no other list, but kept live by a campaign queue.
    in_queues: int = 0
    dormant: int = 0
    deleted: int = 0


async def _member_ids(session: AsyncSession, list_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await session.execute(
                select(AccountListMember.account_id).where(AccountListMember.list_id == list_id)
            )
        ).scalars()
    )


@router.get("/lists/{list_id}/delete-preview", response_model=DeletePreviewOut)
async def delete_preview(list_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """What `DELETE /lists/{id}` would do, for the confirmation to say before it happens."""
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")
    ids = await _member_ids(session, list_id)
    assessment = await anchoring.assess(session, ids, ignoring_list=list_id, delete_empty=True)
    return DeletePreviewOut(accounts=len(ids), **assessment.counts())


@router.delete("/lists/{list_id}", response_model=DeleteListOut)
async def delete_list(list_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Delete a list. Always allowed.

    A list is a workspace — a way of organising accounts to build campaigns
    from — not what decides whether an account's data lives. It used to refuse
    once anything on it had been researched, because deleting it deleted the
    accounts only it held and evidence cascades with them; so a worked list
    could never be cleaned up and the Lists screen only grew.

    Now each account is assessed as though the list were already gone
    (`services/anchoring.py`):

    * **on another list, or in a campaign queue** — untouched. Whatever went to
      a campaign stays, guarded there: a queue that fed a campaign is locked,
      and a campaign that reached La Growth Machine cannot be deleted;
    * **on nothing else, with work behind it** — dormant: hidden, nothing
      deleted, back the moment a list takes it again;
    * **on nothing else, never worked on** — deleted, which is how a bad
      import is undone.

    `GET /lists/{id}/delete-preview` answers the same question without writing.
    """
    row = await session.get(AccountList, list_id)
    if row is None:
        raise HTTPException(404, "list not found")

    ids = await _member_ids(session, list_id)
    assessment = await anchoring.assess(session, ids, ignoring_list=list_id, delete_empty=True)

    # Suggestions nobody acted on belong to this workspace and go with it.
    # Rejected and revealed ones outlive it (`list_id` is set null), so a
    # rejected person is not suggested again when a new list brings the
    # account back.
    await session.execute(
        delete(ContactSuggestion).where(
            ContactSuggestion.list_id == list_id,
            ContactSuggestion.status.in_(("proposed", "accepted", "known")),
        )
    )
    await session.execute(
        AccountListMember.__table__.delete().where(AccountListMember.list_id == list_id)
    )
    await anchoring.apply(session, assessment, reason=f"list {row.label!r} was deleted")
    await session.delete(row)
    await session.commit()

    return DeleteListOut(
        accounts_deleted=len(assessment.deleted),
        accounts_kept=len(assessment.on_lists | assessment.in_queues),
        accounts_dormant=len(assessment.dormant),
    )


@router.get("/lists/{list_id}/accounts", response_model=list[AccountOut])
async def list_accounts(
    list_id: uuid.UUID,
    sort: Sort = Depends(sort_params),
    page: Page = Depends(page_params),
    status_filter: str | None = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
):
    latest = _latest_qualification()
    sorts = _account_sorts(latest)
    sort = validate_sort(sort, sorts)
    stmt = (
        select(Account, latest.c.priority_score, latest.c.priority_band)
        .join(AccountListMember, AccountListMember.account_id == Account.id)
        .outerjoin(latest, latest.c.account_id == Account.id)
        .where(AccountListMember.list_id == list_id)
    )
    if status_filter:
        stmt = stmt.where(Account.status == status_filter)
    stmt = sort.apply(stmt, sorts, Account.name.asc())
    stmt = stmt.limit(page.limit).offset(page.offset)
    return [_account_out(a, s, b) for a, s, b in (await session.execute(stmt)).all()]


# --------------------------------------------------------------------------
# accounts
# --------------------------------------------------------------------------
@router.get("/accounts", response_model=list[AccountOut])
async def get_accounts(
    sort: Sort = Depends(sort_params),
    page: Page = Depends(page_params),
    q: str | None = Query(None, min_length=1, max_length=120),
    dormant: str = Query("exclude", pattern="^(exclude|include|only)$"),
    session: AsyncSession = Depends(get_session),
):
    latest = _latest_qualification()
    sorts = _account_sorts(latest)
    sort = validate_sort(sort, sorts)
    stmt = select(Account, latest.c.priority_score, latest.c.priority_band).outerjoin(
        latest, latest.c.account_id == Account.id
    )
    # Dormant accounts are hidden unless asked for: they are on no list and in
    # no queue, and are shown to be brought back, not worked.
    if dormant == "exclude":
        stmt = stmt.where(Account.dormant_at.is_(None))
    elif dormant == "only":
        stmt = stmt.where(Account.dormant_at.is_not(None))
    if q:
        # ilike with bound parameters — the search term never reaches SQL as text.
        pattern = f"%{q}%"
        stmt = stmt.where(Account.name.ilike(pattern) | Account.domain.ilike(pattern))
    stmt = sort.apply(stmt, sorts, Account.name.asc())
    stmt = stmt.limit(page.limit).offset(page.offset)
    return [_account_out(a, s, b) for a, s, b in (await session.execute(stmt)).all()]


# --------------------------------------------------------------------------
# CSV import — inspect, then dry run, then commit
# --------------------------------------------------------------------------
@router.post("/lists/{list_id}/import/inspect", response_model=MappingOut)
async def inspect_csv(list_id: uuid.UUID, file: UploadFile = File(...)):
    """Step 1 — read the headers and propose a mapping. Nothing is written."""
    try:
        headers, rows = spreadsheet.parse_upload(await file.read(), file.filename)
    except spreadsheet.UnreadableUpload as exc:
        # 400 with the reason attached. "Could not read any columns" was true
        # of a PDF, an empty sheet and an Excel file alike, which left the rep
        # to guess which had happened.
        raise HTTPException(400, str(exc)) from exc
    if not headers:
        raise HTTPException(
            400,
            "that file has no header row — the first row has to name the columns",
        )
    suggested = csv_import.suggest_mapping(headers)
    claimed = {h for h in suggested.values() if h}
    grain = csv_import.detect_grain(rows, suggested)

    warnings: list[str] = []
    if not suggested.get("name"):
        warnings.append(
            "No company-name column was recognised. Nothing imports without it "
            "— pick one below."
        )
    if grain != "contact":
        warnings.append(
            "No contact columns are mapped, so this imports companies only. "
            "Enrichment finds addresses for people already on the list, so it "
            "will have nobody to work on."
        )
    if not suggested.get("domain"):
        warnings.append(
            "No website or domain column. Identity resolution needs one, and "
            "without it accounts cannot be deduplicated or looked up."
        )
    unmapped = [h for h in headers if h not in claimed]
    if unmapped:
        warnings.append(
            f"{len(unmapped)} column(s) will be ignored: {', '.join(unmapped[:6])}"
            + ("…" if len(unmapped) > 6 else "")
        )

    return MappingOut(
        headers=headers,
        suggested=suggested,
        sample_rows=rows[:5],
        fields=[
            FieldOut(key=k, label=label, entity=entity, hint=hint, required=required)
            for k, label, entity, hint, required in FIELD_GUIDE
        ],
        unmapped_headers=unmapped,
        predicted_grain=grain,
        warnings=warnings,
    )


class ListTargetingIn(BaseModel):
    """What an account list is being worked for.

    Services first, then the ICPs - and the ICPs must be linked to the chosen
    services. Picking a service is how a rep thinks ("what am I selling?"), and
    it narrows the ICP list to something short enough to read. Choosing an ICP
    the service does not sell to is refused rather than ignored: silently
    dropping it would enrich for a buyer nobody selected.
    """

    service_ids: list[uuid.UUID] = Field(min_length=1)
    icp_profile_ids: list[uuid.UUID] = Field(min_length=1)


class ListTargetingOut(BaseModel):
    """The current targeting, plus what could be chosen.

    `available_icps` is the ICPs reachable from the chosen services, so the
    picker never has to work it out itself and cannot drift from the rule the
    server enforces.
    """

    service_ids: list[uuid.UUID]
    icp_profile_ids: list[uuid.UUID]
    available_icps: list[uuid.UUID]


class VerifyOutcomeOut(BaseModel):
    contact_id: uuid.UUID
    full_name: str
    outcome: str
    detail: str
    providers_called: list[str]


class IcpVersionOut(BaseModel):
    """Which ICP, at which version, a run actually read."""

    name: str
    version: int


class VerifyOut(BaseModel):
    #: False when no provider could be called — a pass that did not run must
    #: not read as a pass that found nothing.
    ran: bool
    blocked: str | None = None
    waterfall: list[str] = Field(default_factory=list)
    #: The fields the waterfall chased, from `enrichment_config`.
    wanted: list[str] = Field(default_factory=list)
    #: The service this pass targeted, and the ICP versions that defined it.
    #: Returned so a run stays explainable after the ICPs have moved on — a
    #: service may sell to several kinds of buyer, and a run may target more
    #: than one, so this is a list. It was a single `icp_version: int`, which
    #: no longer existed on the report and made the endpoint raise a 500 on
    #: every call — the Enrich button did nothing at all.
    service_code: str | None = None
    icp_versions: list[IcpVersionOut] = Field(default_factory=list)
    #: Contacts deliberately left alone — nobody this service pitches to, or
    #: nobody with enough on the row to tell. Separated because they need
    #: different work: a better list, versus a better import.
    out_of_persona: int = 0
    unknown_persona: int = 0
    checked: int = 0
    verified: int = 0
    #: Of the verified, how many also came away with a number and a profile.
    #: Collected, not gated on — neither is a condition of being reachable.
    #: Aged verified addresses re-confirmed from saved Apollo contacts, free.
    reconfirmed_free: int = 0
    #: Contacts Apollo enriched on this pass, saved to the Apollo account.
    saved_to_apollo: int = 0
    apollo_note: str | None = None
    with_phone: int = 0
    with_linkedin: int = 0
    #: Found, but graded below sendable by the provider that found it. Separate
    #: from `not_found` because it needs different work — a guess needs
    #: confirming, a miss needs a better identifier.
    risky: int = 0
    not_found: int = 0
    unavailable: int = 0
    #: Missing LinkedIn links filled on this pass, and from where — the
    #: provider, or the company's own website. `linkedin_notes` says what the
    #: website pass could not settle.
    contact_linkedin_from_provider: int = 0
    contact_linkedin_from_site: int = 0
    company_linkedin_from_provider: int = 0
    company_linkedin_from_site: int = 0
    linkedin_notes: list[str] = Field(default_factory=list)
    outcomes: list[VerifyOutcomeOut] = Field(default_factory=list)



async def _reachable_icps(
    session: AsyncSession, service_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """ICP ids linked to any of these services."""
    if not service_ids:
        return set()
    rows = (
        await session.execute(
            select(service_icp_link.c.icp_profile_id).where(
                service_icp_link.c.service_id.in_(service_ids)
            )
        )
    ).all()
    return {r[0] for r in rows}



class ResolveOut(BaseModel):
    """What one resolution pass did, and what it could not do."""

    ran: bool
    blocked: str | None = None
    order: list[str] = Field(default_factory=list)
    checked: int = 0
    resolved: int = 0
    needs_review: int = 0
    unresolved: int = 0
    unavailable: int = 0
    outcomes: list[dict] = Field(default_factory=list)


class ResolutionPatch(BaseModel):
    """A rep's verdict on one account.

    `status` is what they decided; the rest is what they corrected on the way.
    Everything is optional because the common case is one field — usually the
    domain — and forcing a full object would mean the screen resending values
    nobody touched.
    """

    status: str | None = Field(default=None, pattern="^(resolved|needs_review|rejected)$")
    domain: str | None = None
    linkedin_url: str | None = None
    industry: str | None = None
    employee_count: int | None = Field(default=None, ge=0)



class ResearchAccountOut(BaseModel):
    """One account's run, and why it stopped if it did."""

    account_id: uuid.UUID
    name: str
    run_id: uuid.UUID | None = None
    #: `researched`, `partial` (some families failed), `failed` (every family
    #: failed, or the run raised), `halted` (stopped before researching), or
    #: `reused` (everything was answered inside the reuse window; not run).
    outcome: str
    detail: str = ""
    #: Evidence rows stored, per family. A family present with 0 looked and
    #: found nothing — which is a finding, not an omission.
    evidence_by_family: dict[str, int] = Field(default_factory=dict)
    #: Conclusions now unreachable for this account, named so a rep knows what
    #: the silence cost rather than being left to infer it.
    gaps: list[dict] = Field(default_factory=list)


#: The longest a limited run will wait and carry on. Above this the loop stops
#: and says so: a rep watching a progress bar needs an answer, and a wait
#: measured in minutes is indistinguishable from the hang §109 was about.
RATE_LIMIT_MAX_WAIT = 90.0


class ResearchOut(BaseModel):
    ran: bool
    blocked: str | None = None
    #: Set when the provider's quota ended the run before the list did. The
    #: accounts not reached were not researched and nothing was spent on them.
    stopped_early: str | None = None
    #: Seconds spent waiting out a per-minute ceiling, when one was named and
    #: short enough to wait for. Reported so a run that took twice as long as
    #: usual explains itself.
    rate_limit_waited: float | None = None
    #: Accounts on the list that tier 0 has not confirmed. Reported rather than
    #: attempted: research on an unverified company succeeds and is wrong.
    skipped_unresolved: int = 0
    attempted: int = 0
    researched: int = 0
    #: Researched, but some families failed — so some conclusions are unknown
    #: rather than absent. Not folded into `researched` for that reason.
    partial: int = 0
    halted: int = 0
    failed: int = 0
    #: Every planned family answered inside the reuse window, so nothing was
    #: spent. Not counted against the cap — the cap bounds spending.
    reused: int = 0
    #: Confirmed and stale, but past the per-request cap. Counted so a rep
    #: knows to run again, rather than reading a capped run as a complete one.
    over_limit: int = 0
    #: The window in force, so the report can say what "reused" meant.
    window_days: int = 0
    #: People looked into by the contact pass, and the passages about them.
    contacts_researched: int = 0
    contact_evidence: int = 0
    #: Accounts whose ICP asks for contact signals but that have nobody matching
    #: its personas with a verified email — the fix is Enrich contacts.
    no_contacts: int = 0
    #: Typed signals written from the evidence, and conclusions the guard
    #: refused because their citations did not resolve.
    signals_stored: int = 0
    signals_dropped: int = 0
    #: Accounts scored across the six dimensions, by band; those with nothing
    #: to judge yet; and those whose assessment could not be made.
    qualified: int = 0
    bands: dict[str, int] = Field(default_factory=dict)
    not_qualified: int = 0
    qualification_failed: int = 0
    evidence_stored: int = 0
    accounts: list[ResearchAccountOut] = Field(default_factory=list)


class AccountIdsIn(BaseModel):
    """A selection, by id."""

    account_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class RemoveOut(BaseModel):
    removed: int = 0
    #: Asked to remove, but not on this list — a stale selection, reported
    #: rather than silently counted as done.
    not_members: int = 0
    #: Of the removed, how many are now on no list and in no queue, and went
    #: dormant. Nothing is deleted by removing.
    dormant: int = 0


class AddOut(BaseModel):
    added: int = 0
    #: Already on this list.
    already: int = 0
    #: Of the added, how many were dormant and came back with their research
    #: and contacts.
    revived: int = 0
    not_found: int = 0


@router.post("/lists/{list_id}/accounts/remove", response_model=RemoveOut)
async def remove_list_members(
    list_id: uuid.UUID,
    payload: AccountIdsIn,
    session: AsyncSession = Depends(get_session),
):
    """Take accounts off this list. **The accounts themselves are kept.**

    A list is a selection, not an owner: the same company legitimately sits on
    several, and its evidence, contacts and research belong to it rather than
    to whichever import brought it in. So this deletes membership rows and
    nothing else — no cascade can reach evidence from here, which is what makes
    it safe to offer as a bulk action.

    An account left on no list and in no campaign queue goes dormant — hidden,
    nothing deleted — and an import of the same domain, or Add to list, brings
    it back with its research and contacts.

    Not a DELETE with a body: several clients and proxies drop DELETE bodies,
    and a selection of ids is not a path parameter.
    """
    lst = await session.get(AccountList, list_id)
    if lst is None:
        raise HTTPException(404, "list not found")

    wanted = set(payload.account_ids)
    present = {
        r[0]
        for r in (
            await session.execute(
                select(AccountListMember.account_id).where(
                    AccountListMember.list_id == list_id,
                    AccountListMember.account_id.in_(wanted),
                )
            )
        ).all()
    }
    if present:
        await session.execute(
            AccountListMember.__table__.delete().where(
                AccountListMember.list_id == list_id,
                AccountListMember.account_id.in_(present),
            )
        )
    released = (
        await anchoring.release(session, present, reason=f"removed from list {lst.label!r}")
        if present
        else anchoring.Assessment()
    )
    await session.commit()
    return RemoveOut(
        removed=len(present), not_members=len(wanted - present), dormant=len(released.dormant)
    )


@router.post("/lists/{list_id}/accounts/add", response_model=AddOut)
async def add_list_members(
    list_id: uuid.UUID,
    payload: AccountIdsIn,
    session: AsyncSession = Depends(get_session),
):
    """Put existing accounts on this list — the way a dormant account comes back by hand.

    Its research, signals, contacts and company check are all still there;
    research reuses what is inside the freshness window, and scoring it for
    this list's ICP is free.
    """
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")
    wanted = set(payload.account_ids)
    existing = set(
        (await session.execute(select(Account.id).where(Account.id.in_(wanted)))).scalars()
    )
    present = set(
        (
            await session.execute(
                select(AccountListMember.account_id).where(
                    AccountListMember.list_id == list_id,
                    AccountListMember.account_id.in_(existing),
                )
            )
        ).scalars()
    )
    new = existing - present
    for account_id in new:
        session.add(
            AccountListMember(
                list_id=list_id, account_id=account_id, added_by="rep", import_row_reason="added"
            )
        )
    revived = await anchoring.revive(session, new)
    await session.commit()
    return AddOut(
        added=len(new), already=len(present), revived=len(revived),
        not_found=len(wanted - existing),
    )


class ResearchTargetsIn(BaseModel):
    """Whole accounts, or named people at them.

    `contact_ids` narrows the *people* to those named — nobody else at their
    company is looked into. The company's own families are still planned, and
    the reuse window then does the work: a company researched recently costs
    nothing and only the person is read; a company never researched is covered
    in the same run, because a person's news means little with no company
    behind it. Their own reuse window is ignored — naming somebody is an
    explicit ask to look now.
    """

    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    contact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


#: Which halves of a run to buy.
#:
#: **Measured, which is why this exists.** A company pass is six grounded
#: searches and a contact pass is four more — 40% of the bill for 4% of the
#: evidence — and one button used to buy both. A rep re-sweeping a company
#: paid for its people again every time, and nothing on the screen said so.
RESEARCH_SCOPES = ("both", "company", "contacts")


@router.post("/lists/{list_id}/run-research", response_model=ResearchOut)
async def run_research_for_list(
    list_id: uuid.UUID,
    limit: int = Query(5, ge=1, le=100),
    payload: ResearchTargetsIn | None = Body(None),
    force: bool = Query(False),
    #: What `force` ignores the reuse window *for*.
    #:
    #: It used to ignore it for everything, which made "rerun this company"
    #: re-buy its contact pass at full price — the largest single waste in
    #: the ledger. A rerun now re-sweeps what you asked to re-sweep.
    force_scope: str = Query("company", pattern="^(both|company|contacts)$"),
    #: Which halves run at all. `company` leaves the people alone entirely.
    scope: str = Query("both", pattern="^(both|company|contacts)$"),
    #: How much this account is worth spending on.
    #:
    #: **A ceiling, and the only one.** The reuse window, the scan's
    #: per-family plan and the LinkedIn waterfall all subtract from what a run
    #: buys; this sets the maximum. A deep run on a dead account still costs
    #: light money, because the scan gates it.
    #:
    #: Measured over the first week: light reaches 85% of every signal found
    #: for 29% of what a run costs, because the two dearest sources are
    #: fifteen times dearer per signal than the two cheapest paid ones.
    #:
    #: `deep` is the default so that a caller which says nothing gets what it
    #: got before. The screens choose deliberately.
    tier: str = Query("deep", pattern="^(light|standard|deep)$"),
    # One cheap sweep before the per-family passes; nothing found means the
    # families are not bought. On by default — it is the saving — and a query
    # param rather than buried config because the first thing anyone needs to
    # do with a gate is run the same list both ways and compare the ledger.
    fast_sweep: bool = Query(True),
    # The standing description — what the company is, and who its people are.
    # Written once per account and per contact, then reused, so leaving it on
    # costs nothing on a second run. Outside the sweep gate deliberately: a
    # profile is most useful on exactly the accounts the gate turns away.
    profiles: bool = Query(True),
    session: AsyncSession = Depends(get_session),
):
    """Research every confirmed account on this list.

    **Inside the reuse window, nothing is bought twice.** A family answered for
    an account within `research_config.freshness_days` is not run again; an
    account whose every planned family is fresh is reported `reused` and not
    run at all. `force` ("Rerun research") ignores the window.

    **Sequential, and capped low.** Each account is several model calls with
    web search, so a fifty-account list run concurrently would multiply the
    spend rate and the rate-limit exposure at the same moment, and a mistake
    would be discovered after paying for all of it rather than five. Doing it
    faster is a deliberate second step, not a default.

    **Unresolved accounts are skipped, not attempted.** `pipeline.run_research`
    refuses them anyway; counting them here means the report can say *why*
    nothing happened — "9 of 13 are not confirmed yet" sends a rep to the
    curation screen, whereas a bare "0 researched" sends them nowhere.

    Gated on the LLM capability alone. Research needs a model and nothing else:
    an installation with no La Growth Machine key can research all day, and
    blocking it on a credential the step never uses is the over-gating the
    per-capability split exists to remove.
    """
    from app.services import demo, llm, pipeline, qualification
    from app.services.crm import StubCrmAdapter

    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")

    try:
        await llm.assert_may_call(session, "company_research")
    except Exception as exc:  # noqa: BLE001 — reported, not raised at the rep
        return ResearchOut(ran=False, blocked=str(exc))

    stmt = (
        select(Account)
        .join(AccountListMember, AccountListMember.account_id == Account.id)
        .where(AccountListMember.list_id == list_id)
        .order_by(Account.name)
    )
    # People picked by name on the Contacts tab: research them, and plan no
    # company families at all.
    chosen_people: dict[uuid.UUID, list] = {}
    if payload is not None and payload.contact_ids:
        for contact in (
            await session.execute(select(Contact).where(Contact.id.in_(payload.contact_ids)))
        ).scalars():
            if not contact.do_not_contact:
                chosen_people.setdefault(contact.account_id, []).append(contact)
        if not chosen_people:
            return ResearchOut(
                ran=True,
                blocked=(
                    "Everybody picked is marked do-not-contact, so nothing was researched."
                ),
            )
        stmt = stmt.where(Account.id.in_(chosen_people))
    elif payload is not None and payload.account_ids:
        # A selection from the table. Still scoped to the list, so an id from
        # somewhere else cannot ride in on this route.
        stmt = stmt.where(Account.id.in_(payload.account_ids))
    members = (await session.execute(stmt)).scalars().all()

    ready = [a for a in members if a.resolution_status == "resolved"]
    report = ResearchOut(ran=True, skipped_unresolved=len(members) - len(ready))

    if not ready:
        report.blocked = (
            f"No account on this list has a confirmed identity yet "
            f"({len(members)} unconfirmed). Resolve them first — research on an "
            "unverified company produces evidence about the wrong business."
        )
        return report

    from app.services import research as research_service
    from app.services import sources as source_service

    window = await research_service.freshness_days(session)
    report.window_days = window
    # What to look for comes from the list's ICPs: their company signals for
    # the company; their contact signals, and buyer personas, for the people.
    list_plan = await research_service.plan_for_list(session, list_id, tier=tier)
    planned = set(list_plan.company.keys)
    contact_families = set(list_plan.contact.keys)
    # Contacts are deep-only. The whole per-person programme has produced
    # five signals for its lifetime, so it is not something a cheaper run
    # should reach for — a rep who wants it asks for the tier that says so.
    if tier != "deep":
        contact_families = set()
    # **Scope narrows the plan, not the runner.** Emptying a family set here
    # means the reuse arithmetic, the "nothing to do" check and the report all
    # agree with what was actually bought. Suppressing it at the call instead
    # would leave this function counting work that never happened.
    if scope == "company":
        contact_families = set()
    elif scope == "contacts":
        planned = set()
    # A plan that buys nothing. `None` would mean "the whole registry" to the
    # runner — the opposite of what a narrowed scope is asking for.
    empty_plan = research_service.ResearchPlan(families=[])

    crm = StubCrmAdapter()
    for account in ready:
        # `force` is scoped now. A contacts-only rerun must not drag the
        # company's families back through the window with it.
        force_company = force and force_scope in ("both", "company")
        force_contacts = force and force_scope in ("both", "contacts")
        fresh = (
            {}
            if force_company
            else await research_service.fresh_families(session, account.id, days=window)
        )
        fresh = {family: when for family, when in fresh.items() if family in planned}
        # A source that has failed here three runs running is not tried again
        # until something changes. Per account: a site blocking our agent
        # blocks it for that company, not for the book.
        held = await source_service.quarantined(session, account.id)
        held = {family: why for family, why in held.items() if family in planned}

        people = (
            chosen_people.get(account.id, [])
            if chosen_people
            else (
                await research_service.contacts_to_research(
                    session, account.id, targets=list_plan.targets
                )
                if contact_families
                else []
            )
        )
        person_fresh = (
            {}
            if force_contacts or chosen_people or not people
            else await research_service.fresh_contact_families(session, account.id, days=window)
        )
        contact_skip = {
            c.id: set(person_fresh.get(c.id, {})) & contact_families for c in people
        }
        contact_work = any(contact_families - contact_skip[c.id] for c in people)

        # Fresh families cost nothing to skip; unread evidence costs nothing to
        # read. An account researched before extraction existed has both, and
        # skipping it entirely is what left it with an empty Signals tab.
        unread = await research_service.has_unread_evidence(session, account.id)
        if (
            (planned or contact_families)
            and planned <= set(fresh)
            and not contact_work
            and not unread
        ):
            answered_at = [
                *fresh.values(),
                *(
                    when
                    for c in people
                    for family, when in person_fresh.get(c.id, {}).items()
                    if family in contact_families
                ),
            ]
            if answered_at:
                # Everything the plan asks for — company and people — was
                # answered inside the window. Nothing is spent, so this does
                # not count against the cap.
                report.reused += 1
                report.accounts.append(
                    ResearchAccountOut(
                        account_id=account.id,
                        name=account.name,
                        outcome="reused",
                        detail=(
                            f"researched {max(answered_at):%d %b %Y}, inside the "
                            f"{window}-day window — rerun to refresh"
                        ),
                    )
                )
                continue
        if report.attempted >= limit:
            report.over_limit += 1
            continue

        report.attempted += 1
        # One id for the run and for the evidence it stores. The runner used
        # to be built without it, so evidence landed with no run to trace to.
        run_id = uuid.uuid4()
        # The factory is what lets the families run at once: each takes a
        # session of its own, because they all read config and write evidence
        # and `AsyncSession` cannot be shared between coroutines. Measured,
        # this is 79s an account down to roughly 37s at identical spend.
        runner = pipeline.llm_family_runner(
            session, run_id=run_id, session_factory=SessionLocal
        )
        try:
            result = await pipeline.run_research(
                session, account=account, crm=crm,
                run_family=runner, run_id=run_id, triggered_by="rep",
                run_sweep=(
                    pipeline.llm_sweep_runner(session, run_id=run_id)
                    if fast_sweep
                    else None
                ),
                run_profile=(
                    pipeline.llm_profile_runner(session) if profiles else None
                ),
                skip_families=frozenset(fresh),
                quarantined=held,
                company_plan=(
                    list_plan.company if scope != "contacts" else empty_plan
                ),
                # The people half is withheld by passing nobody rather than by
                # a flag inside the pipeline: the pipeline's rule is that a
                # contact pass happens when there are contacts and a plan for
                # them, and keeping that rule single is what stops a third
                # caller inventing a fourth way to skip it.
                contacts=people if scope != "company" else [],
                contact_plan=(
                    list_plan.contact if scope != "company" else None
                ),
                run_contact_family=pipeline.llm_contact_runner(session, run_id=run_id),
                contact_skip=contact_skip,
                icp_version_ids=list_plan.icp_version_ids,
                run_extraction=pipeline.llm_signal_extractor(session, run_id=run_id),
                signal_type_keys=list_plan.type_keys,
                run_qualification=qualification.llm_qualifier(
                    session, run_id=run_id, icps=list_plan.icps
                ),
                # Safe only because the runner above was given a factory, and
                # asserted here rather than guessed by the pipeline: a runner
                # that shares one session would race on it.
                concurrent_families=True,
            )
        except Exception as exc:  # noqa: BLE001 — one account must not cost the batch
            report.failed += 1
            report.accounts.append(
                ResearchAccountOut(
                    account_id=account.id, name=account.name,
                    outcome="failed", detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        stored = sum(result.evidence_by_family.values())
        report.evidence_stored += stored
        outcome = {"complete": "researched"}.get(result.status, result.status)
        if outcome == "researched":
            report.researched += 1
        elif outcome == "partial":
            report.partial += 1
        elif outcome == "failed":
            report.failed += 1
        else:
            report.halted += 1

        if result.halted:
            detail = result.halted
        elif result.failed_families:
            # Once per distinct reason: one misrouted provider fails every
            # family the same way, and four copies of it bury the fix.
            reasons = list(dict.fromkeys(result.failed_families.values()))
            n = len(result.failed_families)
            detail = f"{n} source{'s' if n != 1 else ''} failed — " + "; ".join(reasons)
        else:
            detail = f"{stored} evidence rows"
        if result.reused:
            detail += (
                f" · reused {', '.join(result.reused)} (inside the {window}-day window)"
            )
        if chosen_people and not contact_families:
            # Their company was still worth covering; say why the person was not.
            detail += (
                " · this list's ICPs ask for no person-level signals, so only the "
                "company was researched"
            )
        if contact_families and not result.halted:
            if people:
                n_people = len(result.contacts_researched)
                passages = sum(result.contact_evidence.values())
                report.contacts_researched += n_people
                report.contact_evidence += passages
                report.evidence_stored += passages
                if n_people:
                    detail += (
                        f" · {n_people} contact{'s' if n_people != 1 else ''} researched, "
                        f"{passages} passage{'s' if passages != 1 else ''}"
                    )
                if result.contact_failed:
                    detail += " · contact research failed — " + "; ".join(
                        dict.fromkeys(result.contact_failed.values())
                    )
            else:
                # Research still covered the company. The people need finding
                # first: nobody matches the ICP's personas with a verified email.
                report.no_contacts += 1
                detail += " · no ICP contact with a verified email — run Enrich contacts first"
        report.signals_stored += result.signals_stored
        report.signals_dropped += result.signals_dropped
        if result.signals_failed:
            detail += f" · signals not extracted — {result.signals_failed}"
        elif result.signals_stored or result.signals_dropped:
            detail += f" · {result.signals_stored} signal{'s' if result.signals_stored != 1 else ''}"
            if result.signals_dropped:
                detail += f" ({result.signals_dropped} dropped — citations did not resolve)"
        if result.qualification_failed:
            report.qualification_failed += 1
            detail += f" · not scored — {result.qualification_failed}"
        elif result.qualified:
            report.qualified += 1
            band = result.priority_band or "low"
            report.bands[band] = report.bands.get(band, 0) + 1
            detail += f" · priority {result.priority_score:.0f} ({band})"
            if result.unsupported_dimensions:
                n = len(result.unsupported_dimensions)
                detail += (
                    f", {n} dimension{'s' if n != 1 else ''} unsupported "
                    f"({', '.join(result.unsupported_dimensions)})"
                )
        elif result.qualification_note:
            report.not_qualified += 1
            detail += f" · not scored — {result.qualification_note}"
        report.accounts.append(
            ResearchAccountOut(
                account_id=account.id,
                name=account.name,
                run_id=result.run_id,
                outcome=outcome,
                detail=detail,
                evidence_by_family=dict(result.evidence_by_family),
                gaps=[
                    {
                        "family": g.family,
                        "status": g.status,
                        "unreachable": list(g.unreachable),
                        "detail": g.detail,
                    }
                    for g in (result.gaps or [])
                ],
            )
        )

        if result.rate_limited:
            # **Stop, rather than buy the same refusal for every account
            # left.** A 429 fails in milliseconds, so a limited run reaches
            # the next account sooner than a healthy one — the call rate rises
            # exactly when it must fall. Measured on a fifty-account list, the
            # last five accounts each lost all five sources and the final
            # minute held twenty-five calls, every one refused.
            #
            # A short per-minute ceiling is waited out once; anything else
            # ends the loop. The accounts not reached are reported as not
            # reached, which is honest and re-runnable — their families are
            # untouched, so a later run researches them at full cost and no
            # evidence has been lost. Converting them to `partial` at speed,
            # which is what happened before, instead left forty accounts
            # looking researched and empty.
            wait = result.rate_limit_retry_after
            daily = "perday" in (result.rate_limit_quota or "").lower().replace("_", "")
            # A spend cap is never waited out. It does not reset on a clock and
            # no backoff reaches the other side of it.
            if not result.spend_capped and not daily and wait is not None and wait <= RATE_LIMIT_MAX_WAIT:
                log.warning(
                    "lists.research rate limited, waiting %.0fs quota=%s",
                    wait, result.rate_limit_quota or "unnamed",
                )
                report.rate_limit_waited = (report.rate_limit_waited or 0.0) + wait
                await asyncio.sleep(wait)
                continue
            named = result.rate_limit_quota or "unnamed"
            report.stopped_early = (
                f"stopped after {report.attempted} of {len(ready)} accounts — the model "
                f"provider refused on quota ({named})"
                + (f", retry after {wait:g}s" if wait is not None else "")
                + ". The accounts not reached were not researched and nothing was "
                "spent on them; "
                + (
                    "raise the project spend cap and re-run."
                    if result.spend_capped
                    else "re-run once the quota resets."
                )
            )
            log.warning("lists.research %s", report.stopped_early)
            break

    await session.commit()
    return report


@router.post("/accounts/{account_id}/run-research", response_model=ResearchOut)
async def run_research_for_account(
    account_id: uuid.UUID,
    list_id: uuid.UUID | None = Query(
        None, description="Which list's ICPs decide what to look for. Only needed "
                          "when the account is on more than one."
    ),
    contact_ids: list[uuid.UUID] | None = Query(
        None, description="Research only these people at the account. Omit for the company."
    ),
    force: bool = Query(False),
    force_scope: str = Query("company", pattern="^(both|company|contacts)$"),
    scope: str = Query("both", pattern="^(both|company|contacts)$"),
    tier: str = Query("deep", pattern="^(light|standard|deep)$"),
    fast_sweep: bool = Query(True),
    profiles: bool = Query(True),
    session: AsyncSession = Depends(get_session),
):
    """Research one account — or named people at it — from the account screen.

    **Delegates to the list route rather than repeating it.** What to look for
    comes from `plan_for_list`: a list's ICPs decide which signal types are in
    scope, and the reuse window, the quarantine and the fast-sweep gate all
    hang off that plan. Reimplementing any of it here would be a second
    research path to keep in step, and the first thing to drift would be the
    thing that decides what gets bought.

    So the only work this route does is answer "which list". An account on one
    list has an obvious answer. An account on several has a real question —
    their ICPs can differ, and the plans with them — so rather than picking the
    newest and quietly researching against the wrong one, it says which lists
    those are and asks to be told.
    """
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "account not found")

    memberships = (
        await session.execute(
            select(AccountList)
            .join(AccountListMember, AccountListMember.list_id == AccountList.id)
            .where(AccountListMember.account_id == account_id)
            .order_by(AccountList.label)
        )
    ).scalars().all()
    if not memberships:
        return ResearchOut(
            ran=False,
            blocked=(
                f"{account.name} is on no list, and a list's ICPs are what decide "
                "what research looks for. Add it to one first."
            ),
        )
    if list_id is not None:
        if not any(m.id == list_id for m in memberships):
            raise HTTPException(404, "that list does not hold this account")
        chosen = list_id
    elif len(memberships) == 1:
        chosen = memberships[0].id
    else:
        raise HTTPException(
            409,
            {
                "error": "which_list",
                "message": (
                    f"{account.name} is on {len(memberships)} lists, whose ICPs may "
                    "ask for different things. Say which to research for."
                ),
                "lists": [{"id": str(m.id), "label": m.label} for m in memberships],
            },
        )

    return await run_research_for_list(
        list_id=chosen,
        limit=1,
        payload=ResearchTargetsIn(
            account_ids=[account_id], contact_ids=list(contact_ids or [])
        ),
        force=force,
        force_scope=force_scope,
        scope=scope,
        tier=tier,
        fast_sweep=fast_sweep,
        profiles=profiles,
        session=session,
    )


class QualifyAccountOut(BaseModel):
    account_id: uuid.UUID
    name: str
    #: `qualified`, `skipped` (nothing to judge, or identity unconfirmed), `failed`.
    outcome: str
    detail: str = ""
    priority_score: float | None = None
    priority_band: str | None = None
    #: Dimensions whose citations did not resolve: scored 0 and named here.
    unsupported: list[str] = Field(default_factory=list)
    #: Signals written from evidence already held, before scoring.
    signals_stored: int = 0


class QualifyOut(BaseModel):
    ran: bool = True
    blocked: str | None = None
    attempted: int = 0
    qualified: int = 0
    bands: dict[str, int] = Field(default_factory=dict)
    #: New signals read out of evidence already held, facts already known, and
    #: conclusions the guard refused.
    signals_stored: int = 0
    signals_duplicate: int = 0
    signals_dropped: int = 0
    #: Nothing to judge yet — no live signals. The fix is research, not a rerun.
    skipped: int = 0
    failed: int = 0
    accounts: list[QualifyAccountOut] = Field(default_factory=list)


@router.post("/lists/{list_id}/qualify", response_model=QualifyOut)
async def qualify_list(
    list_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=100),
    payload: AccountIdsIn | None = Body(None),
    session: AsyncSession = Depends(get_session),
):
    """Re-read the evidence already held, then score what it comes to.

    **No search and no provider credits** — the two or three model calls are
    the interpretation, not the gathering. That is what makes it the answer to
    "I added a signal type" or "I widened a TTL": the reuse window deliberately
    stops research paying twice for a search, which would otherwise leave a new
    type unable to reach evidence found yesterday.

    Extraction runs first, so a type added a minute ago applies to everything
    on the account. Then the six dimensions, if anything is live to judge.

    **Unconfirmed identities are skipped**, for the reason they are skipped
    everywhere: a judgement about a company nobody has verified is a judgement
    about whoever the spreadsheet row happened to match.
    """
    from app.models.account import Run
    from app.services import demo, llm, pipeline, qualification
    from app.services import research as research_service

    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")

    try:
        await llm.assert_may_call(session, "qualification_assessment")
    except Exception as exc:  # noqa: BLE001 — reported, not raised at the rep
        return QualifyOut(ran=False, blocked=str(exc))

    stmt = (
        select(Account)
        .join(AccountListMember, AccountListMember.account_id == Account.id)
        .where(AccountListMember.list_id == list_id)
        .order_by(Account.name)
    )
    if payload is not None:
        stmt = stmt.where(Account.id.in_(payload.account_ids))
    members = (await session.execute(stmt)).scalars().all()

    report = QualifyOut()
    mode = await demo.current_mode(session)
    # The ICP's types, so a re-read cannot produce a signal the list is not
    # worked for — the same rule research follows.
    list_plan = await research_service.plan_for_list(session, list_id)
    type_keys = list_plan.type_keys
    for account in members:
        if account.resolution_status != "resolved":
            report.skipped += 1
            report.accounts.append(
                QualifyAccountOut(
                    account_id=account.id, name=account.name, outcome="skipped",
                    detail=f"identity is {account.resolution_status} — confirm it first",
                )
            )
            continue
        if report.attempted >= limit:
            break

        report.attempted += 1
        run = Run(
            account_id=account.id, stage="qualification", status="running",
            triggered_by="rep", mode=mode, started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()
        try:
            read = await pipeline.extract_only(
                session,
                account=account,
                run_id=run.id,
                type_keys=type_keys,
                extractor=pipeline.llm_signal_extractor(session, run_id=run.id),
            )
            report.signals_stored += read.signals_stored
            report.signals_duplicate += read.signals_duplicate
            report.signals_dropped += read.signals_dropped
            outcome = await qualification.llm_qualifier(
                session, run_id=run.id, icps=list_plan.icps
            )(account)
        except Exception as exc:  # noqa: BLE001 — one account must not cost the batch
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            report.failed += 1
            report.accounts.append(
                QualifyAccountOut(
                    account_id=account.id, name=account.name, outcome="failed",
                    detail=run.error,
                )
            )
            continue

        run.finished_at = datetime.now(UTC)
        if not outcome.qualified:
            # Nothing was judged, so the run is not a success to be counted.
            run.status = "cancelled"
            report.skipped += 1
            detail = outcome.reason or "nothing to judge"
            if read.signals_stored:
                detail = f"{read.signals_stored} new signal(s) read, but {detail}"
            report.accounts.append(
                QualifyAccountOut(
                    account_id=account.id, name=account.name, outcome="skipped",
                    detail=detail, signals_stored=read.signals_stored,
                )
            )
            continue

        run.status = "succeeded"
        report.qualified += 1
        band = outcome.priority_band or "low"
        report.bands[band] = report.bands.get(band, 0) + 1
        detail = f"priority {outcome.priority_score:.0f} ({band}), context v{outcome.context_version}"
        if read.signals_stored:
            detail = f"{read.signals_stored} new signal(s) · " + detail
        if outcome.unsupported:
            detail += f" · unsupported: {', '.join(outcome.unsupported)}"
        if outcome.reused_from is not None:
            detail += " · nothing changed since the last run, so its judgement was kept"
        if outcome.narrative_failed:
            detail += f" · no narrative — {outcome.narrative_failed}"
        report.accounts.append(
            QualifyAccountOut(
                account_id=account.id, name=account.name, outcome="qualified",
                detail=detail, priority_score=outcome.priority_score,
                priority_band=outcome.priority_band, unsupported=list(outcome.unsupported),
                signals_stored=read.signals_stored,
            )
        )

    await session.commit()
    return report


class ContactOut(BaseModel):
    """One person, with everything enrichment learned about them.

    Wide on purpose. Enrichment writes eight fields across three providers and
    until now the UI rendered none of them — a rep could not tell whether
    Apollo had found the right CTO, or why an address came back `risky`,
    without querying the database. The screen decides which columns to show;
    the API's job is to have them.
    """

    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    #: Off limits, and why. Set by a rep; nothing clears it but a rep.
    do_not_contact: bool = False
    do_not_contact_reason: str | None = None
    #: Their company's rating, read for the ICP the list is worked for.
    qualification_score: float | None = None
    qualification_band: str | None = None
    icp_name: str | None = None
    gate: str = "not_qualified"
    gate_detail: str = ""
    account_domain: str | None = None
    full_name: str
    title: str | None = None
    seniority: str | None = None
    #: Functional area — `engineering`, `finance`. Distinct from `buying_role`,
    #: which is what they do to a *purchase*.
    persona_role: str | None = None
    buying_role: str | None = None
    email: str | None = None
    #: `verified`, `risky`, `invalid`, `unverified`. Only `verified` may be
    #: sent to — a provider's own `guessed` grade lands here as `risky`.
    email_status: str | None = None
    email_confidence: float | None = None
    #: Which provider supplied it, so a bad address is traceable to a source
    #: rather than costing trust in every address on the list.
    email_provider: str | None = None
    phone: str | None = None
    phone_status: str | None = None
    phone_provider: str | None = None
    linkedin_url: str | None = None
    #: True when a model inferred this person rather than a provider or a
    #: file naming them. Never treated as fact.
    is_hypothesis: bool = False
    #: When the address was last graded verified, and whether that is long
    #: enough ago to check again — `verification.EMAIL_RECHECK_DAYS`.
    email_verified_at: datetime | None = None
    email_recheck: bool = False
    created_at: datetime
    updated_at: datetime | None = None


CONTACT_SORTS = {
    "full_name": Contact.full_name,
    "title": Contact.title,
    "seniority": Contact.seniority,
    "buying_role": Contact.buying_role,
    "persona_role": Contact.persona_role,
    "email": Contact.email,
    "email_status": Contact.email_status,
    "email_provider": Contact.email_provider,
    "phone": Contact.phone,
    "created_at": Contact.created_at,
    # Every column the contacts table offers. The two account fields need the
    # join both routes now make — without it, sorting by company was a 422
    # the table reported as an error for a header click.
    "phone_status": Contact.phone_status,
    "phone_provider": Contact.phone_provider,
    "linkedin_url": Contact.linkedin_url,
    "email_confidence": Contact.email_confidence,
    "is_hypothesis": Contact.is_hypothesis,
    "account_name": Account.name,
    "account_domain": Account.domain,
}


async def _ratings(session: AsyncSession, account_ids, icp_profile_ids=None) -> dict:
    """One rating per account, computed once for the whole table.

    Per account rather than per row: a company's rating is the same for
    everybody who works there, and the roll-up is arithmetic over one stored
    qualification (`icp_scores`) — no model call, whatever the table's length.
    """
    from app.services import icp_scores
    from app.services.promotion import queue_gate

    minimum = await queue_gate(session)
    out: dict = {}
    for account_id in dict.fromkeys(account_ids):
        out[account_id] = await icp_scores.best_rating(
            session, account_id, icp_profile_ids, minimum=minimum
        )
    return out


async def _list_icps(session: AsyncSession, list_id) -> list:
    return [
        r[0]
        for r in (
            await session.execute(
                select(account_list_icp.c.icp_profile_id).where(
                    account_list_icp.c.list_id == list_id
                )
            )
        ).all()
    ]


def _contact_out(contact: Contact, account: Account, rating: dict | None = None) -> ContactOut:
    return ContactOut(
        **(rating or {}),
        id=contact.id,
        account_id=account.id,
        account_name=account.name,
        account_domain=account.domain,
        **{
            k: getattr(contact, k)
            for k in (
                "full_name", "title", "seniority", "persona_role", "buying_role",
                "email", "email_status", "email_confidence", "email_provider",
                "phone", "phone_status", "phone_provider", "linkedin_url",
                "is_hypothesis", "email_verified_at", "created_at", "updated_at",
                "do_not_contact", "do_not_contact_reason",
            )
        },
        email_recheck=verification.needs_recheck(contact),
    )


class SuppressionIn(BaseModel):
    contact_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    do_not_contact: bool = True
    #: Required to set the flag. Free text: "left the company", "asked us to stop".
    reason: str | None = None


class SuppressionOut(BaseModel):
    updated: int
    not_found: int = 0


@router.post("/contacts/suppression", response_model=SuppressionOut)
async def set_suppression(payload: SuppressionIn, session: AsyncSession = Depends(get_session)):
    """Mark people do-not-contact, or allow them again.

    Not a delete: their evidence, signals and outreach history stay exactly as
    they are. What changes is that enrichment, research, queueing and execution
    all refuse them from here on.
    """
    if payload.do_not_contact and not (payload.reason or "").strip():
        raise HTTPException(422, "a reason is required to mark somebody do-not-contact")

    rows = list(
        (
            await session.execute(select(Contact).where(Contact.id.in_(payload.contact_ids)))
        ).scalars()
    )
    for contact in rows:
        contact.do_not_contact = payload.do_not_contact
        contact.do_not_contact_reason = payload.reason.strip() if payload.do_not_contact else None
        contact.do_not_contact_at = datetime.now(UTC) if payload.do_not_contact else None
    await session.commit()
    return SuppressionOut(updated=len(rows), not_found=len(set(payload.contact_ids)) - len(rows))


@router.get("/accounts/{account_id}/contacts", response_model=list[ContactOut])
async def account_contacts(
    account_id: uuid.UUID,
    sort: Sort = Depends(sort_params),
    session: AsyncSession = Depends(get_session),
):
    """Everyone known at one company."""
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "account not found")

    sort = validate_sort(sort, CONTACT_SORTS)
    stmt = sort.apply(
        # Joined for the same allowlist as the list route. One account, so the
        # join adds nothing but makes `account_name` / `account_domain` valid
        # here rather than a column the query has no table for.
        select(Contact)
        .join(Account, Account.id == Contact.account_id)
        .where(Contact.account_id == account_id),
        CONTACT_SORTS,
        Contact.full_name.asc(),
    )
    rows = list((await session.execute(stmt)).scalars())
    # No list in sight, so the rating is the best across every active ICP.
    rating = (await _ratings(session, [account_id])).get(account_id)
    return [_contact_out(c, account, rating) for c in rows]


@router.get("/lists/{list_id}/contacts", response_model=list[ContactOut])
async def list_contacts(
    list_id: uuid.UUID,
    sort: Sort = Depends(sort_params),
    session: AsyncSession = Depends(get_session),
):
    """Everyone on a list, across its accounts.

    The list is where enrichment is triggered, so it is where its results have
    to be visible. Reading them one account at a time would mean opening
    forty pages to answer "did that run find anything".
    """
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")

    sort = validate_sort(sort, CONTACT_SORTS)
    stmt = (
        select(Contact, Account)
        .join(Account, Account.id == Contact.account_id)
        .join(AccountListMember, AccountListMember.account_id == Account.id)
        .where(AccountListMember.list_id == list_id)
    )
    stmt = sort.apply(stmt, CONTACT_SORTS, Contact.full_name.asc())
    rows = (await session.execute(stmt)).all()
    # Read for the ICPs this list is worked for — the same pairing enrichment
    # and research use, so the number on the row is the one that applies here.
    ratings = await _ratings(
        session, [a.id for _, a in rows], await _list_icps(session, list_id)
    )
    return [_contact_out(c, a, ratings.get(a.id)) for c, a in rows]


@router.post("/lists/{list_id}/resolve", response_model=ResolveOut)
async def resolve_list_accounts(
    list_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    payload: AccountIdsIn | None = Body(None),
    recheck: bool = Query(
        False,
        description="Also run accounts waiting for review — when the sources have changed "
        "since they were last checked.",
    ),
    session: AsyncSession = Depends(get_session),
):
    """Tier 0 — identify the companies on this list before anything is spent.

    Deliberately **not** behind `require_setup`. Resolution is how an
    incompletely configured installation becomes usable, and it degrades
    sensibly: with only an Apollo key the domain lookup runs, with only an LLM
    key the web fallback runs, with neither the report says it was blocked
    rather than pretending it resolved nobody.

    `limit` defaults to 50 rather than the whole list. The first run on a new
    list is the one most likely to reveal that the CSV is wrong, and finding
    that out over 50 rows costs less than over 5,000.
    """
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")

    report = await resolution.resolve_list(
        session, list_id=list_id, limit=limit,
        account_ids=payload.account_ids if payload else None,
        include_reviewed=recheck,
    )
    await session.commit()
    return ResolveOut(
        ran=report.ran,
        blocked=report.blocked,
        order=report.order,
        checked=report.checked,
        resolved=report.resolved,
        needs_review=report.needs_review,
        unresolved=report.unresolved,
        unavailable=report.unavailable,
        outcomes=[
            {
                "account_id": str(o.account_id),
                "name": o.name,
                "outcome": o.outcome,
                "detail": o.detail,
                "sources_called": o.sources_called,
            }
            for o in report.outcomes
        ],
    )


@router.patch("/accounts/{account_id}/resolution", response_model=AccountOut)
async def set_account_resolution(
    account_id: uuid.UUID,
    payload: ResolutionPatch,
    session: AsyncSession = Depends(get_session),
):
    """Record what a rep decided about an account's identity.

    A human verdict outranks every source, so this writes what it is given
    without re-checking it — that is the point of the review step. The values
    are still normalised, because the partial unique index on `lower(domain)`
    is what stops a corrected domain creating a duplicate account, and it only
    works if every writer agrees on the form.
    """
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "account not found")

    if payload.domain is not None:
        cleaned = resolution.normalise_domain(payload.domain)
        if payload.domain.strip() and cleaned is None:
            raise HTTPException(
                422, f"{payload.domain!r} is not a domain — expected something like acme.com"
            )
        account.domain = cleaned
    if payload.linkedin_url is not None:
        cleaned = resolution.normalise_linkedin(payload.linkedin_url)
        if payload.linkedin_url.strip() and cleaned is None:
            raise HTTPException(
                422,
                "expected a LinkedIn *company* page (/company/...). An /in/ URL is a "
                "person, and storing one here sends a rep to a stranger's profile",
            )
        account.linkedin_url = cleaned
    if payload.industry is not None:
        account.industry = payload.industry or None
        account.industry_key = (
            " ".join(payload.industry.casefold().split()) if payload.industry else None
        )
    if payload.employee_count is not None:
        # Through the recorder, so a rep correcting a headcount leaves the same
        # trail an automated observation would. A number typed today is an
        # observation made today.
        sizing.record_headcount(account, payload.employee_count)

    if payload.status is not None:
        account.resolution_status = payload.status
        account.resolved_by = "rep"
        account.resolved_at = datetime.now(UTC)
        if payload.status == "resolved":
            # A person looked at it and said yes. Confidence is theirs, and the
            # note explaining a machine's doubt no longer applies.
            account.resolution_confidence = 1.0
            account.resolution_note = None

    await session.commit()
    await session.refresh(account)
    return account


@router.get("/lists/{list_id}/targeting", response_model=ListTargetingOut)
async def get_targeting(
    list_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")

    services = [
        r[0]
        for r in (
            await session.execute(
                select(account_list_service.c.service_id).where(
                    account_list_service.c.list_id == list_id
                )
            )
        ).all()
    ]
    icps = [
        r[0]
        for r in (
            await session.execute(
                select(account_list_icp.c.icp_profile_id).where(
                    account_list_icp.c.list_id == list_id
                )
            )
        ).all()
    ]
    return ListTargetingOut(
        service_ids=services,
        icp_profile_ids=icps,
        available_icps=sorted(await _reachable_icps(session, services)),
    )


@router.put("/lists/{list_id}/targeting", response_model=ListTargetingOut)
async def set_targeting(
    list_id: uuid.UUID,
    payload: ListTargetingIn,
    session: AsyncSession = Depends(get_session),
):
    """Set which services and ICPs this list is worked for.

    Not gated on setup: choosing what a list is for is how you get *out* of an
    unconfigured state, and a list is cheap. Enrichment is the step that spends
    money, and that is where the gate sits.
    """
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")

    found = {
        r[0]
        for r in (
            await session.execute(
                select(ServiceCatalog.id).where(
                    ServiceCatalog.id.in_(payload.service_ids)
                )
            )
        ).all()
    }
    missing = [str(i) for i in payload.service_ids if i not in found]
    if missing:
        raise HTTPException(422, f"unknown service(s): {', '.join(missing)}")

    reachable = await _reachable_icps(session, payload.service_ids)
    stray = [str(i) for i in payload.icp_profile_ids if i not in reachable]
    if stray:
        # Refused, not filtered. An ICP the chosen services do not sell to
        # would target a buyer nobody picked, and dropping it quietly would
        # make the list enrich for fewer profiles than the screen showed.
        raise HTTPException(
            422,
            f"{len(stray)} ICP(s) are not linked to the chosen services",
        )

    await session.execute(
        account_list_service.delete().where(
            account_list_service.c.list_id == list_id
        )
    )
    await session.execute(
        account_list_icp.delete().where(account_list_icp.c.list_id == list_id)
    )
    for sid in payload.service_ids:
        await session.execute(
            account_list_service.insert().values(list_id=list_id, service_id=sid)
        )
    for pid in payload.icp_profile_ids:
        await session.execute(
            account_list_icp.insert().values(list_id=list_id, icp_profile_id=pid)
        )
    await session.commit()

    return ListTargetingOut(
        service_ids=list(payload.service_ids),
        icp_profile_ids=list(payload.icp_profile_ids),
        available_icps=sorted(reachable),
    )


class EnrichTargetsIn(BaseModel):
    """Who to enrich: whole accounts, named people, or the whole list.

    Both are narrowing, never widening — empty means the whole list, which is
    what the tab-wide button sends.
    """

    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    #: Exactly the people picked on the Contacts tab.
    contact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


@router.post(
    "/lists/{list_id}/verify-contacts",
    response_model=VerifyOut,
    # Enrichment only. This spends provider credits, so it is genuinely gated —
    # but on the provider it calls, not on a sending credential it never uses.
    dependencies=[Depends(requires("enrichment"))],
)
async def verify_contacts(
    list_id: uuid.UUID,
    service_id: uuid.UUID = Query(
        ..., description="Which service this list is being enriched for."
    ),
    payload: EnrichTargetsIn | None = Body(None),
    session: AsyncSession = Depends(get_session),
):
    """Run this list's unverified contacts through the enrichment waterfall.

    The step between importing a list and doing anything with it. A CSV contact
    is a claim — the spreadsheet says the address exists, and nobody has
    established that sending to it will not bounce a sending domain.

    **`service_id` is required.** Without it this ran alphabetically over every
    unverified contact, which spends a metered provider finding a junior
    developer's address when the service needed the CTO — and the list then
    looks enriched. The service names the ICP, the ICP says who is worth
    reaching, and both are recorded on the report so the spend stays
    explainable. A service with no ICP is refused rather than defaulted: see
    `docs/11`.

    Only unverified contacts are asked about, because every provider call is
    metered and re-checking a verified one spends money to learn what is
    already on the row.
    """
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")

    # The ICPs the list was set up for, narrowed to the service being run.
    # Empty means "every ICP this service sells to", which is what
    # `resolve_targeting` does with None — a list nobody has targeted yet still
    # enriches for the whole service rather than refusing.
    chosen = [
        r[0]
        for r in (
            await session.execute(
                select(account_list_icp.c.icp_profile_id).where(
                    account_list_icp.c.list_id == list_id
                )
            )
        ).all()
    ]
    reachable = await _reachable_icps(session, [service_id])
    narrowed = [i for i in chosen if i in reachable] or None

    try:
        report = await verification.verify_list(
            session,
            list_id=list_id,
            service_id=service_id,
            icp_profile_ids=narrowed,
            account_ids=payload.account_ids if payload else None,
            contact_ids=payload.contact_ids if payload else None,
        )
    except verification.NoServiceIcpError as exc:
        # 409, not 400: nothing about the request is malformed, the system is
        # in the wrong state for it, and it is a state the caller can change.
        raise HTTPException(
            409,
            {
                "error": "service_not_ready",
                "message": str(exc),
            },
        ) from exc
    await session.commit()
    return VerifyOut(
        ran=report.ran,
        blocked=report.blocked,
        waterfall=report.waterfall,
        wanted=report.wanted,
        service_code=report.service_code,
        icp_versions=[
            IcpVersionOut(name=name, version=version)
            for name, version in (report.icp_versions or [])
        ],
        out_of_persona=report.out_of_persona,
        unknown_persona=report.unknown_persona,
        checked=report.checked,
        verified=report.verified,
        reconfirmed_free=report.reconfirmed_free,
        saved_to_apollo=report.saved_to_apollo,
        apollo_note=report.apollo_note,
        with_phone=report.with_phone,
        with_linkedin=report.with_linkedin,
        contact_linkedin_from_provider=report.contact_linkedin_from_provider,
        contact_linkedin_from_site=report.contact_linkedin_from_site,
        company_linkedin_from_provider=report.company_linkedin_from_provider,
        company_linkedin_from_site=report.company_linkedin_from_site,
        linkedin_notes=report.linkedin_notes,
        risky=report.risky,
        not_found=report.not_found,
        unavailable=report.unavailable,
        outcomes=[
            VerifyOutcomeOut(
                contact_id=o.contact_id, full_name=o.full_name, outcome=o.outcome,
                detail=o.detail, providers_called=o.providers_called,
            )
            for o in report.outcomes
        ],
    )


# Ungated on purpose. Importing is parsing a spreadsheet: it calls no vendor,
# spends nothing, and is reversible by deleting the list. It used to require a
# La Growth Machine credential, which meant a CSV could not be read because
# nothing could be *sent* — two stages apart.
@router.post(
    "/lists/{list_id}/import",
    response_model=ImportOut,
)
async def import_csv(
    list_id: uuid.UUID,
    file: UploadFile = File(...),
    mapping: str = Query(..., description="JSON object of field → CSV header"),
    dry_run: bool = Query(True),
    session: AsyncSession = Depends(get_session),
):
    """Steps 2 and 3 — dry run, then the same call with ``dry_run=false``.

    Defaults to a dry run. An import that writes because a flag was forgotten is
    the failure this default exists to prevent.
    """
    import json

    lst = await session.get(AccountList, list_id)
    if lst is None:
        raise HTTPException(404, "list not found")

    try:
        mapping_dict = json.loads(mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "mapping must be a JSON object") from exc

    try:
        _, rows = spreadsheet.parse_upload(await file.read(), file.filename)
    except spreadsheet.UnreadableUpload as exc:
        raise HTTPException(400, str(exc)) from exc
    report = await csv_import.run_import(
        session,
        list_id=list_id,
        rows=rows,
        mapping=mapping_dict,
        added_by="bertie",
        dry_run=dry_run,
    )
    return ImportOut(
        total_rows=report.total_rows,
        committed=report.committed,
        counts=report.counts,
        rows=[
            RowOut(
                row_number=r.row_number, name=r.name, domain=r.domain,
                outcome=r.outcome, detail=r.detail, contact_name=r.contact_name,
            )
            for r in report.rows
        ],
        grain=report.grain,
        accounts_touched=report.accounts_touched,
        contacts_created=report.contacts_created,
        contacts_updated=report.contacts_updated,
    )
