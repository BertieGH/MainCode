"""The strategy contract: ranked ways in, for people already chosen.

Who is worth talking to is decided before this — by arithmetic over configured
weights in `app/services/strategy.py`, or by a rep's override. That decision is
a gate and nothing more: it never reaches the model (`docs/18`). This contract
covers what is left: for each person, **two or three angles** — complete,
different ways to pitch the service — ranked by the model, with the reason.

The app pitches the top-ranked angle unless a rep picks another. Every angle is
kept (`strategy_angle`), so the alternatives are there for the rep and for
sales prep.

All people at one company are argued in one call, because the top angles have
to differ (`assert_differentiated`) and a per-person call cannot see the others
to differ from them.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrategyAngle(BaseModel):
    """One complete way to pitch the service to one person."""

    model_config = ConfigDict(extra="forbid")

    #: A short name for the way in — what a rep sees in the list.
    angle: str = Field(min_length=1)
    #: What we think hurts, for this person. Labelled a hypothesis wherever it
    #: is shown, because it is our inference and not something they said.
    problem_hypothesis: str = Field(min_length=1)
    #: The moment, led by the best-ranked signal that fits this angle.
    why_now: str = Field(min_length=1)
    #: Must be live — checked by the service. Empty only for a person a rep
    #: allowed to approach without a signal.
    trigger_signal_ids: list[str] = Field(default_factory=list)
    #: The service framed against that problem, for this person.
    positioning: str = Field(min_length=1)
    #: Approved proof only, from the list given — checked by the service
    #: (invariant 8). Empty rather than a weak fit.
    proof_point_ids: list[str] = Field(default_factory=list)
    cta: str = Field(min_length=1)
    #: Claims or angles to stay off for this person.
    avoid: list[str] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5


class PersonAngles(BaseModel):
    """Every angle for one person, and which to pitch first."""

    model_config = ConfigDict(extra="forbid")

    contact_id: uuid.UUID
    #: Floored at one; the prompt asks for two or three. Unbounded above
    #: because `maxItems` reaches Gemini and comes back HTTP 400 (§52).
    angles: list[StrategyAngle] = Field(min_length=1)
    #: Indexes into `angles`, best first. Normalised by the service — an index
    #: out of range is dropped and an angle left out is appended — rather than
    #: refused, because a slightly malformed order is not a reason to lose
    #: the angles themselves.
    recommended_order: list[int] = Field(min_length=1)
    why_this_order: str = Field(min_length=1)

    def ordered(self) -> list[StrategyAngle]:
        """The angles, best first, every one exactly once."""
        seen: list[int] = []
        for i in self.recommended_order:
            if 0 <= i < len(self.angles) and i not in seen:
                seen.append(i)
        seen += [i for i in range(len(self.angles)) if i not in seen]
        return [self.angles[i] for i in seen]


class StrategyProposal(BaseModel):
    """Every chosen person at one company, argued together."""

    model_config = ConfigDict(extra="forbid")

    #: Floored at one so a model cannot satisfy the contract by returning no
    #: one — it did, repeatedly, writing everything into `account_angle`.
    people: list[PersonAngles] = Field(min_length=1)
    #: The one-sentence read of the company the angles hang off. Stored on the
    #: strategy and handed to drafting. Its length cannot be enforced here —
    #: `maxLength` draws the same HTTP 400 — so the prompt carries the rule.
    account_angle: str | None = None

    @model_validator(mode="after")
    def _one_entry_per_contact(self) -> StrategyProposal:
        """A person argued twice would become two threads and two sequences."""
        seen = [p.contact_id for p in self.people]
        if len(set(seen)) != len(seen):
            dupes = sorted({str(c) for c in seen if seen.count(c) > 1})
            raise ValueError(f"more than one entry for contact(s): {dupes}")
        return self
