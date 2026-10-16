"""Configuration endpoints — Domain 1.

Three behaviours are deliberate and worth reading before adding to this module:

1. **Versioned surfaces use PUT, not PATCH.** There is no partial update,
   because a partial update implies mutation and these rows are never mutated.
   A PUT writes a new version and deactivates the previous one.
2. **Credentials are write-only.** The response model has no field for the
   value; the read path returns ``last_four``.
3. **Signal types are deprecated, never deleted.** There is no DELETE route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.account import account_list_icp
from app.models.config import (
    EnrichmentConfig,
    IcpProfile,
    IcpProfileVersion,
    InstallationMode,
    IntegrationCredential,
    LlmConfig,
    ModelAvailability,
    OrgProfile,
    ProofPoint,
    ResearchSource,
    SalesRules,
    ScoringConfig,
    ServiceCatalog,
    SignalType,
    WritingSample,
    service_icp_link,
)
from app.schemas.config import (
    AvailabilityIn,
    AvailabilityOut,
    CredentialIn,
    CredentialOut,
    CredentialStateOut,
    EnrichmentConfigIn,
    EnrichmentConfigOut,
    IcpDefinitionIn,
    IcpProfileIn,
    IcpProfileOut,
    IcpServicesIn,
    IcpSourceProposal,
    IcpSourceSuggestions,
    LlmConfigIn,
    LlmConfigOut,
    ModeIn,
    ModeOut,
    ModelInUseOut,
    ModelOptionOut,
    OrgProfileIn,
    OrgProfileOut,
    ProofPointIn,
    ProofPointOut,
    ProviderAvailabilityOut,
    ProviderOut,
    QueryFamilyOut,
    ReadinessOut,
    ResearchConfigIn,
    ResearchConfigOut,
    AccountTrialOut,
    ResearchSourceIn,
    ResearchSourceOut,
    SourceTrialIn,
    SourceTrialOut,
    ResearchSourcePatch,
    SalesRulesIn,
    SalesRulesOut,
    ScoringConfigIn,
    ScoringConfigOut,
    SearchGroupProposal,
    SearchGroupSuggestions,
    ServiceIn,
    ServiceOut,
    ServiceUpdate,
    SignalTypeIn,
    SignalTypeOut,
    SignalTypePatch,
    SlotOut,
    TypeSourceAsk,
    TypeSourceSuggestion,
    WritingSampleIn,
    WritingSampleOut,
)
from app.api.auth import current_user
from app.models.identity import User
from app.services import access
from app.services import (
    availability,
    crypto,
    demo,
    probes,
    provider_catalogue,
    readiness,
)
from app.services import sources as source_service
from app.services.durability import durability_of
from app.services.versioning import activate_new_version, get_active

router = APIRouter(prefix="/config", tags=["config"])


async def _require_active(session: AsyncSession, model, label: str):
    row = await get_active(session, model)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no active {label} — create one first",
        )
    return row


# ==========================================================================
# org profile
# ==========================================================================
@router.get("/org-profile", response_model=OrgProfileOut)
async def get_org_profile(session: AsyncSession = Depends(get_session)):
    return await _require_active(session, OrgProfile, "org profile")


@router.put("/org-profile", response_model=OrgProfileOut, status_code=201)
async def put_org_profile(
    payload: OrgProfileIn, session: AsyncSession = Depends(get_session)
):
    row = await activate_new_version(session, OrgProfile, payload.model_dump())
    await session.commit()
    return row


@router.get("/org-profile/versions", response_model=list[OrgProfileOut])
async def org_profile_versions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(OrgProfile).order_by(OrgProfile.version.desc())
    )
    return list(result.scalars())


# ==========================================================================
# services and proof points
# ==========================================================================

# ---------------------------------------------------------------- ICPs ----
# An ICP is shared and versioned: services and account lists link to the
# *profile*, while the definition they read is whichever version is active.
# Activating a new version therefore cannot orphan a link. See `docs/11`.


async def _icp_out(session: AsyncSession, profile: IcpProfile) -> IcpProfileOut:
    active = (
        await session.execute(
            select(IcpProfileVersion).where(
                IcpProfileVersion.icp_profile_id == profile.id,
                IcpProfileVersion.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    codes = sorted(
        row[0]
        for row in (
            await session.execute(
                select(ServiceCatalog.code)
                .join(
                    service_icp_link,
                    service_icp_link.c.service_id == ServiceCatalog.id,
                )
                .where(service_icp_link.c.icp_profile_id == profile.id)
            )
        ).all()
    )
    lists = (
        await session.execute(
            select(func.count())
            .select_from(account_list_icp)
            .where(account_list_icp.c.icp_profile_id == profile.id)
        )
    ).scalar_one()
    return IcpProfileOut(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        definition=active.definition if active else None,
        version=active.version if active else None,
        service_codes=codes,
        list_count=int(lists or 0),
    )


async def _services_by_code(
    session: AsyncSession, codes: list[str]
) -> list[ServiceCatalog]:
    """Resolve codes to services, refusing any that do not exist.

    Refused rather than skipped: silently dropping an unknown code would link
    the ICP to fewer services than the caller asked for and report success.
    """
    wanted = [c.strip().upper() for c in codes if c and c.strip()]
    if not wanted:
        raise HTTPException(422, "at least one service is required")
    found = list(
        (
            await session.execute(
                select(ServiceCatalog).where(
                    func.upper(ServiceCatalog.code).in_(wanted)
                )
            )
        ).scalars()
    )
    missing = sorted(set(wanted) - {s.code.upper() for s in found})
    if missing:
        raise HTTPException(422, f"unknown service(s): {', '.join(missing)}")
    return found


@router.get("/icp-profiles", response_model=list[IcpProfileOut])
async def list_icp_profiles(session: AsyncSession = Depends(get_session)):
    profiles = list(
        (await session.execute(select(IcpProfile).order_by(IcpProfile.name))).scalars()
    )
    return [await _icp_out(session, p) for p in profiles]


@router.post("/icp-profiles", response_model=IcpProfileOut, status_code=201)
async def create_icp_profile(
    payload: IcpProfileIn, session: AsyncSession = Depends(get_session)
):
    """Create a profile, its first version, and its service links in one call.

    One call rather than three because the links are not optional. Created
    separately, a profile could exist linked to nothing between two requests —
    a state the model says cannot happen.
    """
    services = await _services_by_code(session, payload.service_codes)

    clash = (
        await session.execute(select(IcpProfile).where(IcpProfile.name == payload.name))
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(409, f"an ICP named {payload.name!r} already exists")

    profile = IcpProfile(name=payload.name, description=payload.description)
    session.add(profile)
    await session.flush()

    session.add(
        IcpProfileVersion(
            icp_profile_id=profile.id,
            definition=payload.definition,
            version=1,
            is_active=True,
        )
    )
    for service in services:
        await session.execute(
            service_icp_link.insert().values(
                service_id=service.id, icp_profile_id=profile.id
            )
        )
    await session.commit()
    return await _icp_out(session, profile)


@router.put("/icp-profiles/{profile_id}", response_model=IcpProfileOut)
async def put_icp_definition(
    profile_id: uuid.UUID,
    payload: IcpDefinitionIn,
    session: AsyncSession = Depends(get_session),
):
    """Activate a new version of this profile's definition.

    A new version rather than an edit: an enrichment run records the version it
    read, so editing in place would make "why were these contacts chosen?"
    unanswerable. Runs already finished keep pointing at the old version; the
    next run picks up this one.
    """
    profile = await session.get(IcpProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "no such ICP")

    stranded = await _stranded_by_exclusions(session, payload.definition)
    if stranded:
        raise HTTPException(
            422,
            "this would leave "
            + ", ".join(sorted(stranded))
            + " with no source it can be found in, so the signal could never fire. "
            "Drop the signal instead, or leave one of its places on.",
        )

    current = (
        await session.execute(
            select(func.max(IcpProfileVersion.version)).where(
                IcpProfileVersion.icp_profile_id == profile.id
            )
        )
    ).scalar_one()
    await session.execute(
        update(IcpProfileVersion)
        .where(
            IcpProfileVersion.icp_profile_id == profile.id,
            IcpProfileVersion.is_active.is_(True),
        )
        .values(is_active=False)
    )
    session.add(
        IcpProfileVersion(
            icp_profile_id=profile.id,
            definition=payload.definition,
            version=int(current or 0) + 1,
            is_active=True,
        )
    )
    await session.commit()
    return await _icp_out(session, profile)


@router.put("/icp-profiles/{profile_id}/services", response_model=IcpProfileOut)
async def set_icp_services(
    profile_id: uuid.UUID,
    payload: IcpServicesIn,
    session: AsyncSession = Depends(get_session),
):
    """Replace the set of services this ICP sells to. At least one required."""
    profile = await session.get(IcpProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "no such ICP")
    services = await _services_by_code(session, payload.service_codes)

    await session.execute(
        service_icp_link.delete().where(
            service_icp_link.c.icp_profile_id == profile.id
        )
    )
    for service in services:
        await session.execute(
            service_icp_link.insert().values(
                service_id=service.id, icp_profile_id=profile.id
            )
        )
    await session.commit()
    return await _icp_out(session, profile)


@router.delete("/icp-profiles/{profile_id}", status_code=204)
async def delete_icp_profile(
    profile_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Delete an ICP no account list has used.

    409 once a list points at it. The rule is the one signal types follow: a
    profile that has targeted an enrichment run has history worth keeping, and
    deleting it would leave that run unable to say who it was looking for. One
    nothing references has no history to protect.

    Leaving a service with no ICP is fine. A service is what you sell; who to
    sell it to is chosen on the ICP, and a service can wait for one.
    """
    profile = await session.get(IcpProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "no such ICP")

    used = (
        await session.execute(
            select(func.count())
            .select_from(account_list_icp)
            .where(account_list_icp.c.icp_profile_id == profile.id)
        )
    ).scalar_one()
    if used:
        raise HTTPException(
            409,
            f"{profile.name!r} is used by {used} account list(s) — it cannot be "
            "deleted without making their enrichment unexplainable",
        )

    await session.delete(profile)
    await session.commit()


@router.get("/services", response_model=list[ServiceOut])
async def list_services(
    include_inactive: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(ServiceCatalog).order_by(ServiceCatalog.code)
    if not include_inactive:
        stmt = stmt.where(ServiceCatalog.is_active.is_(True))
    return list((await session.execute(stmt)).scalars())


@router.post("/services", response_model=ServiceOut, status_code=201)
async def create_service(payload: ServiceIn, session: AsyncSession = Depends(get_session)):
    row = ServiceCatalog(**payload.model_dump())
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, f"service code {payload.code!r} already exists") from exc
    return row


async def _service_usage(session: AsyncSession, service_id: uuid.UUID) -> dict[str, int]:
    """Where a service is already committed to. Zero everywhere means deletable."""
    from app.models.strategy import PersonaServiceScore, StrategyThread

    async def count(model, clause) -> int:
        return await session.scalar(
            select(func.count()).select_from(model).where(clause)
        ) or 0

    proofs = await count(ProofPoint, ProofPoint.service_id == service_id)
    threads = await count(StrategyThread, StrategyThread.service_id == service_id)
    cells = await count(PersonaServiceScore, PersonaServiceScore.service_id == service_id)
    return {"proof_points": proofs, "threads": threads, "matrix_cells": cells}


async def _service_by_code(session: AsyncSession, code: str) -> ServiceCatalog:
    """One service, or 404."""
    row = (
        await session.execute(select(ServiceCatalog).where(ServiceCatalog.code == code))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"service {code!r} not found")
    return row


@router.patch("/services/{code}", response_model=ServiceOut)
async def set_service_active(
    code: str, active: bool = Query(...), session: AsyncSession = Depends(get_session)
):
    """Take a service out of strategy, or put it back.

    Reversible and non-destructive: an inactive service stops being weighed
    against personas but the strategies that already chose it still explain
    themselves.
    """
    row = (
        await session.execute(select(ServiceCatalog).where(ServiceCatalog.code == code))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"service {code!r} not found")
    row.is_active = active
    await session.commit()
    return row


@router.put("/services/{code}", response_model=ServiceOut)
async def update_service(
    code: str, payload: ServiceUpdate, session: AsyncSession = Depends(get_session)
):
    """Edit what a service says about itself — name, description, angles, and
    who signs off for it. Only the fields sent are changed.

    The code is fixed: strategy threads and matrix cells refer to it.
    """
    row = await _service_by_code(session, code)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in ("name", "description") and value is None:
            continue  # required columns; "not sent" and "null" mean the same here
        setattr(row, field, value)
    await session.commit()
    return row


@router.delete("/services/{code}", status_code=204)
async def delete_service(code: str, session: AsyncSession = Depends(get_session)):
    """Delete a service nothing has committed to yet.

    Once a strategy has weighed it — even into a cell that scored zero — the
    matrix is the record of a decision not to act, and deleting the service
    would leave that record pointing at nothing.
    """
    row = (
        await session.execute(select(ServiceCatalog).where(ServiceCatalog.code == code))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"service {code!r} not found")

    usage = await _service_usage(session, row.id)
    if any(usage.values()):
        used = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in usage.items() if n)
        raise HTTPException(
            409,
            f"{code!r} is referenced by {used} and cannot be deleted — "
            "deactivate it instead, so the work that used it stays explainable",
        )

    await session.delete(row)
    await session.commit()


@router.get("/proof-points", response_model=list[ProofPointOut])
async def list_proof_points(
    approved_only: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(ProofPoint).order_by(ProofPoint.title)
    if approved_only:
        stmt = stmt.where(ProofPoint.is_approved.is_(True))
    return list((await session.execute(stmt)).scalars())


@router.post("/proof-points", response_model=ProofPointOut, status_code=201)
async def create_proof_point(
    payload: ProofPointIn, session: AsyncSession = Depends(get_session)
):
    row = ProofPoint(**payload.model_dump())
    session.add(row)
    await session.commit()
    return row


@router.post("/proof-points/{pp_id}/approve", response_model=ProofPointOut)
async def approve_proof_point(
    pp_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Approval is its own act, on its own route.

    Kept separate from creation so a claim cannot arrive pre-approved in the
    request that created it — the sign-off is what gates a claim reaching a
    prospect.
    """
    row = await session.get(ProofPoint, pp_id)
    if row is None:
        raise HTTPException(404, "proof point not found")
    row.is_approved = True
    await session.commit()
    return row


# ==========================================================================
# writing samples
# ==========================================================================
@router.post("/proof-points/{pp_id}/withdraw", response_model=ProofPointOut)
async def withdraw_proof_point(pp_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Un-approve a claim.

    The counterpart to approve, and the one that matters when a claim turns out
    to be wrong: it stops the proof point reaching any future prompt
    immediately, without destroying the record that it was once approved.
    Drafts already written keep citing it — those are what a rep approved.
    """
    row = await session.get(ProofPoint, pp_id)
    if row is None:
        raise HTTPException(404, "proof point not found")
    row.is_approved = False
    await session.commit()
    return row


async def _proof_point_citations(session: AsyncSession, pp_id: uuid.UUID) -> int:
    """How many drafts already quote this claim."""
    from app.models.content import Draft

    return await session.scalar(
        select(func.count())
        .select_from(Draft)
        .where(Draft.cited_proof_point_ids.contains([str(pp_id)]))
    ) or 0


@router.delete("/proof-points/{pp_id}", status_code=204)
async def delete_proof_point(pp_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Delete a claim nothing has quoted yet.

    A cited proof point is refused: the draft that quotes it was reviewed and
    approved on the strength of that claim, and deleting it would leave an
    approved message resting on something that no longer exists. Withdraw it
    instead.
    """
    row = await session.get(ProofPoint, pp_id)
    if row is None:
        raise HTTPException(404, "proof point not found")

    cited = await _proof_point_citations(session, pp_id)
    if cited:
        raise HTTPException(
            409,
            f"{row.title!r} is cited by {cited} draft(s) and cannot be deleted — "
            "withdraw it instead, so those drafts still explain themselves",
        )

    await session.delete(row)
    await session.commit()


@router.get("/writing-samples", response_model=list[WritingSampleOut])
async def list_writing_samples(session: AsyncSession = Depends(get_session)):
    return list(
        (await session.execute(select(WritingSample).order_by(WritingSample.channel))).scalars()
    )


@router.post("/writing-samples", response_model=WritingSampleOut, status_code=201)
async def create_writing_sample(
    payload: WritingSampleIn, session: AsyncSession = Depends(get_session)
):
    row = WritingSample(**payload.model_dump())
    session.add(row)
    await session.commit()
    return row


@router.patch("/writing-samples/{sample_id}", response_model=WritingSampleOut)
async def set_writing_sample_active(
    sample_id: uuid.UUID,
    active: bool = Query(...),
    session: AsyncSession = Depends(get_session),
):
    """Take a sample out of the prompt, or put it back.

    Usually what you want rather than deleting: a sample that stopped working
    for one campaign is still evidence of how the voice used to read.
    """
    row = await session.get(WritingSample, sample_id)
    if row is None:
        raise HTTPException(404, "writing sample not found")
    row.is_active = active
    await session.commit()
    return row


@router.delete("/writing-samples/{sample_id}", status_code=204)
async def delete_writing_sample(
    sample_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Delete a sample outright.

    Unconditional, unlike services and proof points: a writing sample is copied
    into a prompt as text and nothing stores a reference to it, so removing one
    leaves no dangling citation behind. It only changes what future prompts
    sound like.
    """
    row = await session.get(WritingSample, sample_id)
    if row is None:
        raise HTTPException(404, "writing sample not found")
    await session.delete(row)
    await session.commit()


# ==========================================================================
# sales rules
# ==========================================================================
@router.get("/sales-rules", response_model=SalesRulesOut)
async def get_sales_rules(session: AsyncSession = Depends(get_session)):
    return await _require_active(session, SalesRules, "sales rules")


@router.put("/sales-rules", response_model=SalesRulesOut, status_code=201)
async def put_sales_rules(
    payload: SalesRulesIn, session: AsyncSession = Depends(get_session)
):
    row = await activate_new_version(session, SalesRules, payload.model_dump())
    await session.commit()
    return row


@router.get("/sales-rules/versions", response_model=list[SalesRulesOut])
async def sales_rules_versions(session: AsyncSession = Depends(get_session)):
    return list(
        (await session.execute(select(SalesRules).order_by(SalesRules.version.desc()))).scalars()
    )


# ==========================================================================
# scoring config
# ==========================================================================
@router.get("/scoring", response_model=ScoringConfigOut)
async def get_scoring(session: AsyncSession = Depends(get_session)):
    return await _require_active(session, ScoringConfig, "scoring config")


@router.put("/scoring", response_model=ScoringConfigOut, status_code=201)
async def put_scoring(
    payload: ScoringConfigIn, session: AsyncSession = Depends(get_session)
):
    row = await activate_new_version(session, ScoringConfig, payload.model_dump())
    await session.commit()
    return row


@router.get("/scoring/versions", response_model=list[ScoringConfigOut])
async def scoring_versions(session: AsyncSession = Depends(get_session)):
    return list(
        (
            await session.execute(select(ScoringConfig).order_by(ScoringConfig.version.desc()))
        ).scalars()
    )


# ==========================================================================
# research settings — the reuse window
# ==========================================================================
@router.get("/research-settings", response_model=ResearchConfigOut)
async def get_research_settings(session: AsyncSession = Depends(get_session)):
    """The active reuse window. Never 404s: no row means the default applies,
    which is a working state, not a missing one."""
    from app.models.config import ResearchConfig
    from app.services.research import DEFAULT_FRESHNESS_DAYS, DEFAULT_TIER

    row = await get_active(session, ResearchConfig)
    if row is not None:
        return row
    return ResearchConfigOut(
        id=None, version=0, is_active=True, freshness_days=DEFAULT_FRESHNESS_DAYS,
        default_tier=DEFAULT_TIER,
    )


@router.put("/research-settings", response_model=ResearchConfigOut, status_code=201)
async def put_research_settings(
    payload: ResearchConfigIn, session: AsyncSession = Depends(get_session)
):
    """A new version. A run records nothing about the window it used, but the
    history of what it was set to — and when — answers "why was this reused?"."""
    from app.models.config import ResearchConfig

    row = await activate_new_version(session, ResearchConfig, payload.model_dump())
    await session.commit()
    return row


# ==========================================================================
# installation mode
# ==========================================================================
@router.get("/mode", response_model=ModeOut)
async def get_mode(session: AsyncSession = Depends(get_session)):
    """The active mode. Never 404s.

    A missing row is a well-defined state, not an error: `demo.current_mode`
    reads it as `production`, which is the safe default. Returning a 404 would
    make a screen show an error for a system that is behaving correctly, and
    the reader would go looking for a fault that is not there.
    """
    row = await get_active(session, InstallationMode)
    if row is not None:
        return row
    return ModeOut(
        id=uuid.UUID(int=0),
        mode=demo.PRODUCTION,
        reason="no mode has been set; production is the default",
        switched_by=None,
        version=0,
        is_active=True,
    )


@router.put("/mode", response_model=ModeOut, status_code=201)
async def put_mode(payload: ModeIn, session: AsyncSession = Depends(get_session)):
    """Switch between a sandbox and a real book.

    Going **to** demo is free: it only ever makes the system less capable, and
    every outbound seam starts refusing.

    Going **to production** is the direction that needs care. Demo runs produce
    fixture evidence, and evidence is the bottom of every citation in the
    system — a book where some citations are fixtures cannot be trusted by the
    rep reading it, and nothing on screen distinguishes them. So if demo runs
    exist, the switch is refused until the caller acknowledges them explicitly.

    Deliberately *not* deleting anything. A destructive cleanup triggered by a
    settings toggle is how somebody loses a real account they had imported
    before the demo. The rows are tagged (`run.mode`); what to do with them is
    a decision, not a side effect.
    """
    current = await demo.current_mode(session)
    if payload.mode == current:
        row = await get_active(session, InstallationMode)
        if row is not None:
            return row

    if payload.mode == demo.PRODUCTION:
        produced = await demo.demo_run_count(session)
        if produced and not payload.acknowledge_demo_data:
            raise HTTPException(
                409,
                {
                    "error": "demo_data_present",
                    "message": (
                        f"{produced} run(s) were produced in demo mode. Their evidence "
                        "and signals are fixtures, and nothing on screen tells them "
                        "apart from real ones. Acknowledge to switch anyway, or start "
                        "production on a clean database."
                    ),
                    "demo_runs": produced,
                },
            )

    row = await activate_new_version(
        session,
        InstallationMode,
        {
            "mode": payload.mode,
            "reason": payload.reason,
            "switched_by": payload.switched_by,
        },
    )
    await session.commit()
    return row


# ==========================================================================
# setup readiness — the gate
# ==========================================================================
@router.get("/readiness", response_model=ReadinessOut)
async def get_readiness(session: AsyncSession = Depends(get_session)):
    """Whether the three mandatory external connections are in place.

    Derived on every call, never stored. A stored "setup complete" flag is a
    claim about the past: a key gets revoked or a workspace runs out of credit
    and the flag still says ready while every run fails. Computed, the gate
    re-closes by itself the moment something breaks.
    """
    state = await readiness.evaluate(session)
    return ReadinessOut(
        ready=state.ready,
        workable=state.workable,
        mode=state.mode,
        demo_runs=state.demo_runs,
        blockers=state.blockers,
        warnings=state.warnings,
        enrichment_order=state.enrichment_order,
        requirements=state.requirements,
        slots=[
            SlotOut(
                kind=s.kind,
                title=s.title,
                why=s.why,
                state=s.state,
                satisfied=s.satisfied,
                blocker=s.blocker,
                warning=s.warning,
                credentials=[
                    CredentialStateOut(
                        provider=c.provider,
                        label=c.label,
                        status=c.status,
                        last_four=c.last_four,
                        console_url=c.console_url,
                        runnable=c.runnable,
                        verifiable=c.verifiable,
                        last_test_code=c.last_test_code,
                        last_test_detail=c.last_test_detail,
                    )
                    for c in s.credentials
                ],
            )
            for s in state.slots
        ],
        unrecognised=[
            CredentialStateOut(
                provider=c.provider,
                label=c.label,
                status=c.status,
                last_four=c.last_four,
                console_url=c.console_url,
                runnable=c.runnable,
                verifiable=c.verifiable,
                last_test_code=c.last_test_code,
                last_test_detail=c.last_test_detail,
            )
            for c in state.unrecognised
        ],
    )


# ==========================================================================
# enrichment waterfall
# ==========================================================================
@router.get("/enrichment", response_model=EnrichmentConfigOut)
async def get_enrichment_config(session: AsyncSession = Depends(get_session)):
    row = await get_active(session, EnrichmentConfig)
    if row is None:
        raise HTTPException(404, "no active enrichment configuration")
    return row


@router.put("/enrichment", response_model=EnrichmentConfigOut, status_code=201)
async def put_enrichment_config(
    payload: EnrichmentConfigIn, session: AsyncSession = Depends(get_session)
):
    """Reorder the waterfall. Writes a new version; the previous one is kept.

    Two rejections, both about calls that would be paid for and wasted:
    a provider named twice is asked twice for the same answer, and a provider
    of the wrong kind is asked a question it cannot answer.
    """
    seen = [p for p in payload.provider_order]
    if len(set(seen)) != len(seen):
        raise HTTPException(
            400, "a provider appears twice in the waterfall; each call is metered"
        )

    enrichment_keys = {p.key for p in provider_catalogue.of_kind("enrichment")}
    for key in seen:
        cat = provider_catalogue.BY_KEY.get(key)
        if cat is None:
            # A provider somebody added. We cannot know it does enrichment, and
            # refusing would make an added provider unusable — so it is allowed
            # and the waterfall simply skips it if nothing implements it.
            continue
        if key not in enrichment_keys:
            raise HTTPException(
                400,
                f"{cat.label} is a {cat.kind} provider and cannot enrich contacts",
            )

    row = await activate_new_version(session, EnrichmentConfig, payload.model_dump())
    await session.commit()
    return row


# ==========================================================================
# model availability — the shortlist a stage may choose from
# ==========================================================================
@router.get("/model-availability", response_model=AvailabilityOut)
async def get_model_availability(session: AsyncSession = Depends(get_session)):
    """Which models this installation may use, and what is currently relying
    on them.

    `in_use` travels with the shortlist so the screen can grey out a removal
    before it is attempted, rather than offering it and refusing on save.
    """
    state = await availability.resolve(session)
    used = await availability.models_in_use(session)
    return AvailabilityOut(
        providers=[
            ProviderAvailabilityOut(
                provider=p.provider,
                label=p.label,
                runnable=p.runnable,
                enabled=p.enabled,
                catalogue=p.catalogue,
                custom=p.custom,
                defaulted=p.defaulted,
            )
            for p in state.providers
        ],
        in_use=[
            ModelInUseOut(provider=u.provider, model=u.model, scenarios=list(u.scenarios))
            for u in used
        ],
    )


@router.put("/model-availability", response_model=AvailabilityOut, status_code=201)
async def put_model_availability(
    payload: AvailabilityIn, session: AsyncSession = Depends(get_session)
):
    """Set the shortlist. Refused if it would strand a configured stage.

    Removing a model a stage still points at does not fail here — it fails at
    that stage's next real call, after research has been paid for, with an
    error naming a model rather than the setting that removed it. Same
    delete-if-unused rule this codebase applies everywhere else.
    """
    cleaned: dict[str, list[str]] = {}
    for provider, models in payload.enabled.items():
        seen: list[str] = []
        for model in models:
            if model and model not in seen:
                seen.append(model)
        if not seen:
            # An empty list is not "no choice" — it is "nothing may run here",
            # which is a stage with an empty dropdown. Rejected rather than
            # stored, because the two are indistinguishable once written.
            raise HTTPException(
                400,
                f"{provider} was given an empty model list. Remove the provider "
                "to fall back to its full catalogue, or choose at least one model.",
            )
        cleaned[provider] = seen

    try:
        await availability.assert_no_stage_is_stranded(session, cleaned)
    except availability.ModelInUseError as exc:
        raise HTTPException(
            409,
            {
                "error": "model_in_use",
                "message": str(exc),
                "stranded": [
                    {"provider": u.provider, "model": u.model, "scenarios": list(u.scenarios)}
                    for u in exc.stranded
                ],
            },
        ) from exc

    await activate_new_version(session, ModelAvailability, {"enabled": cleaned})
    await session.commit()
    return await get_model_availability(session)


# ==========================================================================
# providers and models
# ==========================================================================
@router.get("/providers", response_model=list[ProviderOut])
async def list_providers():
    """The vendors we ship suggestions for — *not* the vendors you may use.

    An endpoint rather than a constant in the bundle so that adding an adapter
    changes what the UI offers without a frontend release. `runnable` is the
    field that matters: it says whether choosing this provider produces a
    configuration that can actually make a call, or a stated intention to
    switch once an adapter exists.
    """
    return [
        ProviderOut(
            key=p.key,
            label=p.label,
            kind=p.kind,
            purpose=p.purpose,
            console_url=p.console_url,
            runnable=p.runnable,
            verifiable=p.verifiable,
            credential_types=list(p.credential_types),
            models=[
                ModelOptionOut(
                    id=m.id,
                    label=m.label,
                    structured_output=m.structured_output,
                    effort=m.effort,
                    prompt_caching=m.prompt_caching,
                    tier=m.tier,
                    notes=m.notes,
                )
                for m in p.models
            ],
        )
        for p in provider_catalogue.CATALOGUE
    ]


# ==========================================================================
# llm config
# ==========================================================================
class SpendRowOut(BaseModel):
    scenario: str
    model: str
    calls: int
    failed: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    #: Output is where a runaway budget shows up, and on most vendors it is
    #: the dearer half — so it is what the screen sorts on.
    avg_output: int
    worst_output: int
    avg_ms: int


class SpendOut(BaseModel):
    days: int
    since: str
    calls: int
    failed: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    by_stage: list[SpendRowOut]
    note: str


@router.get("/llm/spend", response_model=SpendOut)
async def llm_spend(days: int = 30, session: AsyncSession = Depends(get_session)):
    """What the model calls cost, in tokens, by stage.

    Tokens rather than currency, deliberately: a price is a fact about a
    contract with a vendor, it changes without notice, and a rate invented
    here would read as authoritative and be wrong. Multiply by your own.

    `worst_output` is the column that earns its place. A stage configured into
    runaway thinking has an ordinary average and a ruinous maximum, which is
    how `strategy_synthesis` spent a whole 30k budget on one call while its
    neighbours used four hundred tokens.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.config import LlmCall

    window = max(1, min(days, 365))
    since = datetime.now(UTC) - timedelta(days=window)

    rows = (
        await session.execute(
            select(
                LlmCall.scenario,
                LlmCall.model,
                func.count().label("calls"),
                func.count().filter(LlmCall.ok.is_(False)).label("failed"),
                func.coalesce(func.sum(LlmCall.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(LlmCall.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(LlmCall.cache_read_tokens), 0).label("cache_read_tokens"),
                func.coalesce(func.avg(LlmCall.output_tokens), 0).label("avg_output"),
                func.coalesce(func.max(LlmCall.output_tokens), 0).label("worst_output"),
                func.coalesce(func.avg(LlmCall.duration_ms), 0).label("avg_ms"),
            )
            .where(LlmCall.created_at >= since)
            .group_by(LlmCall.scenario, LlmCall.model)
            .order_by(func.sum(LlmCall.output_tokens).desc())
        )
    ).all()

    by_stage = [
        SpendRowOut(
            scenario=r.scenario, model=r.model, calls=r.calls, failed=r.failed,
            input_tokens=r.input_tokens, output_tokens=r.output_tokens,
            cache_read_tokens=r.cache_read_tokens, avg_output=int(r.avg_output),
            worst_output=int(r.worst_output), avg_ms=int(r.avg_ms),
        )
        for r in rows
    ]
    return SpendOut(
        days=window,
        since=since.isoformat(),
        calls=sum(r.calls for r in by_stage),
        failed=sum(r.failed for r in by_stage),
        input_tokens=sum(r.input_tokens for r in by_stage),
        output_tokens=sum(r.output_tokens for r in by_stage),
        cache_read_tokens=sum(r.cache_read_tokens for r in by_stage),
        by_stage=by_stage,
        note=(
            "Tokens, not currency — apply your own vendor rates. Cached input is usually "
            "charged at a fraction of fresh input."
        ),
    )


@router.get("/llm", response_model=list[LlmConfigOut])
async def list_llm_configs(session: AsyncSession = Depends(get_session)):
    rows = list(
        (
            await session.execute(
                select(LlmConfig).where(LlmConfig.is_active.is_(True)).order_by(LlmConfig.scenario)
            )
        ).scalars()
    )
    return [_with_runnable(r) for r in rows]


def _with_runnable(row: LlmConfig) -> LlmConfigOut:
    """Derived, never stored — whether an adapter exists is a fact about code."""
    out = LlmConfigOut.model_validate(row)
    out.runnable = provider_catalogue.is_runnable(row.provider)
    return out


@router.put("/llm/{scenario}", response_model=LlmConfigOut, status_code=201)
async def put_llm_config(
    scenario: str, payload: LlmConfigIn, session: AsyncSession = Depends(get_session)
):
    if payload.scenario != scenario:
        raise HTTPException(400, "scenario in the path and body must match")
    try:
        # A typo'd model id for a provider we know is rejected here. An unknown
        # provider is not — that is a provider somebody added, and we have no
        # list to check it against.
        provider_catalogue.validate(payload.provider, payload.model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    # And it must be one this installation actually allows. The catalogue says
    # the vendor sells it; the shortlist says we are willing to run it, and a
    # stage pointed at something outside the shortlist is a dropdown that
    # disagrees with what saving accepts.
    state = await availability.resolve(session)
    if not state.allows(payload.provider, payload.model):
        entry = state.for_provider(payload.provider)
        raise HTTPException(
            400,
            f"{payload.model!r} is not on this installation's list for "
            f"{payload.provider}. Available: {entry.enabled if entry else []}. "
            "Change the list under Available models.",
        )

    row = await activate_new_version(
        session, LlmConfig, payload.model_dump(), scope_field="scenario"
    )
    await session.commit()
    return _with_runnable(row)


# ==========================================================================
# credentials
# ==========================================================================
@router.get("/credentials", response_model=list[CredentialOut])
async def list_credentials(session: AsyncSession = Depends(get_session)):
    """Returns metadata only. The response model cannot carry a value."""
    return list(
        (
            await session.execute(
                select(IntegrationCredential).order_by(IntegrationCredential.provider)
            )
        ).scalars()
    )


@router.put("/credentials", response_model=CredentialOut, status_code=201)
async def put_credential(
    payload: CredentialIn,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    """Upsert. Re-sending a provider/type replaces the stored value.

    ``last_four`` is derived here rather than accepted from the client, so it
    always describes what is actually stored.
    """
    existing = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.provider == payload.provider,
                IntegrationCredential.credential_type == payload.credential_type,
            )
        )
    ).scalar_one_or_none()

    encrypted = crypto.encrypt(payload.value)
    tail = crypto.last_four(payload.value)
    # Supplied by the caller for a provider they added; filled from the
    # catalogue for one we ship. Never guessed for an unknown provider — a
    # wrong console link is worse than none.
    known = provider_catalogue.BY_KEY.get(payload.provider)
    console_url = payload.console_url or (known.console_url if known else None)

    if existing is None:
        existing = IntegrationCredential(
            provider=payload.provider,
            credential_type=payload.credential_type,
            value_encrypted=encrypted,
            last_four=tail,
            status="untested",
            spend_cap=payload.spend_cap,
            console_url=console_url,
        )
        session.add(existing)
    else:
        existing.value_encrypted = encrypted
        existing.last_four = tail
        # A replaced credential is unproven again until tested.
        existing.status = "untested"
        existing.last_tested_at = None
        if payload.spend_cap is not None:
            existing.spend_cap = payload.spend_cap
        if console_url:
            existing.console_url = console_url

    # Which slot changed and who changed it — never the value, nor its last
    # four. Invariant 9.
    await access.record(
        session, user, "credential.saved", "integration_credential",
        f"{payload.provider}/{payload.credential_type}",
    )
    await session.commit()
    return existing


@router.delete("/credentials/{cred_id}", status_code=204)
async def delete_credential(
    cred_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    """Remove a stored credential.

    Never refused. A credential is a secret, not a record: it explains nothing
    about what already happened, and the rows that do — evidence, signals,
    execution records — do not point at it. Refusing to delete one would leave
    a mistyped provider on the Integrations screen forever, which matters more
    now that providers can be added freely.

    Deleting the last credential for a mandatory slot **re-closes the setup
    gate**, and that is correct rather than unfortunate: readiness is derived
    on every call precisely so it can go backwards when the world does.
    """
    row = await session.get(IntegrationCredential, cred_id)
    if row is None:
        raise HTTPException(404, "credential not found")
    await access.record(
        session, user, "credential.deleted", "integration_credential",
        f"{row.provider}/{row.credential_type}",
    )
    await session.delete(row)
    await session.commit()


async def _record_test(
    session: AsyncSession,
    row: IntegrationCredential,
    *,
    status: str,
    code: str,
    detail: str,
) -> CredentialOut:
    """Persist the outcome and hand it back.

    The reason is stored rather than only returned, so the badge is still
    explainable after a reload. Every string reaching these columns is written
    by us — see the migration; a provider's response body can quote the key it
    was sent.
    """
    row.status = status
    row.last_test_code = code
    row.last_test_detail = detail
    row.last_tested_at = datetime.now(UTC)
    await session.commit()
    return CredentialOut.model_validate(row)


@router.post("/credentials/{cred_id}/test", response_model=CredentialOut)
async def test_credential(cred_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Decrypt the stored value, then — where we can — actually use it.

    Two failures wear the same clothes and must not. A value that will not
    decrypt means `SECRET_KEY` changed since it was stored and the credential
    must be re-entered. A value that decrypts but the provider rejects means
    the key itself is wrong, and re-entering the same one will not help.

    Only Anthropic is probed for real today; the other adapters land with their
    providers. For those, a decrypt is honestly reported as a decrypt.
    """
    row = await session.get(IntegrationCredential, cred_id)
    if row is None:
        raise HTTPException(404, "credential not found")

    try:
        value = crypto.decrypt(row.value_encrypted)
    except crypto.CredentialError:
        return await _record_test(
            session,
            row,
            status="invalid",
            code="undecryptable",
            detail="stored value will not decrypt — re-enter it",
        )

    if row.credential_type != "api_key":
        # Nothing to call with a base URL or a webhook secret. Reported as what
        # it is rather than promoted to `valid`, which would let it satisfy the
        # setup gate on a decrypt.
        return await _record_test(
            session,
            row,
            status="untested",
            code="not_checkable",
            detail=f"stored — a {row.credential_type} cannot be round-tripped",
        )

    # A probe is an outbound request like any other. In demo mode it is
    # refused rather than stubbed to success: a green tick that never left the
    # machine teaches a client something false about their own key.
    if await demo.is_demo(session):
        return await _record_test(
            session,
            row,
            status="untested",
            code="demo",
            detail=(
                "demo mode — the key is stored but no provider was contacted. "
                "Switch to production to check it."
            ),
        )

    # `.reveal()` and nowhere else. `SecretValue` refuses to be formatted or
    # logged, so the unwrap is explicit and goes straight into the probe.
    result = await probes.probe(row.provider, value.reveal())
    return await _record_test(
        session, row, status=result.status, code=result.code, detail=result.detail
    )


# ==========================================================================
# signal types
# ==========================================================================
@router.get("/query-families", response_model=list[QueryFamilyOut])
async def list_query_families(session: AsyncSession = Depends(get_session)):
    """The sources a signal type may claim, for populating the picker.

    Kept under its old path so nothing breaks mid-deploy, and reading the
    registry table rather than the code constant. `/research-sources` is the
    same list with what each source has produced attached.
    """
    return [
        QueryFamilyOut(
            key=s.key, label=s.label, description=s.description,
            scopes=list(s.scopes or []), support_only=s.support_only, runner=s.kind,
        )
        for s in await source_service.all_sources(session)
    ]


@router.get("/research-sources", response_model=list[ResearchSourceOut])
async def list_research_sources(
    include_retired: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    """The registry, with what each source has actually produced attached.

    The numbers are the point. A registry only ever grows: without "tried 40
    times, produced nothing" on the same screen, a source added in March is
    still costing a read per account in December and nobody knows.
    """
    rows = await source_service.all_sources(session, include_retired=include_retired)
    health = await source_service.health(session)
    claims: dict[str, int] = {}
    for st in (
        await session.execute(select(SignalType).where(SignalType.status == "active"))
    ).scalars():
        for key in st.produced_by or []:
            claims[key] = claims.get(key, 0) + 1

    out = []
    for row in rows:
        stat = health.get(row.key)
        out.append(
            ResearchSourceOut(
                **{c.name: getattr(row, c.name) for c in row.__table__.columns},
                claimed_by=claims.get(row.key, 0),
                attempts=stat.attempts if stat else 0,
                evidence=stat.evidence if stat else 0,
                dead_weight=bool(stat and stat.is_dead_weight),
            )
        )
    return out


@router.post("/research-sources", response_model=ResearchSourceOut, status_code=201)
async def create_research_source(
    payload: ResearchSourceIn, session: AsyncSession = Depends(get_session)
):
    """Add a place to read. Always a search — see `sources.CREATABLE_KINDS`."""
    row = ResearchSource(**payload.model_dump(), kind="search", builtin=False)
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, f"a source keyed {payload.key!r} already exists") from exc
    return ResearchSourceOut(
        **{c.name: getattr(row, c.name) for c in row.__table__.columns}
    )


@router.post("/research-sources/try", response_model=SourceTrialOut)
async def try_research_source(
    payload: SourceTrialIn, session: AsyncSession = Depends(get_session)
):
    """Run a candidate source against a few real accounts. Stores nothing.

    Declared **before** `/{key}` so "try" is not read as a source key.

    A source costs a read per account from the moment it is saved, and whether
    it earns that is only visible afterwards — `job_board` spent 26 attempts
    establishing that it finds nothing here. This runs the real prompt against
    the real model and shows what came back, so the wording can be fixed while
    it is still free.

    Nothing is written: no evidence, no coverage, no signals. The one thing it
    does cost is the model calls themselves, which is why the sample is capped.
    """
    from app.services import source_trial

    candidate = payload.model_dump(exclude={"account_ids", "description_b"})
    try:
        report = await source_trial.try_source(
            session,
            candidate=candidate,
            account_ids=payload.account_ids,
            description_b=payload.description_b,
        )
    except source_trial.NotTestable as exc:
        raise HTTPException(422, str(exc)) from exc

    if not report.trials:
        raise HTTPException(404, "none of those account ids exist")

    return SourceTrialOut(
        candidate=report.candidate,
        route=report.route,
        prompt=report.prompt,
        payload=report.payload,
        variant_b=report.variant_b,
        accounts=report.accounts,
        found=report.found,
        dry=report.dry,
        failed=report.failed,
        input_tokens=report.input_tokens,
        output_tokens=report.output_tokens,
        verdict=report.verdict,
        trials=[
            AccountTrialOut(
                account_id=t.account_id,
                account_name=t.account_name,
                found=[e.model_dump(mode="json") for e in t.found],
                not_found=t.not_found,
                duration_ms=t.duration_ms,
                input_tokens=t.input_tokens,
                output_tokens=t.output_tokens,
                error=t.error,
                variant=t.variant,
                missing=t.missing,
            )
            for t in report.trials
        ],
    )


@router.patch("/research-sources/{key}", response_model=ResearchSourceOut)
async def update_research_source(
    key: str, payload: ResearchSourcePatch, session: AsyncSession = Depends(get_session)
):
    """Edit a source in place.

    `key` and `kind` are never editable, on a builtin row or any other. Both are
    written into coverage rows that already exist: renaming one would orphan
    every record of what was read, which is the one thing coverage is for.

    Retiring is a status change rather than a delete, for the same reason.
    """
    row = (
        await session.execute(select(ResearchSource).where(ResearchSource.key == key))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"source {key!r} not found")

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(400, "no fields to update")
    for field, value in changes.items():
        setattr(row, field, value)
    if changes.get("status") == "active":
        # `status_reason` answers "why is this not active?", so it has to go
        # when the answer stops existing. Found by the source audit: resuming
        # `linkedin_serp` left it active while still saying "No SERP API
        # credential is configured", which reads as a live warning about a
        # source that is running.
        row.status_reason = None
    await session.commit()
    # Refreshed before the columns are read, not after. `updated_at` is mapped
    # `onupdate=func.now()` — a SQL expression, so once a real UPDATE flushes,
    # SQLAlchemy expires that attribute and the next read of it is IO. The
    # comprehension below is synchronous, so that read raised MissingGreenlet
    # and the endpoint 500ed on every genuine change while still committing it:
    # that is why resuming `linkedin_serp` left the database correct and the
    # caller holding an error. A no-op patch flushed nothing and looked fine,
    # which is how it survived this long.
    await session.refresh(row)
    return ResearchSourceOut(
        **{c.name: getattr(row, c.name) for c in row.__table__.columns}
    )


@router.post("/signal-types/suggest-sources", response_model=TypeSourceSuggestion)
async def suggest_sources_for_type(
    payload: TypeSourceAsk, session: AsyncSession = Depends(get_session)
):
    """Ask where one signal type would be found.

    A proposal for a form a rep is already filling in — it fills boxes, it does
    not save anything. Keys the model invents are dropped rather than returned,
    because a claimed source nothing runs reports as a permanent coverage gap.
    Somewhere it might genuinely be worth reading comes back under
    `new_sources`, which a person has to add on purpose.
    """
    from app.services import llm, stages

    registry = await source_service.all_sources(session)
    known = {s.key for s in registry if payload.scope in (s.scopes or [])}

    try:
        await llm.assert_may_call(session, "signal_extraction")
    except Exception as exc:  # noqa: BLE001 — reported, not raised at the rep
        raise HTTPException(409, str(exc)) from exc

    result = await stages.suggest_type_sources(
        session,
        signal_type={
            "key": payload.key,
            "label": payload.label,
            "scope": payload.scope,
            "description": payload.description,
        },
        registry=[
            {
                "key": s.key, "label": s.label, "description": s.description,
                "scopes": list(s.scopes or []), "support_only": s.support_only,
            }
            for s in registry
            if payload.scope in (s.scopes or [])
        ],
    )
    proposal = result.parsed
    proposal.sources = [k for k in proposal.sources if k in known]
    proposal.new_sources = [n for n in proposal.new_sources if n.key not in known]
    return proposal


@router.post(
    "/icp-profiles/{profile_id}/suggest-sources", response_model=IcpSourceSuggestions
)
async def suggest_sources_for_icp(
    profile_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Assemble the sources this ICP should read.

    Proposed, never applied. Accepting it writes a new ICP *version* through the
    ordinary definition route, which is what keeps a run from August explainable
    after somebody edits sources in October.
    """
    from app.services import llm, stages

    profile = await session.get(IcpProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "no such ICP")
    version = (
        await session.execute(
            select(IcpProfileVersion).where(
                IcpProfileVersion.icp_profile_id == profile_id,
                IcpProfileVersion.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    definition = (version.definition if version else None) or {}

    wanted = [k for k in (definition.get("signals_that_matter") or []) if isinstance(k, str)]
    types = list(
        (
            await session.execute(
                select(SignalType).where(
                    SignalType.status == "active",
                    *( [SignalType.key.in_(wanted)] if wanted else [] ),
                )
            )
        ).scalars()
    )
    registry = await source_service.all_sources(session)
    known = {s.key for s in registry}

    try:
        await llm.assert_may_call(session, "signal_extraction")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(409, str(exc)) from exc

    result = await stages.suggest_icp_sources(
        session,
        icp={
            "name": profile.name,
            "description": profile.description,
            "industries": definition.get("industries") or [],
            "regions": definition.get("regions") or [],
            "business_model": definition.get("business_model") or [],
            "notes": definition.get("notes"),
        },
        types=[
            {
                "key": t.key, "label": t.label, "scope": t.scope,
                "description": t.description, "expects_sources": list(t.produced_by or []),
            }
            for t in types
        ],
        registry=[
            {
                "key": s.key, "label": s.label, "description": s.description,
                "scopes": list(s.scopes or []), "support_only": s.support_only,
                "kind": s.kind,
            }
            for s in registry
        ],
    )
    proposal = result.parsed
    type_keys = {t.key for t in types}
    proposal.sources = [
        IcpSourceProposal(
            key=p.key,
            for_types=[k for k in p.for_types if k in type_keys],
            why=p.why,
        )
        for p in proposal.sources
        if p.key in known
    ]
    proposal.new_sources = [n for n in proposal.new_sources if n.key not in known]
    return proposal


@router.get("/signal-types", response_model=list[SignalTypeOut])
async def list_signal_types(
    scope: str | None = Query(None, pattern="^(company|contact)$"),
    include_deprecated: bool = Query(False),
    include_paused: bool = Query(True),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(SignalType).order_by(SignalType.scope, SignalType.key)
    if scope:
        stmt = stmt.where(SignalType.scope == scope)
    excluded = []
    if not include_deprecated:
        excluded.append("deprecated")
    if not include_paused:
        excluded.append("paused")
    if excluded:
        stmt = stmt.where(SignalType.status.notin_(excluded))
    rows = list((await session.execute(stmt)).scalars())
    return _annotate(
        rows, await _signal_counts(session), await _wanted_types(session)
    )


@router.post("/signal-types/suggest-groups", response_model=SearchGroupSuggestions)
async def suggest_signal_type_groups(session: AsyncSession = Depends(get_session)):
    """Ask which type-owned searches read the same sources.

    A suggestion, never an application: grouping changes what every later
    search asks for, and that is a decision with a person's name on it. Keys
    the model invents are dropped rather than returned — the same guard every
    other stage gets, for the same reason.
    """
    from app.services import llm, stages

    rows = list(
        (
            await session.execute(
                select(SignalType).where(SignalType.status == "active")
            )
        ).scalars()
    )
    candidates = [
        {
            "key": r.key,
            "label": r.label,
            "scope": r.scope,
            "looks_for": r.search_instruction,
            "grouped_as": r.search_group,
        }
        for r in rows
        if not r.produced_by and (r.search_instruction or "").strip()
    ]
    if len(candidates) < 2:
        # Nothing to group. Said plainly rather than spending a call to be told.
        return SearchGroupSuggestions(ungrouped=[c["key"] for c in candidates])

    try:
        await llm.assert_may_call(session, "signal_extraction")
    except Exception as exc:  # noqa: BLE001 — reported, not raised at the rep
        raise HTTPException(409, str(exc)) from exc

    result = await stages.suggest_search_groups(session, candidates=candidates)
    known = {c["key"] for c in candidates}
    groups = []
    for proposal in result.parsed.groups:
        members = [k for k in proposal.type_keys if k in known]
        if len(members) >= 2:
            groups.append(
                SearchGroupProposal(
                    label=proposal.label, type_keys=members, why=proposal.why
                )
            )
    grouped = {k for g in groups for k in g.type_keys}
    return SearchGroupSuggestions(
        groups=groups, ungrouped=sorted(known - grouped)
    )


@router.post("/signal-types", response_model=SignalTypeOut, status_code=201)
async def create_signal_type(
    payload: SignalTypeIn, session: AsyncSession = Depends(get_session)
):
    problems = await source_service.validate(session, payload.produced_by, payload.scope)
    if problems:
        raise HTTPException(422, "; ".join(problems))
    row = SignalType(**payload.model_dump())
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, f"signal type {payload.key!r} already exists") from exc
    _annotate([row], {})
    return row


async def _signal_counts(session: AsyncSession) -> dict[str, int]:
    """How many signals cite each type.

    The `signal` table arrives in Phase 3. Until then every count is zero, and
    the check below is vacuous rather than wrong — `to_regclass` returns NULL
    for a table that does not exist yet, so this degrades instead of erroring.
    """
    if await session.scalar(text("SELECT to_regclass('public.signal')")) is None:
        return {}
    rows = await session.execute(
        text("SELECT signal_type, count(*) FROM signal GROUP BY signal_type")
    )
    return {key: n for key, n in rows}


def _annotate(
    rows: list[SignalType],
    counts: dict[str, int],
    wanted: set[str] | None = None,
) -> list[SignalType]:
    for row in rows:
        row.signal_count = counts.get(row.key, 0)
        # Resolved here so the screen reads one number whether or not the type
        # overrides the default, and never has to carry the multiple itself.
        row.durability_effective_days = durability_of(row)
        # `wanted is None` means nobody asked — leave the optimistic default
        # rather than claiming every type is unreachable.
        if wanted is not None:
            row.extractable = row.key in wanted
    return rows


@router.get("/icp-profiles/{profile_id}/source-performance")
async def icp_source_performance(
    profile_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """What each source has actually returned for the accounts on this ICP.

    The ICP decides which signals matter; the signals decide which places get
    read. What neither says is whether a place is *earning* it here — and that
    answer differs by ICP, which is the whole reason it is worth asking. A
    technology directory is worth paying for at a software company and
    worthless at a twenty-person broker, and only the numbers for *this* book
    can say so.

    Read, never written. It replaces a tick that switched a source off: a knob
    is a blunt answer to a question nobody had the evidence for, and the
    evidence is the better answer. Tuning still happens — by dropping a signal,
    or through `sources_excluded`, which the API still honours.

    Coverage rather than evidence, for the reason `sources.health` gives: the
    interesting case is the source that was read and gave nothing, which no
    evidence row can express.
    """
    version = (
        await session.execute(
            select(IcpProfileVersion).where(
                IcpProfileVersion.icp_profile_id == profile_id,
                IcpProfileVersion.is_active.is_(True),
            )
        )
    ).scalars().first()
    definition = (version.definition if version else None) or {}
    wanted = {
        k for k in (definition.get("signals_that_matter") or []) if isinstance(k, str)
    }
    excluded = {
        k for k in (definition.get("sources_excluded") or []) if isinstance(k, str)
    }

    types = list(
        (
            await session.execute(select(SignalType).where(SignalType.status == "active"))
        ).scalars()
    )
    in_play = [t for t in types if not wanted or t.key in wanted]
    expects: dict[str, list[str]] = {}
    for row in in_play:
        for key in row.produced_by or []:
            expects.setdefault(key, []).append(row.key)

    # Accounts reached through this ICP's lists. An account on no list the ICP
    # is worked for has nothing to say about it.
    measured = (
        await session.execute(
            text(
                "SELECT c.family, "
                "       COUNT(DISTINCT c.account_id) AS accounts, "
                "       COALESCE(SUM(c.evidence_count), 0) AS evidence, "
                "       COUNT(*) FILTER (WHERE c.status = 'ran') AS ran, "
                "       COUNT(*) FILTER (WHERE c.status = 'empty') AS empty, "
                "       COUNT(*) FILTER (WHERE c.status = 'failed') AS failed, "
                "       MAX(c.created_at) AS last_read "
                "  FROM research_coverage c "
                "  JOIN account_list_member m ON m.account_id = c.account_id "
                "  JOIN account_list_icp l ON l.list_id = m.list_id "
                " WHERE l.icp_profile_id = :icp "
                " GROUP BY c.family"
            ).bindparams(icp=profile_id)
        )
    ).mappings().all()
    by_family = {row["family"]: row for row in measured}

    registry = {s.key: s for s in await source_service.all_sources(session)}
    out = []
    for key in sorted(expects):
        source = registry.get(key)
        seen = by_family.get(key)
        out.append(
            {
                "key": key,
                "label": source.label if source else key,
                "status": source.status if source else "unknown",
                "excluded": key in excluded,
                "expected_by": sorted(expects[key]),
                "accounts": int(seen["accounts"]) if seen else 0,
                "evidence": int(seen["evidence"]) if seen else 0,
                "ran": int(seen["ran"]) if seen else 0,
                "empty": int(seen["empty"]) if seen else 0,
                "failed": int(seen["failed"]) if seen else 0,
                "last_read": seen["last_read"] if seen else None,
            }
        )
    return out


async def _stranded_by_exclusions(session: AsyncSession, definition: dict) -> set[str]:
    """Signal types this definition would leave with nowhere to be found.

    Excluding a source is the one way to say "this place is wrong for *this*
    book" — `tech_debt_modernization` reading BuiltWith is worth paying for at
    a software company and worthless at a twenty-person broker, and the signal
    list cannot express that.

    What it must not do is switch off the last place a chosen signal has. That
    is §80 again, reintroduced per ICP and invisible: a type configured,
    selected, and unable to produce anything. Refused rather than warned,
    because the state has no use — if the signal is not wanted here, the signal
    is what to drop, and then its sources are not derived at all.

    Only *live* sources count. A type whose remaining source is paused is
    stranded just as surely as one with none left.
    """
    excluded = {
        key
        for key in (definition.get("sources_excluded") or [])
        if isinstance(key, str)
    }
    if not excluded:
        return set()

    live = {
        row.key
        for row in (
            await session.execute(
                select(ResearchSource).where(ResearchSource.status == "active")
            )
        ).scalars()
    }
    wanted = {
        key
        for key in (definition.get("signals_that_matter") or [])
        if isinstance(key, str)
    }
    types = (
        await session.execute(select(SignalType).where(SignalType.status == "active"))
    ).scalars()

    stranded = set()
    for row in types:
        # An empty `signals_that_matter` means every active type, which is what
        # the planner does with it — so the check has to agree or it would pass
        # a definition the planner then breaks.
        if wanted and row.key not in wanted:
            continue
        claimed = set(row.produced_by or ())
        if claimed and not (claimed & live) - excluded:
            stranded.add(row.key)
    return stranded


async def _wanted_types(session: AsyncSession) -> set[str] | None:
    """Every type the active ICPs name, or None when they name none.

    None is not the empty set. An ICP that has accepted no signal list does not
    narrow extraction at all, so every type is reachable — reporting them all as
    unreachable would be the opposite of the truth.
    """
    rows = (
        await session.execute(
            select(IcpProfileVersion.definition).where(
                IcpProfileVersion.is_active.is_(True)
            )
        )
    ).scalars()
    named = {
        key
        for definition in rows
        for key in ((definition or {}).get("signals_that_matter") or [])
        if isinstance(key, str)
    }
    return named or None


async def _get_signal_type(session: AsyncSession, key: str) -> SignalType:
    row = (
        await session.execute(select(SignalType).where(SignalType.key == key))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"signal type {key!r} not found")
    # Every single-row route returns SignalTypeOut, and the client decides
    # whether to offer Delete from this number. Leaving it at the schema
    # default would offer deletion of a type that has real history.
    _annotate([row], await _signal_counts(session))
    return row


@router.patch("/signal-types/{key}", response_model=SignalTypeOut)
async def update_signal_type(
    key: str, payload: SignalTypePatch, session: AsyncSession = Depends(get_session)
):
    """Tune a type in place.

    Deliberately not versioned. A signal type's weight is a knob, and the
    qualification that used it already stored its own computed scores — so the
    audit trail survives without a version chain here. A deprecated type is
    refused: tuning something retired has no effect and reads as if it might.
    """
    row = await _get_signal_type(session, key)
    if row.status == "deprecated":
        raise HTTPException(409, f"{key!r} is deprecated and cannot be edited")

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(400, "no fields to update")

    if "produced_by" in changes:
        # SignalTypePatch carries no scope — it is immutable — so the registry
        # check has to happen where the stored scope is known.
        problems = await source_service.validate(session, changes["produced_by"], row.scope)
        if problems:
            raise HTTPException(422, "; ".join(problems))
    if changes.get("durability_days") == 0:
        # `null` already means "leave alone" in a patch, so it cannot also mean
        # "clear". Zero is the clear, and it restores the default rather than
        # writing it out — so a later TTL change carries its durability along.
        changes["durability_days"] = None
    # Against the TTL that will be in force after this patch, not the one
    # stored: a single call may lower both, and checking the old value would
    # refuse a pair that is fine together.
    ttl = changes.get("default_ttl_days", row.default_ttl_days)
    durable = changes.get("durability_days", row.durability_days)
    if durable is not None and durable < ttl:
        raise HTTPException(
            422,
            f"durability_days ({durable}) must be at least default_ttl_days "
            f"({ttl}) — a fact cannot stop being worth reading before it stops "
            "being a hook",
        )
    for field, value in changes.items():
        setattr(row, field, value)

    await session.commit()
    _annotate([row], await _signal_counts(session))
    return row


@router.delete("/signal-types/{key}", status_code=204)
async def delete_signal_type(key: str, session: AsyncSession = Depends(get_session)):
    """Delete a type that never produced anything.

    The rule is deprecate-never-delete, and the reason for it is that a
    qualification decided partly on a type has to stay explainable. A type with
    zero signals has no such history behind it — nothing cites it, so nothing
    loses its citation. Deleting it destroys a registry row and nothing else.

    The moment one signal exists the door closes permanently, which is why the
    count is authoritative here rather than the status: a mistyped type caught
    the same afternoon is a typo, and a type that has classified real evidence
    is a decision.
    """
    row = await _get_signal_type(session, key)

    counts = await _signal_counts(session)
    used = counts.get(key, 0)
    if used:
        raise HTTPException(
            409,
            f"{key!r} has produced {used} signal(s) and cannot be deleted — "
            "deprecate it instead, so the qualifications that used it stay explainable",
        )

    await session.delete(row)
    await session.commit()


@router.post("/signal-types/{key}/pause", response_model=SignalTypeOut)
async def pause_signal_type(key: str, session: AsyncSession = Depends(get_session)):
    """Stop extracting this type, reversibly.

    Distinct from deprecation: a paused type is expected to come back, so it
    keeps its place in the registry and can be resumed. Use it to take a noisy
    type out while it is tuned, rather than retiring something you still want.
    """
    row = await _get_signal_type(session, key)
    if row.status == "deprecated":
        raise HTTPException(
            409, f"{key!r} is deprecated — deprecation is terminal and cannot be paused"
        )
    if row.status == "paused":
        return row
    row.status = "paused"
    row.paused_at = datetime.now(UTC)
    await session.commit()
    return row


@router.post("/signal-types/{key}/resume", response_model=SignalTypeOut)
async def resume_signal_type(key: str, session: AsyncSession = Depends(get_session)):
    """Return a paused type to extraction."""
    row = await _get_signal_type(session, key)
    if row.status == "deprecated":
        raise HTTPException(
            409,
            f"{key!r} is deprecated and cannot be resumed — create a new type instead",
        )
    row.status = "active"
    row.paused_at = None
    await session.commit()
    return row


@router.post("/signal-types/{key}/deprecate", response_model=SignalTypeOut)
async def deprecate_signal_type(key: str, session: AsyncSession = Depends(get_session)):
    """Retire a type without destroying its history.

    There is no DELETE for signal types. Existing signals keep rendering, keep
    their evidence, and stay available to the Learning layer — a qualification
    decided partly on this type must still be able to explain itself.
    """
    row = await _get_signal_type(session, key)
    if row.status == "deprecated":
        return row
    row.status = "deprecated"
    row.deprecated_at = datetime.now(UTC)
    # Deprecating a paused type must clear paused_at, or the consistency
    # constraint rejects the write.
    row.paused_at = None
    await session.commit()
    return row
