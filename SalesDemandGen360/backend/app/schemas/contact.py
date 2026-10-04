"""The decision-maker contract.

The model proposes *who*; it never proposes *how to reach them*. Email and
phone come from Apollo or ContactOut with a verification status attached, and a
model-generated address that happens to look right is the one failure mode that
gets a domain blacklisted. So this contract has no email field at all — not an
optional one, not a discouraged one. Absence is the enforcement.

Everything here is `is_hypothesis=True` by construction: a title inferred from
a bio page is a guess about a buying role, and the strategy layer weights it
accordingly.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Seniority = Literal["c_level", "vp", "director", "manager", "ic", "unknown"]
BuyingRole = Literal[
    "economic_buyer", "technical_buyer", "champion", "influencer", "blocker"
]


class EnrichedContact(BaseModel):
    """One person at the account, as far as public sources show."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1)
    title: str | None = None
    seniority: Seniority = "unknown"
    #: The role they play in a purchase, which is not their title. A VP
    #: Engineering is usually the technical buyer and occasionally the blocker.
    buying_role: BuyingRole | None = None
    linkedin_url: str | None = None
    #: Where this person was found. Without it the row is an assertion.
    evidence_ids: list[str] = Field(min_length=1)
    #: How confident the model is that this person holds this role *now*.
    #: People change jobs and profile pages lag.
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    rationale: str | None = None


class ContactBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contacts: list[EnrichedContact] = Field(default_factory=list)
