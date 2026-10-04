"""Deterministic scoring. No LLM is reachable from this module, by design.

`docs/02 §6`: the model produces per-dimension evidence-grounded assessments;
the application computes the score. Keeping the arithmetic here is what makes
re-scoring the whole book after a weight change a cheap batch job rather than
thousands of calls — and what makes any given score explainable after the fact,
since the same inputs always produce the same number.

A note on the roll-up formula: `docs/02 §6` writes it as
`FIT + INTENT + TIMING + ACCESS`, which names four dimensions, two of which
("timing", "access") are not among the six the system actually carries. That
line predates the six-dimension model. The authoritative definition is
`scoring_config.dimension_weights`, which is validated to hold exactly the six
and to total 100.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import ScoringConfig
from app.models.context import Qualification
from app.schemas.qualification import (
    DIMENSIONS,
    DimensionAssessment,
    DimensionAssessments,
    DimensionResult,
    QualificationResult,
)


def _round2(value: float) -> float:
    """Half-up, not banker's rounding.

    Python rounds 62.5 to 62 and 63.5 to 64, so a threshold of 63 would admit
    one account and reject an identical one. NUMERIC(5,2) in the column means
    the stored value has to match what was computed here anyway.
    """
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def effective_weights(
    base: dict[str, float], *multiplier_sets: dict[str, float] | None
) -> dict[str, float]:
    """Apply every multiplier set on top of the base weights, renormalise once.

    Renormalisation is the point, and doing it *once at the end* is the reason
    this takes varargs rather than being called twice. The base weights total
    100 so a priority score reads as a percentage; multiplying one of them by
    1.4 breaks that total, and without renormalising an account would score
    higher than an identical one purely because its weights add up to more.
    Renormalising after each set separately would quietly favour whichever set
    was applied last. The multipliers change the *balance* between dimensions,
    never the total.

    Two sets today — industry and size band — and they compose by multiplying:
    a fintech ×1.2 on buyer that is also a large company ×1.3 on buyer ends up
    at ×1.56 before renormalisation. Neither axis is more specific than the
    other, so neither overrides.
    """
    weights = dict(base)
    for multipliers in multiplier_sets:
        if not multipliers:
            continue
        for dim, factor in multipliers.items():
            if dim in weights:
                weights[dim] = weights[dim] * float(factor)

    total = sum(weights.values())
    if total <= 0:
        raise ValueError("effective weights sum to zero; every dimension would be ignored")
    return {dim: (w / total) * 100 for dim, w in weights.items()}


def normalise_industry(value: str | None) -> str:
    """The join key for an industry string.

    `account.industry` is free text from whatever a CSV called its industry,
    sector or vertical column; ICP industries are strings somebody typed into a
    chip field. Nothing reconciles them, so "FinTech", "fintech " and "Fintech"
    would key three different multiplier rows and the mismatch would be silent
    — the account simply scores on base weights and nobody is told why.

    Case, surrounding space and repeated internal space only. Deliberately
    *not* a mapping: "Financial Services" does not become "fintech", because
    that is a judgement about two different words rather than two spellings of
    one. Aliases become worth building when account enrichment lands and Apollo
    brings its own taxonomy; guessing at them now would be inventing mappings
    for a vocabulary not yet in the system.
    """
    if not value:
        return ""
    return " ".join(value.split()).casefold()


def band_for(score: float, cutoffs: dict[str, float]) -> str:
    """Bands are inclusive at the cut-off.

    A `high` cut-off of 75 means 75 is High. Exclusive would make the number
    printed in Settings not the number that applies, which is the kind of
    off-by-one nobody finds by reading.
    """
    if score >= float(cutoffs["high"]):
        return "high"
    if score >= float(cutoffs["medium"]):
        return "medium"
    return "low"


def _man_view(scores: dict[str, float]) -> dict[str, str]:
    """The legacy MAN view, derived rather than authored.

    Money is the commercial read, Authority the buyer read, Need the
    opportunity read. It is a lens on the six, never a separate judgement —
    which is why nothing writes to it.
    """

    def label(v: float) -> str:
        return "strong" if v >= 70 else "moderate" if v >= 40 else "weak"

    return {
        "money": label(scores.get("commercial", 0.0)),
        "authority": label(scores.get("buyer", 0.0)),
        "need": label(scores.get("opportunity", 0.0)),
    }


def score(
    assessments: DimensionAssessments | dict[str, dict],
    *,
    config: ScoringConfig,
    industry: str | None = None,
    size_band: str | None = None,
) -> QualificationResult:
    """Compute the roll-up. Pure: same inputs, same output, every time.

    Accepts either a fresh `DimensionAssessments` from the model or the
    `reasons` dict read back off a stored qualification — the second form is
    what makes re-scoring possible without asking anything.
    """
    if isinstance(assessments, DimensionAssessments):
        by_dim: dict[str, DimensionAssessment] = assessments.by_dimension()
        raw = {
            d: {
                "score": a.score,
                "reason": a.reason,
                "evidence_ids": list(a.evidence_ids),
                "basis": a.basis,
            }
            for d, a in by_dim.items()
        }
    else:
        raw = assessments

    missing = set(DIMENSIONS) - set(raw)
    if missing:
        # A priority computed over five dimensions is not comparable to one
        # computed over six, and the whole book is ranked on this number.
        raise ValueError(f"cannot score without every dimension; missing {sorted(missing)}")

    base = {k: float(v) for k, v in config.dimension_weights.items()}
    absent = set(DIMENSIONS) - set(base)
    if absent:
        # A config predating the six-dimension validator reaches here and would
        # otherwise KeyError on the first missing weight, or — worse, if the
        # lookup were forgiving — score every account on the dimensions that
        # happen to be present and report it as a full assessment.
        raise ValueError(
            f"scoring_config v{config.version} is missing weights for {sorted(absent)}; "
            "it cannot produce a comparable priority score. Activate a config that "
            "carries all six dimensions."
        )
    # Normalised so "FinTech" from a spreadsheet and "Fintech" from the ICP
    # reach the same row. An account whose industry matches nothing gets no
    # multipliers and scores on the base weights — visibly, rather than on a
    # guessed mapping.
    industry_key = normalise_industry(industry)
    industry_mult = (config.industry_multipliers or {}).get(industry_key, {})
    # `unknown` deliberately carries no multipliers: it is the absence of a
    # headcount, not a size, and scoring it as one would be an invention.
    size_mult = (
        (config.size_multipliers or {}).get(size_band, {})
        if size_band and size_band != "unknown"
        else {}
    )
    weights = effective_weights(base, industry_mult, size_mult)

    results: list[DimensionResult] = []
    total = 0.0
    for dim in DIMENSIONS:
        entry = raw[dim]
        dim_score = float(entry["score"])
        weight = weights[dim]
        contribution = dim_score * weight / 100.0
        total += contribution
        results.append(
            DimensionResult(
                dimension=dim,
                score=_round2(dim_score),
                weight=_round2(weight),
                contribution=_round2(contribution),
                reason=entry.get("reason", ""),
                evidence_ids=[uuid.UUID(str(e)) for e in entry.get("evidence_ids", [])],
                basis=entry.get("basis", "evidence"),
            )
        )

    priority = _round2(total)
    scores = {r.dimension: r.score for r in results}

    return QualificationResult(
        priority_score=priority,
        priority_band=band_for(priority, config.band_cutoffs),
        dimensions=results,
        scoring_config_version=config.version,
        industry=industry,
        size_band=size_band,
        man=_man_view(scores) if config.man_view_enabled else None,
    )


async def rescore_book(
    session: AsyncSession, *, config: ScoringConfig | None = None
) -> int:
    """Recompute every stored qualification under the active config.

    Makes **zero LLM calls**: each row already carries the per-dimension
    assessments in `reasons`, and a weight change does not invalidate a
    judgement about what the evidence showed — only what that judgement is
    worth relative to the others.

    Rows are updated in place rather than versioned. The audit trail lives in
    `scoring_config_version`, which says exactly which maths produced the
    number now stored.
    """
    if config is None:
        config = (
            await session.execute(
                select(ScoringConfig).where(ScoringConfig.is_active.is_(True))
            )
        ).scalar_one()

    rows = list((await session.execute(select(Qualification))).scalars())
    for row in rows:
        stored = row.reasons or {}
        result = score(
            {k: v for k, v in row.reasons.items() if not k.startswith("_")},
            config=config,
            industry=stored.get("_industry"),
            size_band=stored.get("_size_band"),
        )
        for dim in DIMENSIONS:
            setattr(row, f"{dim}_score", result.score_for(dim))
        row.priority_score = result.priority_score
        row.priority_band = result.priority_band
        row.scoring_config_version = config.version
        if result.man:
            row.man_money = result.man["money"]
            row.man_authority = result.man["authority"]
            row.man_need = result.man["need"]

    await session.flush()
    return len(rows)
