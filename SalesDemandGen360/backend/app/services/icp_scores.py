"""A company's qualification, read for one ICP.

A company is qualified once — the model judges opportunity, commercial and
intent against its evidence, and that judgement does not depend on who we sell
to. Fit (size, industry, country) and buyer (whether the ICP's personas are
reachable there) do depend on the ICP, and both are computed in Python. So the
score for any ICP is the stored assessment with those two recomputed and the
roll-up re-run: no model call, the same answer every time.

Used wherever an ICP is known — the queue rule for a queue's ICP, the outreach
screen for a campaign's ICP, and the account page's score per ICP.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Contact
from app.models.config import IcpProfile, IcpProfileVersion, ScoringConfig
from app.models.context import Qualification
from app.schemas.qualification import DIMENSIONS
from app.services import dimensions, scoring, sizing
from app.services import fit as fit_service


@dataclass
class IcpScore:
    icp_profile_id: uuid.UUID
    icp_name: str
    icp_version: int
    qualification_id: uuid.UUID
    priority_score: float
    priority_band: str
    scoring_config_version: int
    #: {dimension, score, reason, basis, evidence_ids} for each of the six.
    dimensions: list[dict] = field(default_factory=list)


async def company_qualification(session: AsyncSession, account_id) -> Qualification | None:
    """The company's most recent qualification."""
    return (
        await session.execute(
            select(Qualification)
            .where(Qualification.account_id == account_id)
            .order_by(Qualification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def rescore(
    account: Account,
    qualification: Qualification,
    *,
    icp_name: str,
    definition: dict,
    contacts: list[Contact],
    config: ScoringConfig,
) -> tuple[float, str, list[dict]]:
    """The stored assessment with fit and buyer computed for this ICP."""
    reasons = qualification.reasons or {}
    raw = {d: dict(reasons[d]) for d in DIMENSIONS if isinstance(reasons.get(d), dict)}
    raw["fit"] = fit_service.assess(account, definition or {}, icp=icp_name).as_assessment()
    raw["buyer"] = dimensions.assess_buyer(contacts, definition or {}, icp=icp_name).as_assessment()
    result = scoring.score(
        raw,
        config=config,
        industry=reasons.get("_industry") or account.industry,
        size_band=reasons.get("_size_band") or sizing.band_for(account.employee_count),
    )
    dims = [
        {
            "dimension": d.dimension,
            "score": d.score,
            "reason": d.reason,
            "basis": d.basis,
            "evidence_ids": [str(e) for e in d.evidence_ids],
        }
        for d in result.dimensions
    ]
    return result.priority_score, result.priority_band, dims


async def _config(session: AsyncSession) -> ScoringConfig | None:
    return (
        await session.execute(select(ScoringConfig).where(ScoringConfig.is_active.is_(True)))
    ).scalar_one_or_none()


async def _contacts(session: AsyncSession, account_id) -> list[Contact]:
    return list(
        (await session.execute(select(Contact).where(Contact.account_id == account_id))).scalars()
    )


async def _icps(session: AsyncSession, icp_profile_id=None) -> list[tuple[IcpProfile, IcpProfileVersion]]:
    stmt = (
        select(IcpProfile, IcpProfileVersion)
        .join(IcpProfileVersion, IcpProfileVersion.icp_profile_id == IcpProfile.id)
        .where(IcpProfileVersion.is_active.is_(True))
        .order_by(IcpProfile.name)
    )
    if icp_profile_id is not None:
        stmt = stmt.where(IcpProfile.id == icp_profile_id)
    return [tuple(r) for r in (await session.execute(stmt)).all()]


async def scores(
    session: AsyncSession, account: Account, *, icp_profile_id=None
) -> list[IcpScore]:
    """The company's score for every active ICP, or for one."""
    qualification = await company_qualification(session, account.id)
    config = await _config(session)
    if qualification is None or config is None:
        return []
    icps = await _icps(session, icp_profile_id)
    if not icps:
        return []
    contacts = await _contacts(session, account.id)
    out: list[IcpScore] = []
    for profile, version in icps:
        try:
            score, band, dims = rescore(
                account, qualification, icp_name=profile.name,
                definition=version.definition or {}, contacts=contacts, config=config,
            )
        except ValueError:
            # A stored assessment missing a dimension cannot be rolled up —
            # the company-wide score says so on its own page.
            continue
        out.append(IcpScore(
            icp_profile_id=profile.id, icp_name=profile.name, icp_version=version.version,
            qualification_id=qualification.id, priority_score=score, priority_band=band,
            scoring_config_version=config.version, dimensions=dims,
        ))
    return out


def as_rating(score: IcpScore | None, minimum: str) -> dict:
    """One company rating, as every table shows it.

    `not_qualified` is its own answer rather than a fail: nobody has judged the
    company yet, which sends a rep to qualify it, not to drop it.
    """
    from app.services.promotion import BAND_ORDER

    if score is None:
        gate, detail = "not_qualified", "company not qualified yet"
    else:
        reaches = BAND_ORDER[score.priority_band] >= BAND_ORDER[minimum]
        gate = "pass" if reaches else "below"
        detail = (
            f"{score.priority_band} {score.priority_score:.0f} for {score.icp_name} "
            f"{'meets' if reaches else 'is below'} the minimum band ({minimum})"
        )
    return {
        "qualification_score": score.priority_score if score else None,
        "qualification_band": score.priority_band if score else None,
        "icp_name": score.icp_name if score else None,
        "gate": gate,
        "gate_detail": detail,
    }


async def best_rating(
    session: AsyncSession, account_id, icp_profile_ids=None, *, minimum: str | None = None
) -> dict:
    """The company's best rating across the ICPs a screen is working for.

    Best rather than average, as fit already is: a list worked for two ICPs
    needs its accounts to fit one of them, not both.
    """
    from app.services.promotion import BAND_ORDER, queue_gate

    account = await session.get(Account, account_id)
    if account is None:
        return as_rating(None, minimum or await queue_gate(session))
    found = await scores(session, account)
    wanted = {str(i) for i in (icp_profile_ids or [])}
    if wanted:
        found = [s for s in found if str(s.icp_profile_id) in wanted] or []
    best = max(found, key=lambda s: (s.priority_score, s.icp_name), default=None)
    return as_rating(best, minimum or await queue_gate(session))


async def gate_for(session: AsyncSession, account_id, icp_profile_id, *, min_band: str | None = None) -> dict:
    """The rating for one named ICP — a campaign's or a queue's."""
    from app.services.promotion import queue_gate

    minimum = min_band or await queue_gate(session)
    score = await score_for(session, account_id, icp_profile_id)
    return as_rating(score, minimum)


async def score_for(session: AsyncSession, account_id, icp_profile_id) -> IcpScore | None:
    """The company's score for one ICP, or None when it has not been qualified."""
    account = await session.get(Account, account_id)
    if account is None or icp_profile_id is None:
        return None
    found = await scores(session, account, icp_profile_id=icp_profile_id)
    return found[0] if found else None
