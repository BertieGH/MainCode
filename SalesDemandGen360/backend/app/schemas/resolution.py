"""What the model may say when asked to identify a company.

The contract asks for **candidates with confidence**, never for an answer.
Asked "what is Acme's domain?" a model will always produce one, because that is
what the question demands. Asked "which companies trade under this name, and
how sure are you about each?", it can say *three do* — and that is the answer a
rep needs in order to pick the right one.

`confidence` is therefore the load-bearing field, not `domain`.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CompanyCandidate(BaseModel):
    """One company this row might refer to."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    #: Bare registrable domain — `acme.com`, not a URL and not a landing page.
    domain: str | None = None
    #: The company page, `/company/...`. A `/in/...` URL is a person and is
    #: rejected downstream by `normalise_linkedin`.
    linkedin_url: str | None = None
    industry: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    #: 0–1. Reserve above 0.9 for a match confirmed by more than the name —
    #: the site itself, a filing, a matching location. A common name matched on
    #: nothing else is not a confident answer however plausible it reads.
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    #: What the identification rests on, in one line. Read by a human deciding
    #: whether to trust it, so "matched the careers page to the HQ city in the
    #: list" is useful and "found the company" is not.
    rationale: str = Field(min_length=1)


class CompanyResolution(BaseModel):
    """Every company the row could plausibly mean, best first.

    An empty list is a legitimate answer. Saying "no company matches this" is
    more useful than a low-confidence guess, because a guess that reaches
    `resolved` sends research at the wrong business and nothing downstream can
    tell.
    """

    model_config = ConfigDict(extra="forbid")

    candidates: list[CompanyCandidate] = Field(default_factory=list)
    #: What was searched and could not be established. Makes "we looked and
    #: there is nothing" distinguishable from "we did not look" — the same rule
    #: `EvidenceBatch` follows.
    not_found: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _silence_must_say_what_it_looked_for(self) -> CompanyResolution:
        if not self.candidates and not self.not_found:
            raise ValueError(
                "an empty resolution must say what was searched for in `not_found`; "
                "silence is indistinguishable from never having looked"
            )
        return self
