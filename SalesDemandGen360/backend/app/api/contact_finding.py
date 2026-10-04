"""Search-first enrichment: check the company, suggest its people, reveal the accepted.

The routes behind the list screen's *Check company* and *Find contacts*
actions, and the suggested-contacts panel. What each spends is stated on the
route, because the difference is the point of the flow:

* `check-companies` — the website is free; Apollo's organisation record is one
  credit, asked only while country or LinkedIn page is missing.
* `find-contacts` — Apollo's People API Search. **Free.**
* `suggestions/decide` — a rep's accept or reject. Nothing is called.
* `suggestions/reveal` — one credit per accepted person Apollo has data for.
  Never personal emails, never phones.

See `services/company_check.py` and `services/contact_suggestions.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import requires
from app.database import get_session
from app.models.account import Account, AccountList, AccountListMember, account_list_icp
from app.models.config import EnrichmentConfig
from app.services import apollo_people, company_check, contact_suggestions, verification
from app.services.providers import ProviderError
from app.services.versioning import get_active

router = APIRouter(tags=["contact finding"])

#: Gated on the enrichment provider, as enrichment is — not on outreach.
ENRICHMENT = [Depends(requires("enrichment"))]
NO_KEY = "No Apollo key is stored — add one under Setup before searching or revealing."


class SelectionIn(BaseModel):
    """A selection, by id. Omitted, every confirmed account on the list."""

    account_ids: list[uuid.UUID] | None = Field(default=None, max_length=1000)


async def _confirmed_accounts(
    session: AsyncSession, list_id: uuid.UUID, account_ids: list[uuid.UUID] | None
) -> list[Account]:
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")
    stmt = (
        select(Account)
        .join(AccountListMember, AccountListMember.account_id == Account.id)
        .where(AccountListMember.list_id == list_id, Account.resolution_status == "resolved")
        .order_by(Account.name)
    )
    if account_ids:
        stmt = stmt.where(Account.id.in_(account_ids))
    return list((await session.execute(stmt)).scalars())


def _apollo_failed(exc: ProviderError) -> HTTPException:
    return HTTPException(502, {"error": "apollo_failed", "message": str(exc)})


# ==========================================================================
# the company check
# ==========================================================================
class OptionOut(BaseModel):
    value: str
    source: str


class ConflictOut(BaseModel):
    field: str
    current: str | None = None
    options: list[OptionOut] = Field(default_factory=list)
    note: str


class FillOut(BaseModel):
    field: str
    value: str
    source: str


class CheckedAccountOut(BaseModel):
    account_id: uuid.UUID
    name: str
    domain: str | None = None
    filled: list[FillOut] = Field(default_factory=list)
    conflicts: list[ConflictOut] = Field(default_factory=list)
    website_answered: bool = False
    apollo_asked: bool = False
    note: str = ""


class CompanyCheckOut(BaseModel):
    checked: int = 0
    #: False when no Apollo key is stored: only the website was read.
    apollo_available: bool = False
    #: Set when Apollo failed part-way; the rest were checked from the website.
    apollo_error: str | None = None
    apollo_credits: int = 0
    filled: int = 0
    conflicts: int = 0
    accounts: list[CheckedAccountOut] = Field(default_factory=list)


@router.post(
    "/lists/{list_id}/check-companies", response_model=CompanyCheckOut, dependencies=ENRICHMENT
)
async def check_companies(
    list_id: uuid.UUID,
    payload: SelectionIn | None = Body(None),
    session: AsyncSession = Depends(get_session),
):
    """Confirm country and LinkedIn page for confirmed accounts; list what disagrees."""
    accounts = await _confirmed_accounts(session, list_id, payload.account_ids if payload else None)
    people = await apollo_people.from_credentials(session)
    report = CompanyCheckOut(apollo_available=people is not None)
    for account in accounts:
        try:
            result = await company_check.check_account(account, people=people)
        except ProviderError as exc:
            # Apollo failing is not the website failing: finish from the site,
            # and say once why Apollo was not asked for the rest.
            report.apollo_error = str(exc)
            people = None
            result = await company_check.check_account(account, people=None)
        report.checked += 1
        report.apollo_credits += result.apollo_credits
        report.filled += len(result.filled)
        report.conflicts += len(result.conflicts)
        report.accounts.append(
            CheckedAccountOut(
                account_id=account.id,
                name=account.name,
                domain=account.domain,
                filled=[FillOut(**f) for f in result.filled],
                conflicts=[ConflictOut(**asdict(c)) for c in result.conflicts],
                website_answered=result.website_answered,
                apollo_asked=result.apollo_asked,
                note=result.note,
            )
        )
    await session.commit()
    return report


class OpenConflictsOut(BaseModel):
    account_id: uuid.UUID
    name: str
    domain: str | None = None
    hq_country: str | None = None
    linkedin_url: str | None = None
    checked_at: str | None = None
    conflicts: list[ConflictOut] = Field(default_factory=list)


def _open(account: Account) -> OpenConflictsOut:
    check = account.company_check or {}
    return OpenConflictsOut(
        account_id=account.id,
        name=account.name,
        domain=account.domain,
        hq_country=account.hq_country,
        linkedin_url=account.linkedin_url,
        checked_at=check.get("checked_at"),
        conflicts=[ConflictOut(**c) for c in check.get("conflicts") or []],
    )


@router.get("/lists/{list_id}/company-conflicts", response_model=list[OpenConflictsOut])
async def company_conflicts(list_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Accounts on this list whose last check left something for a rep."""
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")
    accounts = (
        await session.execute(
            select(Account)
            .join(AccountListMember, AccountListMember.account_id == Account.id)
            .where(AccountListMember.list_id == list_id, Account.company_check.is_not(None))
            .order_by(Account.name)
        )
    ).scalars()
    return [row for row in (_open(a) for a in accounts) if row.conflicts]


class SettleIn(BaseModel):
    field: str = Field(pattern="^(domain|linkedin_url|hq_country)$")
    #: The value to use. Omitted or null keeps what is on record.
    value: str | None = None


@router.post("/accounts/{account_id}/company-check/settle", response_model=OpenConflictsOut)
async def settle_conflict(
    account_id: uuid.UUID, payload: SettleIn, session: AsyncSession = Depends(get_session)
):
    """A rep's answer to one conflict. Remembered, so the next check does not ask again."""
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "account not found")
    try:
        company_check.settle(account, payload.field, payload.value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "another account already has that domain") from exc
    return _open(account)


# ==========================================================================
# suggested contacts
# ==========================================================================
class FoundAccountOut(BaseModel):
    account_id: uuid.UUID
    name: str
    requests: int = 0
    proposed: int = 0
    refreshed: int = 0
    on_list: int = 0
    known: int = 0
    already_decided: int = 0
    filtered: int = 0
    dropped: int = 0
    note: str = ""


class FindOut(BaseModel):
    #: False when nothing could be asked — a search that did not run must not
    #: read as one that found nobody.
    ran: bool
    blocked: str | None = None
    service_code: str | None = None
    icp_versions: list[dict] = Field(default_factory=list)
    per_persona: int = 5
    personas: list[str] = Field(default_factory=list)
    #: Personas with no titles and no buying role to search on.
    skipped_personas: list[str] = Field(default_factory=list)
    searches: int = 0
    proposed: int = 0
    refreshed: int = 0
    on_list: int = 0
    known: int = 0
    already_decided: int = 0
    filtered: int = 0
    #: Undecided suggestions from an earlier search that this one no longer keeps.
    dropped: int = 0
    accounts: list[FoundAccountOut] = Field(default_factory=list)


@router.post("/lists/{list_id}/find-contacts", response_model=FindOut, dependencies=ENRICHMENT)
async def find_contacts(
    list_id: uuid.UUID,
    service_id: uuid.UUID = Query(..., description="Which service these people are wanted for."),
    payload: SelectionIn | None = Body(None),
    session: AsyncSession = Depends(get_session),
):
    """Search Apollo for each ICP persona at each confirmed account. Free."""
    from app.api.lists import _reachable_icps

    accounts = await _confirmed_accounts(session, list_id, payload.account_ids if payload else None)
    chosen = [
        r[0]
        for r in (
            await session.execute(
                select(account_list_icp.c.icp_profile_id).where(account_list_icp.c.list_id == list_id)
            )
        ).all()
    ]
    reachable = await _reachable_icps(session, [service_id])
    try:
        service, versions = await verification.resolve_targeting(
            session,
            service_id=service_id,
            icp_profile_ids=[i for i in chosen if i in reachable] or None,
        )
    except verification.NoServiceIcpError as exc:
        raise HTTPException(409, {"error": "service_not_ready", "message": str(exc)}) from exc

    queries, skipped = contact_suggestions.persona_queries(*(v.definition for v in versions))
    report = FindOut(
        ran=False,
        service_code=service.code,
        icp_versions=[{"name": v.profile.name, "version": v.version} for v in versions],
        personas=[q.persona for q in queries],
        skipped_personas=skipped,
    )
    if not queries:
        names = ", ".join(sorted({v.profile.name for v in versions}))
        raise HTTPException(
            409,
            {
                "error": "service_not_ready",
                "message": f"{names} names no buyer personas to search for — add titles under ICP profiles",
            },
        )
    people = await apollo_people.from_credentials(session)
    if people is None:
        report.blocked = NO_KEY
        return report

    config = await get_active(session, EnrichmentConfig)
    report.per_persona = config.suggestions_per_persona if config else 5
    report.ran = True
    for account in accounts:
        try:
            found = await contact_suggestions.find_for_account(
                session, list_id=list_id, account=account, queries=queries,
                people=people, cap=report.per_persona,
            )
        except ProviderError as exc:
            await session.commit()
            raise _apollo_failed(exc) from exc
        report.accounts.append(FoundAccountOut(**asdict(found)))
        for name in ("proposed", "refreshed", "on_list", "known", "already_decided", "filtered", "dropped"):
            setattr(report, name, getattr(report, name) + getattr(found, name))
        report.searches += found.requests
    await session.commit()
    return report


class SuggestionOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    account_domain: str | None = None
    first_name: str | None = None
    #: Apollo's obfuscated surname — never a real one until revealed.
    last_name_hint: str | None = None
    title: str | None = None
    persona: str | None = None
    buying_role: str | None = None
    has_email: bool = False
    has_location: bool = False
    refreshed_at: datetime | None = None
    status: str
    note: str | None = None
    contact_id: uuid.UUID | None = None
    contact_name: str | None = None
    contact_email_status: str | None = None
    contact_has_linkedin: bool = False
    #: The profile of the contact this person is — once revealed, or when they
    #: were already on the list. Apollo's free search never returns one.
    linkedin_url: str | None = None
    #: Their company's rating, read for the ICPs this list is worked for. The
    #: person is a suggestion; the company is already scored, and that is what
    #: says whether revealing them is worth a credit.
    qualification_score: float | None = None
    qualification_band: str | None = None
    icp_name: str | None = None
    gate: str = "not_qualified"
    gate_detail: str = ""
    revealed_at: datetime | None = None


@router.get("/lists/{list_id}/suggestions", response_model=list[SuggestionOut])
async def list_suggestions(
    list_id: uuid.UUID,
    status: list[str] | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")
    rows = await contact_suggestions.for_list(session, list_id, tuple(status) if status else None)
    from app.api.lists import _list_icps, _ratings

    ratings = await _ratings(
        session, [a.id for _, a, *_rest in rows], await _list_icps(session, list_id)
    )
    return [
        SuggestionOut(
            **(ratings.get(a.id) or {}),
            id=s.id,
            account_id=a.id,
            account_name=a.name,
            account_domain=a.domain,
            first_name=s.first_name,
            last_name_hint=s.last_name_hint,
            title=s.title,
            persona=s.persona,
            buying_role=s.buying_role,
            has_email=s.has_email,
            has_location=s.has_location,
            refreshed_at=s.refreshed_at,
            status=s.status,
            note=s.note,
            contact_id=s.contact_id,
            contact_name=c.full_name if c else None,
            contact_email_status=c.email_status if c else None,
            contact_has_linkedin=bool(c and c.linkedin_url),
            linkedin_url=c.linkedin_url if c else None,
            revealed_at=s.revealed_at,
        )
        for s, a, c in rows
    ]


class DecideIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    status: str = Field(pattern="^(proposed|accepted|rejected)$")


class DecideOut(BaseModel):
    changed: int


@router.post("/lists/{list_id}/suggestions/decide", response_model=DecideOut)
async def decide_suggestions(
    list_id: uuid.UUID, payload: DecideIn, session: AsyncSession = Depends(get_session)
):
    """Accept, reject, or put back. Calls nothing and spends nothing."""
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")
    changed = await contact_suggestions.decide(session, list_id, list(payload.ids), payload.status)
    await session.commit()
    return DecideOut(changed=changed)


class RevealIn(BaseModel):
    #: Which accepted suggestions to reveal. Omitted, every accepted one on the list.
    ids: list[uuid.UUID] | None = Field(default=None, max_length=1000)


class RevealOut(BaseModel):
    ran: bool
    blocked: str | None = None
    asked: int = 0
    revealed: int = 0
    created: int = 0
    updated: int = 0
    verified: int = 0
    risky: int = 0
    no_email: int = 0
    linkedin: int = 0
    not_found: int = 0
    credits: int = 0
    #: Revealed before, or saved in the Apollo account — settled without buying.
    reused: int = 0
    #: Saved as contacts in the Apollo account, labelled Gen360.
    saved_to_apollo: int = 0
    save_error: str | None = None
    #: Apollo ran out of credits part-way; the rest stay accepted.
    stopped: str | None = None
    company_country: int = 0
    company_linkedin: int = 0
    notes: list[str] = Field(default_factory=list)


@router.post(
    "/lists/{list_id}/suggestions/reveal", response_model=RevealOut, dependencies=ENRICHMENT
)
async def reveal_suggestions(
    list_id: uuid.UUID,
    payload: RevealIn | None = Body(None),
    session: AsyncSession = Depends(get_session),
):
    """Reveal accepted suggestions — one credit per person Apollo has data for."""
    if await session.get(AccountList, list_id) is None:
        raise HTTPException(404, "list not found")
    accepted = [s for s, _, _ in await contact_suggestions.for_list(session, list_id, ("accepted",))]
    if payload and payload.ids:
        wanted = set(payload.ids)
        accepted = [s for s in accepted if s.id in wanted]
    people = await apollo_people.from_credentials(session)
    if people is None:
        return RevealOut(ran=False, blocked=NO_KEY, asked=len(accepted))
    try:
        report = await contact_suggestions.reveal(session, suggestions=accepted, people=people)
    except ProviderError as exc:
        await session.rollback()
        raise _apollo_failed(exc) from exc
    await session.commit()
    return RevealOut(ran=True, **asdict(report))
