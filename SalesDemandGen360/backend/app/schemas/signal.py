"""The extraction contract: what the model is allowed to return.

`evidence_ids` carrying `min_length=1` is the schema-level half of "no signal
without evidence". It is only half: the model can still name an id that does
not exist, so `app/services/extraction.py` resolves every id against the
`evidence` table and drops any signal citing an unknown one.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

STRENGTHS = ("low", "medium", "high")


class ExtractedSignal(BaseModel):
    """One conclusion the model drew, with the excerpts it rests on."""

    model_config = ConfigDict(extra="forbid")

    signal_type: str
    summary: str = Field(min_length=1)
    business_implication: str | None = None
    strength: Literal["low", "medium", "high"]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    observed_at: date
    #: Never empty. The other half of the invariant is the repository guard.
    evidence_ids: list[str] = Field(min_length=1)
    #: An interpretation the evidence supports but does not state outright.
    is_hypothesis: bool = False
    #: Required when the type is contact-scoped; rejected when it is not.
    contact_id: uuid.UUID | None = None


class SignalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: list[ExtractedSignal] = Field(default_factory=list)


def build_batch_model(type_keys: list[str]) -> type[BaseModel]:
    """Build the output schema from the *active* registry rows.

    The registry is configuration, so the set of legal `signal_type` values
    changes without a deploy — which means the output schema has to be built
    per run rather than hardcoded. Pinning it to a `Literal` is what stops the
    model inventing a type that no scoring weight and no research family knows
    about; such a signal would be stored, counted, and unexplainable.

    An empty registry yields a schema that permits no signals at all, which is
    the honest reading of "nothing is configured to be extracted".
    """
    if not type_keys:
        return create_model(
            "EmptySignalBatch",
            __config__=ConfigDict(extra="forbid"),
            signals=(list[None], Field(default_factory=list, max_length=0)),
        )

    constrained = create_model(
        "RegistrySignal",
        __base__=ExtractedSignal,
        signal_type=(Literal[tuple(type_keys)], ...),  # type: ignore[valid-type]
    )
    return create_model(
        "RegistrySignalBatch",
        __config__=ConfigDict(extra="forbid"),
        signals=(list[constrained], Field(default_factory=list)),  # type: ignore[valid-type]
    )


class DroppedSignal(BaseModel):
    """A signal the guard refused, kept for the evaluation log.

    Dropped signals are counted, not silently discarded: a rising drop rate is
    the earliest visible sign that an extraction prompt has drifted.
    """

    signal_type: str
    summary: str
    reason: str
    unknown_evidence_ids: list[str] = Field(default_factory=list)


class ExtractionOutcome(BaseModel):
    stored: int = 0
    dropped: list[DroppedSignal] = Field(default_factory=list)
    #: Conclusions we already hold: same type, same date, same citation. Counted
    #: rather than discarded silently — a run that produces only duplicates has
    #: read nothing new, and that is worth seeing.
    duplicates: int = 0

    @property
    def drop_rate(self) -> float:
        total = self.stored + len(self.dropped)
        return len(self.dropped) / total if total else 0.0
