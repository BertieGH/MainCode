"""Building the versioned context, and storing a qualification against it.

`account_context` is the handoff contract between research and everything
downstream. It is immutable: a rebuild makes a new version rather than editing
the last one. That is not tidiness — a strategy, a draft and an approval all
point at a specific version, and rewriting it underneath them would leave an
approved message justified by a context that no longer says what it said.

There is deliberately no update function in this module.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context import AccountContext, Qualification
from app.models.signal import Signal
from app.schemas.qualification import QualificationResult

#: Bumped when the shape of `payload` changes, so a context built by older code
#: is recognisable as such rather than being silently misread.
BUILDER_VERSION = "1.0"


async def live_signals(
    session: AsyncSession, account_id: uuid.UUID, *, today: date | None = None
) -> list[Signal]:
    """Signals that still count, newest first.

    Expiry is read from the row rather than recomputed: `expires_at` was set
    from the type's TTL at the moment the signal was written, so a later TTL
    change does not retroactively revive or kill evidence-backed history.
    """
    today = today or date.today()
    rows = await session.execute(
        select(Signal)
        .where(
            Signal.account_id == account_id,
            Signal.superseded_by.is_(None),
        )
        .order_by(Signal.observed_at.desc())
    )
    return [
        s for s in rows.scalars() if s.expires_at is None or s.expires_at >= today
    ]


def build_payload(signals: list[Signal]) -> dict:
    """The compressed picture. Deterministic ordering, no timestamps.

    This ends up inside a prompt, so anything volatile in here costs the cache
    on every account — see `app/services/prompt.py`.
    """
    return {
        "signal_count": len(signals),
        "signals": [
            {
                "id": str(s.id),
                "type": s.signal_type,
                "scope": s.scope,
                "summary": s.summary,
                "business_implication": s.business_implication,
                "strength": s.strength,
                "confidence": float(s.confidence),
                "observed_at": s.observed_at.isoformat(),
                "is_hypothesis": s.is_hypothesis,
                "contact_id": str(s.contact_id) if s.contact_id else None,
            }
            # Sorted by a stable key, not by whatever order Postgres returned.
            for s in sorted(signals, key=lambda x: (x.observed_at, str(x.id)), reverse=True)
        ],
    }


async def build_context(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    today: date | None = None,
    narrative: dict | None = None,
) -> AccountContext:
    """Write the next version. Never touches the previous one.

    `narrative` is the model's reading, merged under its own key rather than
    mixed into the signal list: the deterministic half must stay reproducible
    from the database, and a reader has to be able to tell which half is which.
    It is passed in rather than fetched here so the version is written once,
    with the overlay already in it — a context edited after the fact would
    break the immutability every downstream artefact depends on.
    """
    signals = await live_signals(session, account_id, today=today)

    previous = (
        await session.execute(
            select(func.max(AccountContext.version)).where(
                AccountContext.account_id == account_id
            )
        )
    ).scalar()

    payload = build_payload(signals)
    if narrative:
        payload["narrative"] = narrative
    row = AccountContext(
        account_id=account_id,
        run_id=run_id,
        version=(previous or 0) + 1,
        parent_version=previous,
        payload=payload,
        signal_ids=[str(s.id) for s in signals],
        # A rough proxy, not a tokeniser call. It exists to catch a context
        # that has grown past what the next stage can be handed, and being out
        # by ten per cent does not change that answer.
        token_count=len(str(payload)) // 4,
        builder_version=BUILDER_VERSION,
    )
    session.add(row)
    await session.flush()
    return row


async def store_qualification(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    result: QualificationResult,
    context_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    inputs: str | None = None,
    reused_from: uuid.UUID | None = None,
) -> Qualification:
    """Persist a computed qualification, assessments and all.

    `reasons` carries the per-dimension assessments rather than the weighted
    contributions. Contributions are a function of the config version that is
    about to change; the assessments are what a re-score needs and what a rep
    reads when they ask why.
    """
    reasons = result.as_reasons()
    # Underscore-prefixed so they cannot collide with a dimension name; the
    # scorer strips these back out. Stored rather than re-derived because a
    # re-score has to reproduce the multipliers that were actually applied,
    # and the account's industry or headcount may have changed since.
    if result.industry:
        reasons["_industry"] = result.industry
    if result.size_band:
        reasons["_size_band"] = result.size_band
    # What the judged dimensions were judged on, so an unchanged account can
    # keep its judgement rather than be asked again — see `dimensions`.
    if inputs:
        reasons["_inputs"] = inputs
    if reused_from:
        reasons["_reused_from"] = str(reused_from)

    row = Qualification(
        account_id=account_id,
        context_id=context_id,
        run_id=run_id,
        fit_score=result.score_for("fit"),
        opportunity_score=result.score_for("opportunity"),
        buyer_score=result.score_for("buyer"),
        commercial_score=result.score_for("commercial"),
        intent_score=result.score_for("intent"),
        engagement_score=result.score_for("engagement"),
        priority_score=result.priority_score,
        priority_band=result.priority_band,
        reasons=reasons,
        scoring_config_version=result.scoring_config_version,
        man_money=(result.man or {}).get("money"),
        man_authority=(result.man or {}).get("authority"),
        man_need=(result.man or {}).get("need"),
    )
    session.add(row)
    await session.flush()
    return row
