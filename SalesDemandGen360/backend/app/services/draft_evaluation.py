"""Evaluate one person's drafts before a rep approves them (`docs/18`).

Approval reads flagged sequences individually and **samples** the rest, and
"flagged" leaned on an evaluation that was never run: a missing verdict was
read as `pass`, so a set of drafts could be approved on a sample with no
content check at all, under a screen saying every thread had passed.

This runs when drafts are saved for approval — the words being approved — in
two layers:

* **Rules**, deterministic and free: every cited signal still live, every
  cited proof point approved, no empty step. A failure here stands whatever
  the model says.
* **The `evaluation` stage**, reading the drafts against the angle they were
  written from, the cadence, and the opening lines of everyone else at the
  same company in this campaign — faithfulness, claims beyond the evidence,
  fit to each step, and two people getting the same message.

The model being unavailable is not a pass: the rules' verdict is stored if
they found something, and otherwise nothing is — and approval reads "never
evaluated" as a reason to read the thread individually.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Contact
from app.models.config import ProofPoint
from app.models.governance import Evaluation
from app.models.campaign import OutreachSequence
from app.models.strategy import StrategyAngle, StrategyThread

log = logging.getLogger(__name__)

#: What the model is asked to judge. Kept to things a rep can act on.
CRITERIA = [
    "faithful_to_angle: the drafts argue the pitched angle — its problem, its why-now and its ask — "
    "rather than drifting to another argument",
    "no_unsupported_claims: every factual claim about the prospect is backed by a cited signal, "
    "and every claim about results is backed by a cited approved proof point",
    "step_fit: each step's words suit its channel and its place in the cadence (a LinkedIn message "
    "reads like one; a follow-up does not assume an earlier step was read)",
    "differentiated: the opening is materially different from the openings written for the other "
    "people at this company in this campaign",
    "register: professional and specific, no hype, no invented urgency",
]

SEVERITY = {"pass": 0, "warn": 1, "fail": 2}


async def evaluate(session: AsyncSession, sequence: OutreachSequence, *, judge=None) -> Evaluation | None:
    """Evaluate this person's current drafts and store the verdict. Returns it,
    or None when neither layer produced one."""
    from app.services import campaign_drafts, context as context_service

    contact = await session.get(Contact, sequence.contact_id)
    thread = await session.get(StrategyThread, sequence.thread_id) if sequence.thread_id else None
    arc = await campaign_drafts.arc_of(session, sequence.id)
    if contact is None or thread is None or not arc:
        return None

    live = {str(s.id) for s in await context_service.live_signals(session, contact.account_id)}
    cited_proof = {str(p) for _, d in arc if d for p in (d.cited_proof_point_ids or [])}
    approved = {
        str(p.id)
        for p in (
            await session.execute(
                select(ProofPoint).where(
                    ProofPoint.id.in_([uuid.UUID(x) for x in cited_proof]), ProofPoint.is_approved.is_(True)
                )
            )
        ).scalars()
    } if cited_proof else set()

    # --- rules -----------------------------------------------------------
    issues: list[dict] = []
    for touch, draft in arc:
        where = f"step {touch.step_no}"
        if draft is None or not (draft.body or "").strip():
            issues.append({"code": "empty_step", "severity": "fail", "locus": where,
                           "detail": f"{where} has no words — it would send whatever the lead already holds."})
            continue
        dead = [s for s in (draft.cited_signal_ids or []) if str(s) not in live]
        if dead:
            issues.append({"code": "stale_trigger", "severity": "fail", "locus": where,
                           "detail": f"{where} cites {len(dead)} signal(s) that are no longer live — rewrite it on a current one."})
        bad = [p for p in (draft.cited_proof_point_ids or []) if str(p) not in approved]
        if bad:
            issues.append({"code": "unapproved_proof", "severity": "fail", "locus": where,
                           "detail": f"{where} cites proof that is not approved (invariant 8)."})
    rules_verdict = "fail" if any(i["severity"] == "fail" for i in issues) else "pass"

    # --- the model -------------------------------------------------------
    angle = (
        await session.execute(
            select(StrategyAngle).where(StrategyAngle.thread_id == thread.id, StrategyAngle.is_selected.is_(True))
        )
    ).scalar_one_or_none()
    others = await _other_openings(session, sequence, contact)
    # What the drafts were allowed to argue from. Without it the evaluator
    # judged support by counts alone and failed a draft for citing an
    # acquisition that *was* a live signal (live rerun, `docs/18`).
    from app.services import stages, strategy_context

    evidence = await strategy_context.signal_brief(
        session, account_id=contact.account_id, contact_id=contact.id, icp_version=None,
        cited={str(s) for _, d in arc if d for s in (d.cited_signal_ids or [])},
    )
    proof_rows = (
        await session.execute(select(ProofPoint).where(ProofPoint.id.in_([uuid.UUID(x) for x in approved])))
    ).scalars().all() if approved else []
    subject = {
        "person": {"title": contact.title, "seniority": contact.seniority, "buying_role": contact.buying_role},
        "pitched_angle": {
            "angle": angle.angle if angle else None,
            "problem_hypothesis": thread.problem_hypothesis,
            "why_now": thread.trigger_summary,
            "positioning": thread.positioning,
            "ask": thread.cta,
            "avoid": list(thread.avoid_list or []),
        },
        "touches": [
            {"step": t.step_no, "channel": t.channel, "subject": d.subject if d else None,
             "body": d.body if d else None,
             "cites_signals": len((d.cited_signal_ids or []) if d else []),
             "cites_proof": len((d.cited_proof_point_ids or []) if d else [])}
            for t, d in arc
        ],
        "other_openings_at_this_company": others,
        "live_signals": [
            {k: s[k] for k in ("signal_id", "signal_rank", "is_trigger", "type", "summary", "business_implication", "age_days")}
            for s in evidence
        ],
        "cited_proof": [{"id": str(p.id), "title": p.title, "body": p.body, "metrics": p.metrics or {}} for p in proof_rows],
        "company_profile": stages._profile_facts(await session.get(Account, contact.account_id)),
    }
    model_verdict, scores, model_name = None, None, None
    try:
        from app.services import stages

        with stages.attributed(
            account_id=contact.account_id, contact_id=contact.id,
            campaign_id=sequence.campaign_id, scope="campaign",
        ):
            result = await (judge or _judge)(session, subject)
        parsed = result.parsed
        model_verdict, scores = parsed.verdict, dict(parsed.scores or {})
        model_name = getattr(result, "model", None)
        issues += [i.model_dump(mode="json") for i in parsed.issues]
    except Exception as exc:  # noqa: BLE001 — unavailable is "not evaluated", never "passed"
        log.warning("draft_evaluation.model_unavailable sequence=%s err=%s", sequence.id, exc)

    if model_verdict is None and rules_verdict == "pass":
        return None
    verdict = max([rules_verdict, model_verdict or "pass"], key=SEVERITY.__getitem__)
    if verdict != "pass" and not issues:  # a non-pass must say what (the table enforces it)
        issues.append({"code": "unspecified", "severity": verdict, "detail": "The evaluator flagged this without saying why — read it."})
    row = Evaluation(
        subject_type="outreach_sequence", subject_id=sequence.id,
        method="hybrid" if model_verdict is not None else "rules",
        verdict=verdict, scores=scores or None, issues=issues or None,
        evaluator_version=model_name or "rules",
    )
    session.add(row)
    await session.flush()
    return row


async def _judge(session: AsyncSession, subject: dict):
    from app.services import stages

    return await stages.evaluate(
        session, subject_type="outreach_sequence", subject=subject, criteria=CRITERIA,
    )


async def _other_openings(session: AsyncSession, sequence: OutreachSequence, contact: Contact) -> list[dict]:
    """The first step written for everyone else at this company in this campaign."""
    from app.services import campaign_drafts

    rows = (
        await session.execute(
            select(OutreachSequence, Contact)
            .join(Contact, Contact.id == OutreachSequence.contact_id)
            .where(
                OutreachSequence.campaign_id == sequence.campaign_id,
                Contact.account_id == contact.account_id,
                OutreachSequence.id != sequence.id,
            )
        )
    ).all()
    out = []
    for other, person in rows:
        arc = await campaign_drafts.arc_of(session, other.id)
        if arc and arc[0][1] is not None:
            out.append({"title": person.title, "opening": arc[0][1].body})
    return out


async def latest_verdict(session: AsyncSession, sequence_id: uuid.UUID) -> tuple[str | None, list]:
    """The newest verdict and its issues, or (None, []) if never evaluated."""
    row = (
        await session.execute(
            select(Evaluation)
            .where(Evaluation.subject_type == "outreach_sequence", Evaluation.subject_id == sequence_id)
            .order_by(Evaluation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return (row.verdict, list(row.issues or [])) if row else (None, [])
