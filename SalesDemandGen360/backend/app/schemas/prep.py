"""The sales-prep contract.

Phase 12 is held, so nothing calls this yet — but `llm_config` already names
`SalesPrepPayload` as the `sales_prep` scenario's output contract, and a
scenario whose contract does not exist is a stage that fails at its first call
rather than at import. The contract is cheap; discovering it is missing while a
rep waits for a brief before a meeting is not.

Two shape decisions come straight from `docs/08 §12`, and both are about *when*
prep is generated:

* Prep is written **one contact at a time, on demand**, never in batch and
  never in advance. A brief written on day 0 for a call on day 18 argues from a
  picture that predates the whole conversation.
* It must state **what was already sent and what came back**, because the rep's
  first job on the call is not to repeat the sequence at the person.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PitchStructure(BaseModel):
    """Situation → Complication → Angle → Proof → Ask.

    Fixed five parts rather than free prose: a rep skims this ninety seconds
    before a call, and a paragraph does not survive that reading.
    """

    model_config = ConfigDict(extra="forbid")

    situation: str = Field(min_length=1)
    complication: str = Field(min_length=1)
    angle: str = Field(min_length=1)
    proof: str = Field(min_length=1)
    ask: str = Field(min_length=1)
    #: Only `is_approved` proof points may be cited. Blocked at generation.
    proof_point_ids: list[str] = Field(default_factory=list)


class DiscoveryQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    #: What the answer would tell us — so a rep can drop it if time is short.
    listening_for: str = Field(min_length=1)
    dimension: Literal[
        "fit", "opportunity", "buyer", "commercial", "intent", "engagement"
    ] | None = None


class Objection(BaseModel):
    """An objection with its pre-empt, not a rebuttal to read out."""

    model_config = ConfigDict(extra="forbid")

    objection: str = Field(min_length=1)
    pre_empt: str = Field(min_length=1)
    likelihood: Literal["low", "medium", "high"] = "medium"


class SalesPrepPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    elevator_pitch: str = Field(min_length=1)
    pitch_structure: PitchStructure
    discovery_questions: list[DiscoveryQuestion] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)
    #: What this account has already been told, in the rep's words. Generated
    #: from the sent touches, so the call does not restate the sequence.
    already_said: list[str] = Field(default_factory=list)
    #: What they said back, if anything.
    their_replies: list[str] = Field(default_factory=list)
    #: Named gaps a rep should know they are walking in with.
    open_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _a_brief_asks_something(self) -> SalesPrepPayload:
        if not self.discovery_questions:
            raise ValueError(
                "a prep brief with no discovery questions is a pitch script; "
                "the call exists to learn something"
            )
        return self
