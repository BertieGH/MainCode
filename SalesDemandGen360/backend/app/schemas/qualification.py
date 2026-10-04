"""The qualification contract.

The model assesses each dimension against cited evidence. It does **not**
compute the roll-up — that is deterministic Python over a versioned
`scoring_config`, which is what makes re-scoring the whole book a batch job
instead of thousands of calls.

The awkward case this contract has to get right is a dimension with genuinely
nothing behind it. Engagement on an account we have never contacted is not a
gap in the research and not a low-confidence guess: it is a known, correct
zero. Requiring evidence everywhere would push the model to manufacture a
citation for it, which is the one failure mode the whole system is built to
avoid. So absence is declarable — but it must be *declared*, and it pins the
score to zero rather than leaving it free.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DIMENSIONS = ("fit", "opportunity", "buyer", "commercial", "intent", "engagement")

Dimension = Literal["fit", "opportunity", "buyer", "commercial", "intent", "engagement"]
Basis = Literal["evidence", "no_evidence"]


class DimensionAssessment(BaseModel):
    """One dimension, judged against what we actually found."""

    model_config = ConfigDict(extra="forbid")

    dimension: Dimension
    score: Annotated[float, Field(ge=0, le=100)]
    reason: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    basis: Basis = "evidence"

    @model_validator(mode="after")
    def _basis_matches_the_citations(self) -> DimensionAssessment:
        if self.basis == "evidence":
            if not self.evidence_ids:
                raise ValueError(
                    f"{self.dimension}: an evidence-based assessment must cite at least one "
                    "evidence id. If there is genuinely nothing, declare basis='no_evidence'."
                )
            return self

        # basis == "no_evidence"
        if self.evidence_ids:
            raise ValueError(
                f"{self.dimension}: basis='no_evidence' cannot carry citations"
            )
        if self.score != 0:
            raise ValueError(
                f"{self.dimension}: basis='no_evidence' must score 0, got {self.score}. "
                "A score above zero is a claim, and a claim needs a source."
            )
        return self


class DimensionAssessments(BaseModel):
    """All six. A partial set cannot produce a comparable priority score."""

    model_config = ConfigDict(extra="forbid")

    assessments: list[DimensionAssessment] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def _exactly_the_six(self) -> DimensionAssessments:
        seen = [a.dimension for a in self.assessments]
        missing = set(DIMENSIONS) - set(seen)
        if missing:
            raise ValueError(f"missing dimensions: {sorted(missing)}")
        if len(set(seen)) != len(seen):
            raise ValueError("a dimension was assessed twice")
        return self

    def by_dimension(self) -> dict[str, DimensionAssessment]:
        return {a.dimension: a for a in self.assessments}


class DimensionResult(BaseModel):
    """A stored assessment plus what the maths made of it."""

    dimension: str
    score: float
    weight: float
    #: score × effective weight, before normalisation to 0–100.
    contribution: float
    reason: str
    evidence_ids: list[uuid.UUID] = Field(default_factory=list)
    basis: str = "evidence"


class QualificationResult(BaseModel):
    """The deterministic output. No LLM was consulted to produce any of this."""

    priority_score: float
    priority_band: str
    dimensions: list[DimensionResult]
    scoring_config_version: int
    #: The industry whose multipliers were applied, as written on the account.
    #: Stored unnormalised so a rep reads what the row says; the lookup that
    #: used it was done on the normalised key.
    industry: str | None = None
    #: The size band whose multipliers were applied — derived from headcount,
    #: never classified. `unknown` carries no multipliers.
    size_band: str | None = None
    man: dict[str, str] | None = None

    def score_for(self, dimension: str) -> float:
        return next(d.score for d in self.dimensions if d.dimension == dimension)

    def as_reasons(self) -> dict:
        """The JSONB written to `qualification.reasons`.

        This is the re-scoring input, so it stores the *assessment* — score,
        reason, citations, basis — and not the weighted contribution, which is
        a function of a config version that is about to change.
        """
        return {
            d.dimension: {
                "score": d.score,
                "reason": d.reason,
                "evidence_ids": [str(e) for e in d.evidence_ids],
                "basis": d.basis,
            }
            for d in self.dimensions
        }
