"""The context-builder contract: the narrative laid over the signal list.

`app/services/context.py` already builds the deterministic half of a context —
the live signals, sorted, with their strengths and citations. That half is
reproducible from the database and needs no model.

What it cannot produce is the reading: which of eleven signals actually matter
together, what changed since the last version, and — most valuable and most
often skipped — what we still do not know. So this contract is an *overlay*.
It is merged into `account_context.payload` under a single key, and every
claim in it must point back at signals that are already in the deterministic
half. It cannot introduce a fact; it can only organise the facts already there.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Theme(BaseModel):
    """A pattern across several signals that none of them states alone."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    reading: str = Field(min_length=1)
    #: Signal ids from the deterministic payload. Resolved and filtered by the
    #: service, exactly as extraction does with evidence ids.
    signal_ids: list[str] = Field(min_length=1)
    #: How much of the account's story this carries.
    weight: Literal["primary", "supporting"] = "supporting"


class Unknown(BaseModel):
    """Something a rep would want and we do not have.

    Stated as a question rather than a gap name, because it is read by a person
    deciding whether to spend another research pass.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    #: The research family that would answer it, when one would.
    would_be_answered_by: str | None = None


class AccountContextPayload(BaseModel):
    """The overlay. Never a source of new facts."""

    model_config = ConfigDict(extra="forbid")

    #: Two or three sentences a rep could read aloud.
    summary: str = Field(min_length=1)
    themes: list[Theme] = Field(default_factory=list)
    #: What moved since the previous context version, when there was one.
    what_changed: str | None = None
    unknowns: list[Unknown] = Field(default_factory=list)
    #: 0–1 across the whole picture, not per theme. Low confidence on a thin
    #: account is the correct answer and must stay expressible.
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5

    @model_validator(mode="after")
    def _confidence_without_themes_is_unearned(self) -> AccountContextPayload:
        # A summary with no themes is a paraphrase of the signal list. It may
        # be all a thin account supports — but it cannot also claim to be
        # confident, or the number stops meaning anything downstream.
        if not self.themes and self.confidence > 0.5:
            raise ValueError(
                f"confidence {self.confidence} with no themes: a reading that identifies "
                "no pattern across signals cannot be more than moderately confident"
            )
        return self
