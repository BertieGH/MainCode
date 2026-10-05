"""Qualification and strategy for a campaign's people, against the campaign's service and ICP.

A strategy is the argument for approaching one person about one service, for
one ICP — so it belongs to the campaign, not to the company: the same person
needs a different argument for EIA than for QA. The company's
qualification is not scored here: it stays with the company, and is shown read
for the campaign's ICP (`icp_scores`).

**Defaults follow the sales rules; a rep may override, and it is recorded.**

* Who is pursued: `strategy.build_matrix` and `select_threads` — role weight,
  contact signals, service fit, `persona_weight_threshold`,
  `max_concurrent_threads`. A person below the threshold or over the limit is
  left out unless the rep ticks *pursue anyway* (`chosen_by_rep`).
* A live signal: a strategy normally cites one. With none about the company a
  person is left out unless the rep ticks *allow without one*
  (`without_live_trigger`).

Both overrides flag the sequence in approval, so a person reads it rather than
a sample. Qualification is not required to build a strategy.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Contact
from app.models.campaign import OutreachCampaign, OutreachSequence
from app.models.config import (
    IcpProfile,
    IcpProfileVersion,
    SalesRules,
    ScoringConfig,
    ServiceCatalog,
)
from app.models.context import AccountContext
from app.models.signal import Signal
from app.models.strategy import PersonaServiceScore, Strategy, StrategyThread
from app.services import context as context_service
from app.services import campaign_drafts
from app.services import icp_scores
from app.services import strategy as rules_service
from app.services.dimensions import personas_of
from app.services.promotion import reachable

log = logging.getLogger(__name__)

#: Used only when no sales rules are configured.
DEFAULT_THRESHOLD = 20.0
DEFAULT_CAP = 2
DEFAULT_OFFSET = 3
PURSUED = ("active_primary", "active_secondary")

DECISION_LABELS = {
    "pursue": "pursue",
    "below_threshold": "below threshold",
    "over_limit": "over the limit",
    "not_reachable": "not reachable",
}


class NotReadyError(RuntimeError):
    """The campaign cannot be qualified or strategised yet, with the reason."""


async def choose_targets(session: AsyncSession, service_id, icp_profile_id) -> int:
    """Check a service and ICP go together, and return the ICP version in force."""
    from app.models.config import service_icp_link

    service = await session.get(ServiceCatalog, service_id)
    profile = await session.get(IcpProfile, icp_profile_id)
    if service is None or profile is None:
        raise NotReadyError("that service or ICP no longer exists")
    linked = await session.scalar(
        select(func.count())
        .select_from(service_icp_link)
        .where(
            service_icp_link.c.service_id == service.id,
            service_icp_link.c.icp_profile_id == profile.id,
        )
    )
    if not linked:
        raise NotReadyError(
            f"ICP {profile.name} is not linked to {service.code} — link them in Setup, "
            "or choose another ICP"
        )
    version = await session.scalar(
        select(IcpProfileVersion.version).where(
            IcpProfileVersion.icp_profile_id == profile.id, IcpProfileVersion.is_active.is_(True)
        )
    )
    if version is None:
        raise NotReadyError(f"ICP {profile.name} has no active version")
    return version


async def set_targets(session: AsyncSession, campaign: OutreachCampaign, service_id, icp_profile_id) -> None:
    """Choose the service and ICP for a campaign promoted before queues carried them."""
    if campaign.status != "draft":
        raise NotReadyError("a campaign's service and ICP can only be chosen while it is a draft")
    if (campaign.service_id, campaign.icp_profile_id) != (service_id, icp_profile_id):
        built = await session.scalar(
            select(func.count()).select_from(Strategy).where(Strategy.campaign_id == campaign.id)
        )
        if built:
            raise NotReadyError(
                "strategy was already built for this campaign's service and ICP — changing them "
                "would leave it arguing for the wrong thing. Clone the queue instead."
            )
    campaign.icp_version = await choose_targets(session, service_id, icp_profile_id)
    campaign.service_id, campaign.icp_profile_id = service_id, icp_profile_id
    await session.flush()


@dataclass
class Targets:
    service: ServiceCatalog
    icp_name: str
    icp_version: IcpProfileVersion


async def targets(session: AsyncSession, campaign: OutreachCampaign) -> Targets:
    if campaign.service_id is None or campaign.icp_profile_id is None:
        raise NotReadyError(
            "this campaign has no service and ICP yet — its queue was created before they "
            "were chosen with the queue. Choose them here to score and build strategy."
        )
    service = await session.get(ServiceCatalog, campaign.service_id)
    profile = await session.get(IcpProfile, campaign.icp_profile_id)
    if service is None or profile is None:
        raise NotReadyError("the campaign's service or ICP no longer exists")
    stmt = select(IcpProfileVersion).where(IcpProfileVersion.icp_profile_id == profile.id)
    stmt = (
        stmt.where(IcpProfileVersion.version == campaign.icp_version)
        if campaign.icp_version
        else stmt.where(IcpProfileVersion.is_active.is_(True))
    )
    version = (await session.execute(stmt.limit(1))).scalar_one_or_none()
    if version is None:
        raise NotReadyError(f"ICP {profile.name} has no version {campaign.icp_version or '(active)'}")
    return Targets(service=service, icp_name=profile.name, icp_version=version)


@dataclass
class Rules:
    threshold: float
    cap: int
    offset: int
    role_weights: dict


async def sales_rules(session: AsyncSession) -> Rules:
    row = (
        await session.execute(select(SalesRules).where(SalesRules.is_active.is_(True)))
    ).scalar_one_or_none()
    scoring = (
        await session.execute(select(ScoringConfig).where(ScoringConfig.is_active.is_(True)))
    ).scalar_one_or_none()
    return Rules(
        threshold=float(row.persona_weight_threshold) if row else DEFAULT_THRESHOLD,
        cap=int(row.max_concurrent_threads) if row else DEFAULT_CAP,
        offset=int(row.thread_start_offset_days) if row else DEFAULT_OFFSET,
        role_weights=dict(getattr(scoring, "persona_role_weights", None) or {}),
    )


async def people_of(
    session: AsyncSession, campaign_id: uuid.UUID
) -> list[tuple[OutreachSequence, Contact, Account]]:
    """Everyone the campaign has a sequence for, with their company."""
    rows = await session.execute(
        select(OutreachSequence, Contact, Account)
        .join(Contact, Contact.id == OutreachSequence.contact_id)
        .join(Account, Account.id == Contact.account_id)
        .where(OutreachSequence.campaign_id == campaign_id)
        .order_by(Account.name, Contact.full_name)
    )
    return [tuple(r) for r in rows.all()]


@dataclass
class Decision:
    weight: float
    thread_status: str
    default: str
    detail: str
    rank: int


def decide(targets_: Targets, rules: Rules, contacts: list[Contact], live: list) -> tuple[list, dict]:
    """The rules' answer for each person at one company. No model call."""
    roles = tuple(sorted({role for role, _ in personas_of(targets_.icp_version.definition or {}) if role}))
    about: dict = {}
    for signal in live:
        if getattr(signal, "contact_id", None):
            about.setdefault(signal.contact_id, []).append((signal.id, signal.strength))
    personas = [
        rules_service.PersonaInput(
            contact_id=c.id, full_name=c.full_name, buying_role=c.buying_role,
            seniority=c.seniority, signals=tuple(about.get(c.id, [])), contactable=reachable(c),
        )
        for c in contacts
    ]
    cells = rules_service.build_matrix(
        personas,
        [rules_service.ServiceInput(
            service_id=targets_.service.id, code=targets_.service.code, target_personas=roles,
        )],
        persona_role_weights=rules.role_weights,
    )
    selected = rules_service.select_threads(
        cells,
        persona_weight_threshold=rules.threshold,
        max_concurrent_threads=rules.cap,
        thread_start_offset_days=rules.offset,
    )
    rationale = {c.contact_id: c.rationale for c in cells}
    by_id = {c.id: c for c in contacts}
    decisions: dict = {}
    for s in selected:
        contact = by_id[s.contact_id]
        if s.thread_status in PURSUED:
            default, detail = "pursue", f"weight {s.weight:g} meets the threshold of {rules.threshold:g}"
        elif not reachable(contact):
            default, detail = "not_reachable", "no verified email or LinkedIn profile"
        elif s.thread_status == "queued":
            default, detail = (
                "over_limit",
                f"weight {s.weight:g} qualifies, but {rules.cap} people at this company are already pursued",
            )
        else:
            default, detail = (
                "below_threshold",
                f"weight {s.weight:g} is below the threshold of {rules.threshold:g} ({rationale[s.contact_id]})",
            )
        decisions[s.contact_id] = Decision(s.weight, s.thread_status, default, detail, s.rank)
    return cells, decisions


async def current_threads(session: AsyncSession, campaign_id, account_id) -> dict:
    strategy = (
        await session.execute(
            select(Strategy)
            .where(
                Strategy.campaign_id == campaign_id,
                Strategy.account_id == account_id,
                Strategy.status != "superseded",
            )
            .order_by(Strategy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if strategy is None:
        return {}
    threads = (
        await session.execute(select(StrategyThread).where(StrategyThread.strategy_id == strategy.id))
    ).scalars()
    return {t.contact_id: t for t in threads}


async def people_view(session: AsyncSession, campaign: OutreachCampaign) -> dict:
    """Each person with their qualification, the rules' default and their strategy."""
    t = await targets(session, campaign)
    rules = await sales_rules(session)
    rows = await people_of(session, campaign.id)
    by_account: dict = {}
    for sequence, contact, account in rows:
        by_account.setdefault(account.id, []).append((sequence, contact, account))

    people: list[dict] = []
    for account_id, group in by_account.items():
        contacts = [c for _, c, _ in group]
        live = await context_service.live_signals(session, account_id)
        # Research can find only old news: say so, rather than "none".
        current = await session.scalar(
            select(func.count())
            .select_from(Signal)
            .where(Signal.account_id == account_id, Signal.superseded_by.is_(None))
        ) or 0
        expired = max(0, current - len(live))
        _, decisions = decide(t, rules, contacts, live)
        gate = await icp_scores.gate_for(session, account_id, t.icp_version.icp_profile_id)
        threads = await current_threads(session, campaign.id, account_id)
        for sequence, contact, account in group:
            d = decisions[contact.id]
            thread = threads.get(contact.id)
            arc = await campaign_drafts.arc_of(session, sequence.id)
            state = campaign_drafts.state_of(sequence, thread is not None, arc)
            people.append({
                "sequence_id": sequence.id,
                "contact_id": contact.id,
                "full_name": contact.full_name,
                "title": contact.title,
                "account_id": account.id,
                "account_name": account.name,
                "reachable": reachable(contact),
                "weight": d.weight,
                "default_decision": d.default,
                "decision_detail": d.detail,
                "live_signals": len(live),
                "expired_signals": expired,
                **gate,
                "strategy_status": thread.thread_status if thread else None,
                "chosen_by_rep": bool(thread and thread.chosen_by_rep),
                "without_live_trigger": bool(thread and thread.without_live_trigger),
                "problem_hypothesis": thread.problem_hypothesis if thread else None,
                # Where their cadence drafts stand, so this table can be picked
                # from accurately: strategy and drafts are two different gates,
                # and choosing by one while acting on the other is the mistake.
                "draft_state": state,
                "draft_state_label": campaign_drafts.STATE_LABELS[state],
                "touch_count": len(arc),
                "edited": campaign_drafts.edited(arc),
                # Withdrawn people stay visible and greyed — they were in this
                # campaign and a rep needs to see why they are not any more.
                # This table did not carry it, so a withdrawn person looked
                # like anybody else: their strategy would not build, and the
                # only explanation offered was "the model returned no case".
                "withdrawn": sequence.status == "cancelled",
                "withdraw_reason": sequence.withdraw_reason,
            })
    return {
        "service_code": t.service.code,
        "icp_name": t.icp_name,
        "icp_version": t.icp_version.version,
        "threshold": rules.threshold,
        "cap": rules.cap,
        "people": people,
    }


@dataclass
class BuildOutcome:
    account_id: uuid.UUID
    name: str
    built: bool = False
    version: int | None = None
    pursued: list[str] = field(default_factory=list)
    #: Pursued only because a rep ticked "pursue anyway".
    overridden: list[str] = field(default_factory=list)
    #: Built without a live signal, because a rep allowed it.
    without_trigger: list[str] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    note: str = ""


async def build(
    session: AsyncSession,
    campaign: OutreachCampaign,
    account: Account,
    *,
    pursue_anyway: set = frozenset(),
    allow_without_signal: set = frozenset(),
    synthesise=None,
) -> BuildOutcome:
    """Build this campaign's strategy for its people at one company.

    Raises `strategy.DifferentiationError` when two people would get the same
    argument — nothing is stored then.
    """
    from app.services import stages

    t = await targets(session, campaign)
    rules = await sales_rules(session)
    out = BuildOutcome(account.id, account.name)
    group = [(s, c) for s, c, a in await people_of(session, campaign.id) if a.id == account.id]
    if not group:
        out.note = "nobody from this company is in the campaign"
        return out

    contacts = [c for _, c in group]
    live = await context_service.live_signals(session, account.id)
    live_ids = {str(s.id) for s in live}
    cells, decisions = decide(t, rules, contacts, live)

    # Withdrawn from this campaign: not a candidate, whatever the rules say
    # and whatever a rep ticks. Checked first, so the reason given is the
    # withdrawal rather than a threshold they also happen to miss — and so
    # that an override cannot quietly pull somebody back in. Reinstating them
    # is a deliberate act on the Threads tab.
    withdrawn = {c.id: s for s, c in group if s.status == "cancelled"}

    chosen: list[Contact] = []
    for contact in contacts:
        d = decisions[contact.id]
        if contact.id in withdrawn:
            reason = withdrawn[contact.id].withdraw_reason
            out.excluded.append({
                "name": contact.full_name,
                "reason": (
                    "withdrawn from this campaign"
                    + (f" — {reason}" if reason else "")
                    + ". Reinstate them on the Threads tab to build a strategy"
                ),
            })
            continue
        if d.default != "pursue" and contact.id not in pursue_anyway:
            out.excluded.append({"name": contact.full_name, "reason": d.detail})
            continue
        if not live_ids and contact.id not in allow_without_signal:
            out.excluded.append({
                "name": contact.full_name,
                "reason": "no live signal about this company — allow it to build without one",
            })
            continue
        chosen.append(contact)
    if not chosen:
        out.note = "nobody to build a strategy for"
        return out

    context = (
        await session.execute(
            select(AccountContext)
            .where(AccountContext.account_id == account.id)
            .order_by(AccountContext.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or await context_service.build_context(session, account_id=account.id)

    ordered = sorted(chosen, key=lambda c: decisions[c.id].rank)
    plan = []
    for i, contact in enumerate(ordered):
        plan.append({
            "contact_id": contact.id,
            "service_id": t.service.id,
            "service": t.service.code,
            "weight": decisions[contact.id].weight,
            "rank": i + 1,
            "thread_status": "active_primary" if i == 0 else "active_secondary",
            "start_offset_days": i * rules.offset,
            "chosen_by_rep": decisions[contact.id].default != "pursue",
            "may_cite_no_live_signal": contact.id in allow_without_signal,
        })

    if synthesise is None:
        async def synthesise(**kwargs):
            return await stages.synthesise_strategy(session, **kwargs)

    # `chosen_by_rep` is governance, not an instruction: told that the weights
    # had left somebody out, the model dropped them and argued nobody — which
    # is how a rep's override turned into "no case was argued for them". It is
    # recorded on the thread and read in approval; the model is not told.
    #
    # `weight` was withheld here too for a while, on the theory that a 40 said
    # the same thing in a number. Tested against the live model: it makes no
    # difference, so it stays — the experiment is in the corrections log.
    asked = [{k: v for k, v in item.items() if k != "chosen_by_rep"} for item in plan]

    # One retry, because this call is measurably unreliable rather than
    # opinionated. The same request for the same person, minutes apart, has
    # returned one sound thread on 411 output tokens and an empty list on 790
    # — and, at a lower budget, burned the whole allowance thinking and
    # truncated. Returning nothing is a contract violation: the prompt asks
    # for one thread per entry and says why, and who is approached was decided
    # before the model was asked. So an empty answer is retried once and only
    # then reported — and reported as a provider failure, not as a judgement
    # about the person, which is what sent a rep looking for their own mistake.
    wanted = {c.id: c for c in ordered}

    def answers_nobody(parsed) -> bool:
        """Nothing here is about a person we asked about.

        Used to be "the threads list is empty", which `StrategyProposal`'s
        `min_length=1` now makes unreachable — the contract refuses that at
        parse time. The useless answer that remains is one carrying threads for
        somebody else entirely: it satisfies the schema, is discarded here, and
        leaves the rep told that nothing came back for their person.
        """
        return not any(t.contact_id in wanted for t in parsed.threads)

    result = await synthesise(account=account, context=context, threads=asked, contacts=ordered)
    if answers_nobody(result.parsed):
        log.warning(
            "campaign_strategy.empty_proposal account=%s asked=%d returned=%d — retrying once",
            account.id, len(asked), len(result.parsed.threads),
        )
        result = await synthesise(account=account, context=context, threads=asked, contacts=ordered)
    proposal = result.parsed
    accepted = []
    log.info(
        "campaign_strategy.proposal account=%s asked=%d returned=%d ids=%s",
        account.id, len(asked), len(proposal.threads),
        [str(t.contact_id) for t in proposal.threads],
    )
    for proposed in proposal.threads:
        contact = wanted.get(proposed.contact_id)
        if contact is None:
            # The model may not add a person — but a thread dropped here is
            # invisible, and the rep is told "the model returned nothing for
            # them", which sends them looking at the person rather than at a
            # `contact_id` that came back subtly wrong. Say which id arrived
            # and which were sent.
            log.warning(
                "campaign_strategy.unknown_contact account=%s returned=%s sent=%s",
                account.id, proposed.contact_id, sorted(str(k) for k in wanted),
            )
            continue
        cited = [s for s in proposed.trigger_signal_ids if s in live_ids]
        if not cited and contact.id not in allow_without_signal:
            out.excluded.append({"name": contact.full_name, "reason": "the strategy cited no live signal"})
            continue
        accepted.append((contact, proposed, cited))
    argued = {c.id for c, _, _ in accepted}
    named = {e["name"] for e in out.excluded}
    for contact in ordered:
        if contact.id not in argued and contact.full_name not in named:
            out.excluded.append({
                "name": contact.full_name,
                "reason": (
                    "the model returned nothing for them, twice — this is a provider failure, "
                    "not a decision about this person. Try again, or lower the effort for "
                    "strategy_synthesis if it keeps happening"
                ),
            })
    if not accepted:
        out.note = "no usable strategy came back"
        return out

    rules_service.assert_differentiated({c.id: p.problem_hypothesis for c, p, _ in accepted})

    await session.execute(
        update(Strategy)
        .where(
            Strategy.campaign_id == campaign.id,
            Strategy.account_id == account.id,
            Strategy.status != "superseded",
        )
        .values(status="superseded")
        .execution_options(synchronize_session="fetch")
    )
    # Anyone this build leaves out must not keep pointing at the argument it replaces.
    sequences_of: dict = {}
    for sequence, person in group:
        sequence.thread_id = None
        sequences_of.setdefault(person.id, []).append(sequence)
    version = (
        await session.scalar(select(func.max(Strategy.version)).where(Strategy.account_id == account.id))
        or 0
    ) + 1
    qual = await icp_scores.company_qualification(session, account.id)
    strategy = Strategy(
        account_id=account.id, campaign_id=campaign.id, service_id=t.service.id,
        icp_profile_id=t.icp_version.icp_profile_id, qualification_id=qual.id if qual else None,
        version=version, status="draft",
    )
    session.add(strategy)
    await session.flush()
    for cell in cells:
        session.add(PersonaServiceScore(
            strategy_id=strategy.id, contact_id=cell.contact_id, service_id=cell.service_id,
            weight=cell.weight, rationale=cell.rationale, evidence_ids=cell.evidence_ids or None,
        ))

    positions = {item["contact_id"]: item for item in plan}
    for contact, proposed, cited in accepted:
        item = positions[contact.id]
        thread = StrategyThread(
            strategy_id=strategy.id, contact_id=contact.id, service_id=t.service.id,
            weight=decisions[contact.id].weight, rank=item["rank"], thread_status=item["thread_status"],
            problem_hypothesis=proposed.problem_hypothesis, trigger_summary=proposed.trigger_summary,
            trigger_signal_ids=cited, positioning=proposed.positioning,
            channel_sequence=list(proposed.channel_sequence), cta=proposed.cta,
            avoid_list=list(proposed.avoid_list) or None, confidence=proposed.confidence,
            start_offset_days=item["start_offset_days"],
            chosen_by_rep=item["chosen_by_rep"], without_live_trigger=not cited,
        )
        session.add(thread)
        await session.flush()
        for sequence in sequences_of.get(contact.id, []):
            sequence.thread_id = thread.id
        out.pursued.append(contact.full_name)
        if item["chosen_by_rep"]:
            out.overridden.append(contact.full_name)
        if not cited:
            out.without_trigger.append(contact.full_name)

    out.built = True
    out.version = version
    log.info(
        "campaign_strategy.built campaign=%s account=%s version=%s pursued=%d excluded=%d",
        campaign.id, account.id, version, len(out.pursued), len(out.excluded),
    )
    return out


async def person_detail(session: AsyncSession, campaign: OutreachCampaign, contact_id) -> dict:
    """One person in the campaign: the company's score for its ICP, the rules'
    default, and the strategy argued for them — with the versions before it."""
    from dataclasses import asdict

    view = await people_view(session, campaign)
    row = next((p for p in view["people"] if p["contact_id"] == contact_id), None)
    if row is None:
        raise NotReadyError("this person is not in the campaign")
    score = await icp_scores.score_for(session, row["account_id"], campaign.icp_profile_id)

    history = (
        await session.execute(
            select(Strategy, StrategyThread)
            .outerjoin(
                StrategyThread,
                (StrategyThread.strategy_id == Strategy.id) & (StrategyThread.contact_id == contact_id),
            )
            .where(Strategy.campaign_id == campaign.id, Strategy.account_id == row["account_id"])
            .order_by(Strategy.version.desc())
        )
    ).all()
    current = next((th for s, th in history if s.status != "superseded"), None)

    signals: list[dict] = []
    if current is not None and current.trigger_signal_ids:
        ids = []
        for value in current.trigger_signal_ids:
            try:
                ids.append(uuid.UUID(str(value)))
            except ValueError:
                continue
        for s in (await session.execute(select(Signal).where(Signal.id.in_(ids)))).scalars():
            signals.append({
                "id": str(s.id),
                "summary": s.summary,
                "observed_at": s.observed_at.isoformat() if s.observed_at else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            })

    return {
        "person": row,
        "service_code": view["service_code"],
        "icp_name": view["icp_name"],
        "icp_version": view["icp_version"],
        "threshold": view["threshold"],
        "cap": view["cap"],
        "score": asdict(score) if score else None,
        "strategy": None if current is None else {
            "problem_hypothesis": current.problem_hypothesis,
            "trigger_summary": current.trigger_summary,
            "positioning": current.positioning,
            "channel_sequence": list(current.channel_sequence or []),
            "cta": current.cta,
            "avoid_list": list(current.avoid_list or []),
            "confidence": float(current.confidence) if current.confidence is not None else None,
            "thread_status": current.thread_status,
            "rank": current.rank,
            "start_offset_days": current.start_offset_days,
            "weight": float(current.weight),
            "chosen_by_rep": current.chosen_by_rep,
            "without_live_trigger": current.without_live_trigger,
        },
        "trigger_signals": signals,
        "versions": [
            {
                "version": s.version,
                "status": s.status,
                "built_at": s.created_at.isoformat() if s.created_at else None,
                "argued_for_this_person": th is not None,
            }
            for s, th in history
        ],
    }
