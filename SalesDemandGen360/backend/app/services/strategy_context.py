"""Everything strategy is given about one company, and the order its signals matter in.

`docs/18`. The model argues from the whole picture — the company, its live
signals with the evidence behind them, the campaign's ICP and service, the
approved proof for that service, and each person — and never from the gates.
Weight, rank, the qualification score and a rep's override decide only whether
a person proceeds; once they do, none of it reaches the prompt, so an
overridden person is argued for exactly as well as anyone the rules chose.

**Signals are ranked here, in Python** (invariant 7's spirit: a number a rep
can be told the reason for). The model is told the rank and leads with the top
signal that fits an angle.
"""

from __future__ import annotations

import math
import uuid
from datetime import date
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Contact
from app.models.config import IcpProfileVersion, ProofPoint, ServiceCatalog
from app.models.signal import Evidence, Signal, signal_evidence
from app.services import persona

#: high 3, medium 2, low 1 — the strength a signal was extracted with.
STRENGTH = {"high": 3.0, "medium": 2.0, "low": 1.0}
#: A signal's pull halves every this many days since it was observed.
HALF_LIFE_DAYS = 60.0
#: A signal whose type the ICP lists under `signals_that_matter`.
ICP_MATCH = 1.5
#: A signal about the person themselves, in that person's own list.
ABOUT_THIS_PERSON = 1.3
#: Evidence excerpts per signal, and their length. Enough to quote, not to read.
EXCERPTS_PER_SIGNAL = 2
EXCERPT_CHARS = 400


def rank_score(signal: Signal, *, matters: set[str], about_person: bool, today: date) -> tuple[float, int]:
    """`strength × confidence × recency × icp_match × about_this_person`, and the age in days."""
    age = max(0, (today - signal.observed_at).days) if signal.observed_at else 365
    score = (
        STRENGTH.get(signal.strength or "", 1.0)
        * float(signal.confidence if signal.confidence is not None else 0.5)
        * math.pow(0.5, age / HALF_LIFE_DAYS)
        * (ICP_MATCH if signal.signal_type in matters else 1.0)
        * (ABOUT_THIS_PERSON if about_person else 1.0)
    )
    return score, age


def ranked(signals: list[Signal], *, matters: set[str], about_person: bool, today: date) -> list[tuple[int, float, int, Signal]]:
    """`(rank, score, age_days, signal)`, best first. Ties broken by id so the
    order — and the prompt — is the same on every run."""
    scored = [(*rank_score(s, matters=matters, about_person=about_person, today=today), s) for s in signals]
    scored.sort(key=lambda r: (-r[0], str(r[2].id)))
    return [(i + 1, score, age, s) for i, (score, age, s) in enumerate(scored)]


async def excerpts(session: AsyncSession, signal_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    """The newest few excerpts behind each signal, with where and when they came from."""
    out: dict[uuid.UUID, list[dict]] = {}
    if not signal_ids:
        return out
    rows = (
        await session.execute(
            select(signal_evidence.c.signal_id, Evidence)
            .join(Evidence, Evidence.id == signal_evidence.c.evidence_id)
            .where(signal_evidence.c.signal_id.in_(signal_ids))
            .order_by(Evidence.observed_at.desc().nullslast(), Evidence.id)
        )
    ).all()
    for sid, ev in rows:
        bucket = out.setdefault(sid, [])
        if len(bucket) >= EXCERPTS_PER_SIGNAL or not ev.excerpt:
            continue
        when = ev.observed_at
        bucket.append({
            "excerpt": ev.excerpt[:EXCERPT_CHARS],
            "source": ev.source_name or (urlparse(ev.source_url).netloc if ev.source_url else None),
            "date": (when.date() if hasattr(when, "hour") else when).isoformat() if when else None,
        })
    return out


def matched_persona(contact: Contact, personas: list[dict]) -> dict | None:
    """The ICP persona this person fits — by buying role, then by title."""
    title = (contact.title or "").lower()
    for p in personas or []:
        if contact.buying_role and p.get("buying_role") == contact.buying_role:
            return p
        if any(t and t.lower() in title for t in p.get("titles", [])):
            return p
    return None


def _person_role(contact: Contact) -> dict[str, Any]:
    """What we know of their role. Classified from the title where nothing is
    stored, so the prompt never says `unknown` about a CTO."""
    seniority = contact.seniority if contact.seniority not in (None, "", "unknown") else persona.classify_seniority(contact.title)
    return {
        "seniority": seniority,
        "buying_role": contact.buying_role or persona.classify_buying_role(contact.title),
        "department": persona.classify_department(contact.title),
    }


async def build(
    session: AsyncSession,
    *,
    account: Account,
    contacts: list[Contact],
    service: ServiceCatalog,
    icp_name: str,
    icp_description: str | None,
    icp_version: IcpProfileVersion,
    no_signal_allowed: set[uuid.UUID],
    today: date | None = None,
) -> tuple[dict[str, Any], set[str], set[str]]:
    """The payload for one company, and the live signal ids and proof ids it offered.

    The two id sets are what the answer is checked against: a cited signal
    must be one of these, and so must a cited proof point.
    """
    from app.services import context as context_service
    from app.services import stages

    today = today or date.today()
    definition = icp_version.definition or {}
    matters = set(definition.get("signals_that_matter") or [])

    live = await context_service.live_signals(session, account.id, today=today)
    company_live = [s for s in live if not s.contact_id]
    behind = await excerpts(session, [s.id for s in live])

    def as_dict(rank: int, score: float, age: int, s: Signal) -> dict[str, Any]:
        return {
            "signal_id": str(s.id),
            "signal_rank": rank,
            "rank_score": round(score, 3),
            "type": s.signal_type,
            "summary": s.summary,
            "business_implication": s.business_implication,
            "strength": s.strength,
            "confidence": float(s.confidence) if s.confidence is not None else None,
            "age_days": age,
            "is_hypothesis": s.is_hypothesis,
            "icp_lists_this_type": s.signal_type in matters,
            "evidence": behind.get(s.id, []),
        }

    proofs = (
        await session.execute(
            select(ProofPoint)
            .where(
                ProofPoint.is_approved.is_(True),
                (ProofPoint.service_id == service.id) | (ProofPoint.service_id.is_(None)),
            )
            .order_by(ProofPoint.title, ProofPoint.id)
        )
    ).scalars().all()

    people = []
    for c in contacts:
        mine = [s for s in live if s.contact_id == c.id]
        people.append({
            "contact_id": str(c.id),
            "full_name": c.full_name,
            "title": c.title,
            **_person_role(c),
            "icp_persona_matched": matched_persona(c, definition.get("personas") or []),
            "profile": stages._profile_facts(c),
            "contact_signals": [as_dict(*r) for r in ranked(mine, matters=matters, about_person=True, today=today)],
            "may_cite_no_live_signal": c.id in no_signal_allowed,
        })

    payload = {
        "company": stages._account_facts(account),
        "company_signals": [
            as_dict(*r) for r in ranked(company_live, matters=matters, about_person=False, today=today)
        ],
        "icp": {
            "name": icp_name,
            "description": icp_description,
            **{
                k: definition.get(k)
                for k in ("track", "industries", "regions", "employees", "personas",
                          "signals_that_matter", "exclusions")
                if definition.get(k)
            },
        },
        "service": {
            "id": str(service.id),
            "code": service.code,
            "name": service.name,
            "description": service.description,
            "positioning_angles": service.positioning_angles or [],
            "economic_buyer": service.economic_buyer,
        },
        "proof_points": [
            {"id": str(p.id), "kind": p.kind, "title": p.title, "body": p.body, "metrics": p.metrics or {}}
            for p in proofs
        ],
        # Stated as a number as well as implied by the list: the list cannot be
        # bounded in the schema (Gemini answers `maxItems` with HTTP 400), and
        # a model writing people until the budget runs out loses everything.
        "person_count": len(people),
        "people": people,
    }
    return payload, {str(s.id) for s in live}, {str(p.id) for p in proofs}


# --------------------------------------------------------------------------
# the same picture, for one person — drafting and sales prep
# --------------------------------------------------------------------------
def targets_brief(*, service: ServiceCatalog | None, icp_name: str | None, icp_description: str | None,
                  icp_version: IcpProfileVersion | None) -> dict[str, Any]:
    """The campaign's ICP and service, as strategy saw them.

    Drafting and prep used to get only the catalogue of every service and
    every ICP, and had to guess which this person was being approached about.
    """
    definition = (icp_version.definition or {}) if icp_version else {}
    out: dict[str, Any] = {}
    if icp_name:
        out["icp"] = {
            "name": icp_name,
            "description": icp_description,
            **{k: definition.get(k) for k in ("track", "industries", "personas") if definition.get(k)},
        }
    if service is not None:
        out["service"] = {
            "code": service.code,
            "name": service.name,
            "description": service.description,
            "positioning_angles": service.positioning_angles or [],
        }
    return out


async def signal_brief(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    icp_version: IcpProfileVersion | None,
    cited: set[str] | frozenset = frozenset(),
    evidence_for_all: bool = False,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Every live signal for one person's company and for them, ranked as
    strategy ranks them, with `is_trigger` marking what the pitch rests on.

    "Live" is `context.live_signals` — not expired by date, not superseded —
    the one definition strategy, drafting and prep now share (prep used a
    lifecycle flag and could disagree about what counted).

    Evidence excerpts go with the cited signals (drafting) or all of them
    (prep, which argues from the whole picture on a call). Never URLs: they
    are for a rep checking a claim, and nothing downstream reasons with them.
    """
    from app.services import context as context_service

    today = today or date.today()
    matters = set(((icp_version.definition or {}) if icp_version else {}).get("signals_that_matter") or [])
    live = await context_service.live_signals(session, account_id, today=today)
    mine = [s for s in live if contact_id and s.contact_id == contact_id]
    company = [s for s in live if not s.contact_id]
    scored = [
        (*rank_score(s, matters=matters, about_person=s in mine, today=today), s)
        for s in company + mine
    ]
    scored.sort(key=lambda r: (-r[0], str(r[2].id)))
    wanted_evidence = [s.id for _, _, s in scored if evidence_for_all or str(s.id) in cited]
    behind = await excerpts(session, wanted_evidence)
    out = []
    for rank, (score, age, s) in enumerate(scored, start=1):
        row: dict[str, Any] = {
            "signal_id": str(s.id),
            "signal_rank": rank,
            "rank_score": round(score, 3),
            "is_trigger": str(s.id) in cited,
            "about_this_person": s in mine,
            "type": s.signal_type,
            "summary": s.summary,
            "business_implication": s.business_implication,
            "strength": s.strength,
            "confidence": float(s.confidence) if s.confidence is not None else None,
            "age_days": age,
            "expires_in_days": max((s.expires_at - today).days, 0) if getattr(s, "expires_at", None) else None,
            "is_hypothesis": s.is_hypothesis,
            "icp_lists_this_type": s.signal_type in matters,
        }
        if s.id in behind:
            row["evidence"] = behind[s.id]
        out.append(row)
    return out
