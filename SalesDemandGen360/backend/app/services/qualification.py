"""Qualification: read the signals, judge six dimensions, score in Python.

The order is the point. A **context version** is written first, because a
strategy, a draft and an approval all cite one and it must not change under
them. The model then judges the six dimensions against that context and the
evidence — and is never asked for a priority score. The roll-up is deterministic
arithmetic over a versioned `scoring_config` (`docs/01` invariant 7), which is
what makes re-scoring the whole book free.

**A citation that does not resolve costs its dimension, not the account.** The
ids are checked against evidence we actually hold; unknown ones are stripped,
and a dimension left standing on nothing scores 0 and is marked `unsupported` —
deliberately a different word from `no_evidence`. "Nobody has contacted them"
and "the model claimed this and could not back it" are different facts, and
collapsing them would hide a drifting prompt behind an honest-looking zero.

Refusing the whole qualification was the alternative. It was rejected because
it blocks nothing useful: an unscored account still queues, still promotes, and
now sorts nowhere — whereas a scored one carries its own penalty, proportional
to how much of it turned out to be unsupported.

**Fit, buyer and engagement are computed, not judged** — fit and buyer whenever
the list's ICPs are known, engagement always. See `services/fit.py` and
`services/dimensions.py`. The model is still asked for all six, since the
contract is six; its view of those stands only where the facts are unavailable.

**Opportunity, commercial and intent stay judgements, held steady.** They land on
a five-step scale, and when nothing the model would be shown has changed since a
previous qualification, that judgement is kept and the model is not asked.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Contact
from app.models.campaign import OutreachSequence
from app.models.config import ScoringConfig
from app.models.content import Touch
from app.models.context import AccountContext, Qualification
from app.models.governance import Evaluation
from app.models.signal import Evidence, signal_evidence
from app.models.strategy import StrategyThread
from app.schemas.qualification import DIMENSIONS, DimensionAssessments
from app.services import context as context_service
from app.services import dimensions
from app.services import fit as fit_service
from app.services import scoring, sizing

log = logging.getLogger(__name__)

#: How much of an account's evidence the assessment is shown. Newest first,
#: and the same cap extraction uses: a judgement is about what is true now.
EVIDENCE_FOR_ASSESSMENT = 80


@dataclass
class QualificationOutcome:
    """What qualifying one account came to."""

    qualified: bool = False
    #: Why not, when not — shown to the rep rather than inferred from a zero.
    reason: str | None = None
    priority_score: float | None = None
    priority_band: str | None = None
    context_version: int | None = None
    qualification_id: uuid.UUID | None = None
    #: Dimensions whose citations did not resolve: scored 0, marked, and named.
    unsupported: tuple[str, ...] = ()
    stripped_citations: int = 0
    #: The narrative overlay is optional. Its failure is recorded, not raised:
    #: the six dimensions can still be judged from the signal list itself.
    narrative_failed: str | None = None
    themes_dropped: int = 0
    #: Set when nothing the model would be shown had changed, so the judged
    #: dimensions were carried from this earlier qualification unasked.
    reused_from: uuid.UUID | None = None


def resolve_citations(
    cited: list[str],
    held: set[str],
    backing: dict[str, list[str]] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Resolve one dimension's citations to evidence we hold.

    Returns the evidence ids kept, the signal ids that were resolved through
    their evidence, and the ids that resolved to nothing.

    The middle case exists because of what the model is shown. The context
    lists signals by `id` and a narrative theme cites them by `signal_ids`, and
    the model copies those into `evidence_ids`: BlueWave's intent was stripped
    to zero for citing its own public-focus theme. A signal of this account's
    context is itself backed by evidence (invariant 1), so resolving it to that
    evidence keeps the citation honest — every id that survives is still an
    evidence row. Only signals in `backing` resolve: one from another account,
    or one no longer live, is not in it and is stripped like any unknown id.
    """
    kept: list[str] = []
    via_signal: list[str] = []
    unknown: list[str] = []
    for cid in cited:
        if cid in held:
            kept.append(cid)
            continue
        behind = [e for e in (backing or {}).get(cid, []) if e in held]
        if behind:
            via_signal.append(cid)
            kept.extend(behind)
        else:
            unknown.append(cid)
    return list(dict.fromkeys(kept)), via_signal, unknown


def guard(
    assessments: DimensionAssessments,
    held: set[str],
    backing: dict[str, list[str]] | None = None,
) -> tuple[dict, tuple[str, ...], int]:
    """Strip citations we do not hold; mark what is left standing on nothing.

    `backing` maps the context's signal ids to their evidence — see
    `resolve_citations`.
    """
    raw: dict[str, dict] = {}
    unsupported: list[str] = []
    stripped = 0
    for a in assessments.assessments:
        keep, _, unknown = resolve_citations(a.evidence_ids, held, backing)
        stripped += len(unknown)
        basis, score = a.basis, a.score
        if a.basis == "evidence" and not keep:
            basis, score = "unsupported", 0.0
            unsupported.append(a.dimension)
        raw[a.dimension] = {
            "score": score,
            "reason": a.reason,
            "evidence_ids": keep,
            "basis": basis,
        }
    return raw, tuple(unsupported), stripped


def keep_known_themes(payload, signal_ids: set[str]) -> tuple[dict, int]:
    """The overlay, minus any theme citing a signal that is not in the context.

    The same rule extraction applies to evidence: an overlay may organise the
    facts already there and may not introduce one.
    """
    data = payload.model_dump(mode="json")
    themes = data.get("themes", []) or []
    kept = [t for t in themes if all(i in signal_ids for i in t.get("signal_ids", []))]
    data["themes"] = kept
    return data, len(themes) - len(kept)


async def run_qualification(
    session: AsyncSession,
    *,
    account: Account,
    run_id: uuid.UUID | None = None,
    assess,
    narrate=None,
    today: date | None = None,
    icps: Sequence[tuple[str, dict]] = (),
    prompt_version: str | None = None,
) -> QualificationOutcome:
    """Qualify one account. `assess` and `narrate` are injected, as the
    research runners are, so the ordering and the guard are testable without a
    model call."""
    signals = await context_service.live_signals(session, account.id, today=today)
    if not signals:
        # Nothing to judge. Scoring zeros here would rank an unresearched
        # account against a judged one, which is worse than saying so.
        #
        # "Nothing found" and "everything found has aged out" are different
        # facts about an account, and only the second one means research
        # worked. Said apart, because they send a rep somewhere different.
        from app.models.signal import Signal

        newest = (
            await session.execute(
                select(func.max(Signal.observed_at)).where(Signal.account_id == account.id)
            )
        ).scalar()
        if newest is not None:
            return QualificationOutcome(
                reason=(
                    f"every signal has expired — the newest fact is from "
                    f"{newest:%b %Y}. Nothing current to judge"
                )
            )
        return QualificationOutcome(
            reason="no live signals yet — research and extraction come first"
        )

    outcome = QualificationOutcome()
    narrative = None
    if narrate is not None:
        try:
            payload = await narrate(account, signals, await _previous_context(session, account.id))
            narrative, outcome.themes_dropped = keep_known_themes(
                payload, {str(s.id) for s in signals}
            )
        except Exception as exc:  # noqa: BLE001 — a reading, not a fact
            outcome.narrative_failed = f"{type(exc).__name__}: {exc}"
            log.warning("qualification.narrative_failed account=%s err=%s", account.id, exc)

    ctx = await context_service.build_context(
        session, account_id=account.id, run_id=run_id, today=today, narrative=narrative
    )
    outcome.context_version = ctx.version

    evidence = list(
        (
            await session.execute(
                select(Evidence)
                .where(Evidence.account_id == account.id)
                .order_by(Evidence.retrieved_at.desc())
                .limit(EVIDENCE_FOR_ASSESSMENT)
            )
        ).scalars()
    )
    held = {str(e.id) for e in evidence}
    # Everything the model would be shown, and how it would be asked. Only
    # computed when the caller says how it asks (`prompt_version`); a test's
    # stand-in assessor has no prompt to fingerprint.
    inputs = (
        dimensions.inputs_fingerprint(
            prompt=prompt_version,
            evidence_ids=held,
            signal_ids={str(s.id) for s in signals},
            account=_facts(account),
        )
        if prompt_version is not None
        else None
    )
    previous = await _judged_on_the_same_inputs(session, account.id, inputs) if inputs else None

    via_signal: dict[str, list[str]] = {}
    unknown_ids: dict[str, list[str]] = {}
    if previous is not None:
        # Nothing the model would be shown has changed, so the last judgement
        # stands and nothing is asked. Asking again is how BlueWave's
        # opportunity read 70, 80 and 85 over the same evidence.
        raw = {d: dict(previous.reasons[d]) for d in DIMENSIONS}
        unsupported, stripped = (), 0
        outcome.reused_from = previous.id
    else:
        assessments = await assess(account, ctx, evidence)
        # The evidence behind each signal this context lists, for a citation
        # that names the signal rather than its evidence.
        backing: dict[str, list[str]] = {}
        if signals:
            rows = await session.execute(
                select(signal_evidence.c.signal_id, signal_evidence.c.evidence_id).where(
                    signal_evidence.c.signal_id.in_([s.id for s in signals])
                )
            )
            for signal_id, evidence_id in rows.all():
                backing.setdefault(str(signal_id), []).append(str(evidence_id))
        raw, unsupported, stripped = guard(assessments, held, backing)

        # Recorded per dimension, so the next "unsupported" can be diagnosed
        # from the evaluation row instead of by rerunning the model and hoping.
        for a in assessments.assessments:
            _, via, unknown = resolve_citations(a.evidence_ids, held, backing)
            if via:
                via_signal[a.dimension] = via
            if unknown:
                unknown_ids[a.dimension] = unknown

    # The dimensions that are facts: computed fresh every time from the
    # account, its contacts and its outreach, whether or not the judgement was
    # kept — a contact enriched since the last run changes buyer on this one.
    replaced: dict[str, dict] = {}
    computed_fit = fit_service.best(account, icps)
    if computed_fit is not None:
        replaced["fit"] = computed_fit.as_assessment()
    if icps:
        contacts = list(
            (
                await session.execute(select(Contact).where(Contact.account_id == account.id))
            ).scalars()
        )
        buyer = dimensions.best_buyer(contacts, icps)
        if buyer is not None:
            replaced["buyer"] = buyer.as_assessment()
    replaced["engagement"] = (await _engagement(session, account.id)).as_assessment()

    for dim, value in replaced.items():
        # A replaced judgement is nothing this qualification rests on: its bad
        # citations are not faults in it, and it is not unsupported.
        stripped -= len(unknown_ids.pop(dim, []))
        via_signal.pop(dim, None)
        raw[dim] = value
    unsupported = tuple(d for d in unsupported if d not in replaced)

    # What is still judged lands on the five-step scale. The prompt asks for
    # the steps; this makes it true whatever came back.
    for dim in DIMENSIONS:
        if dim not in replaced and raw[dim].get("basis") == "evidence":
            raw[dim]["score"] = dimensions.to_level(float(raw[dim]["score"]))
    outcome.unsupported, outcome.stripped_citations = unsupported, stripped

    config = (
        await session.execute(select(ScoringConfig).where(ScoringConfig.is_active.is_(True)))
    ).scalar_one()
    result = scoring.score(
        raw,
        config=config,
        industry=account.industry,
        size_band=sizing.band_for(account.employee_count),
    )
    row = await context_service.store_qualification(
        session, account_id=account.id, result=result, context_id=ctx.id, run_id=run_id,
        inputs=inputs, reused_from=outcome.reused_from,
    )

    # The pipeline state, not a verdict: `qualified` means it has been judged,
    # whatever the band. Disqualifying stays a rep's decision.
    if account.status != "disqualified":
        account.status = "qualified"

    if unsupported or stripped or via_signal:
        issues = [
            {"dimension": d, "reason": "no citation resolved; scored 0 as unsupported"}
            for d in unsupported
        ] or (
            [{"reason": f"{stripped} citation(s) did not resolve and were stripped"}]
            if stripped
            else []
        )
        issues += [
            {"dimension": d, "reason": "these ids resolved to nothing", "ids": ids}
            for d, ids in unknown_ids.items()
        ]
        # Not a fault in this qualification — every id still reached evidence —
        # but a prompt citing signals instead of evidence is drift worth seeing.
        issues += [
            {
                "dimension": d,
                "reason": "cited signal ids as evidence; resolved through the signal's evidence",
                "ids": ids,
            }
            for d, ids in via_signal.items()
        ]
        session.add(
            Evaluation(
                subject_type="qualification",
                subject_id=row.id,
                method="rules",
                verdict="fail" if len(unsupported) >= 6 else "warn",
                scores={
                    "unsupported_dimensions": len(unsupported),
                    "citations_stripped": stripped,
                    "citations_via_signal": sum(len(v) for v in via_signal.values()),
                },
                issues=issues,
                evaluator_version="qualification-guard-2",
            )
        )
    await session.flush()

    outcome.qualified = True
    outcome.priority_score = result.priority_score
    outcome.priority_band = result.priority_band
    outcome.qualification_id = row.id
    log.info(
        "qualification.done account=%s priority=%.2f band=%s unsupported=%d",
        account.id, result.priority_score, result.priority_band, len(unsupported),
    )
    return outcome


def _facts(account: Account) -> dict:
    """The account block the model is shown, for the input fingerprint."""
    return {
        key: getattr(account, key, None)
        for key in ("name", "domain", "industry", "employee_count", "hq_country", "hq_region")
    }


async def _judged_on_the_same_inputs(
    session: AsyncSession, account_id: uuid.UUID, inputs: str
) -> Qualification | None:
    """The latest qualification judged on exactly these inputs, if it can stand.

    One with an unsupported dimension is not carried forward: that judgement
    failed its citations, and keeping it would keep the failure until the
    evidence happened to change.
    """
    row = (
        (
            await session.execute(
                select(Qualification)
                .where(
                    Qualification.account_id == account_id,
                    Qualification.reasons["_inputs"].astext == inputs,
                )
                .order_by(Qualification.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    reasons = row.reasons or {}
    if any(not isinstance(reasons.get(d), dict) for d in DIMENSIONS):
        return None
    if any(reasons[d].get("basis") == "unsupported" for d in DIMENSIONS):
        return None
    return row


async def _engagement(session: AsyncSession, account_id: uuid.UUID) -> dimensions.Computed:
    """What outreach history says: touches sent to anyone here, and replies.

    A touch reaches an account through its sequence, the strategy thread it
    belongs to, and the contact that thread is for.
    """
    sent, last_sent, replies = (
        await session.execute(
            select(
                func.count(Touch.id).filter(Touch.status == "sent"),
                func.max(Touch.sent_at),
                func.count(Touch.id).filter(Touch.stop_reason == "reply_received"),
            )
            .select_from(Touch)
            .join(OutreachSequence, OutreachSequence.id == Touch.sequence_id)
            .join(StrategyThread, StrategyThread.id == OutreachSequence.thread_id)
            .join(Contact, Contact.id == StrategyThread.contact_id)
            .where(Contact.account_id == account_id)
        )
    ).one()
    return dimensions.assess_engagement(
        sent=int(sent or 0), last_sent=last_sent, replied=bool(replies)
    )


async def _previous_context(session: AsyncSession, account_id: uuid.UUID):
    version = (
        await session.execute(
            select(func.max(AccountContext.version)).where(
                AccountContext.account_id == account_id
            )
        )
    ).scalar()
    if version is None:
        return None
    return (
        await session.execute(
            select(AccountContext).where(
                AccountContext.account_id == account_id, AccountContext.version == version
            )
        )
    ).scalar_one_or_none()


def llm_qualifier(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    icps: Sequence[tuple[str, dict]] = (),
):
    """The real thing: the narrative overlay, then the six dimensions.

    `icps` are the list's ICPs as (name, definition). With them, fit is
    computed from the account's size, industry and country; without them the
    model's fit stands.
    """

    async def run(account: Account) -> QualificationOutcome:
        from app.services import llm, stages

        # How the assessment is asked, beyond the account's own evidence: the
        # prompt prefix (org, ICPs, services, approved proofs, the instructions)
        # and the model. A change to any of it is a reason to judge again.
        prefix = await stages.load_prefix(session, "qualification_assessment")
        config = await llm.stage_config(session, "qualification_assessment")
        version = dimensions.prompt_version(
            prefix.fingerprint(),
            [config.provider, config.model, config.effort, config.thinking_mode],
        )

        async def narrate(acc, signals, previous):
            result = await stages.read_context(
                session, account=acc, signals=signals, previous=previous
            )
            return result.parsed

        async def assess(acc, ctx, evidence):
            result = await stages.assess_dimensions(
                session, account=acc, context=ctx, evidence=evidence
            )
            return result.parsed

        return await run_qualification(
            session, account=account, run_id=run_id, assess=assess, narrate=narrate,
            icps=icps, prompt_version=version,
        )

    return run
