"""The research contract: what a family fan-out is allowed to bring back.

Evidence is the bottom of every audit trail, so this contract is stricter than
the table it feeds. Three fields carry the weight:

* **`excerpt` is required and must be a quotation.** A summary written by the
  model is not evidence — it is an unattributed claim that looks like one. The
  whole point of the citation chain is that a rep can read the sentence the
  conclusion rests on.
* **`observed_at` is when the fact was true**, not when it was retrieved. A
  funding round found today and closed in 2023 is not a trigger, and the only
  place that distinction can be made is here, where the page is in view.
* **`source_url` is required for everything except `manual`.** Evidence nobody
  can re-open is evidence nobody can check.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Mirrors `app.models.signal.SOURCE_TYPES` minus `manual` and `crm`: a
#: research call cannot produce either. Manual capture comes from a rep, and
#: CRM evidence comes from the CRM adapter, which the model never sees.
ResearchSourceType = Literal["web", "news", "jobs", "linkedin", "provider", "filing"]


class FoundEvidence(BaseModel):
    """One passage, with enough provenance to re-open it later."""

    model_config = ConfigDict(extra="forbid")

    source_type: ResearchSourceType
    source_url: str = Field(min_length=1)
    #: The publication or site, as a human would name it.
    source_name: str | None = None
    title: str | None = None
    #: Quoted from the source. Not paraphrased, not summarised.
    excerpt: str = Field(min_length=1)
    #: When the fact was true. Null when the source genuinely does not date it —
    #: an undated claim is weaker, and pretending to a date would hide that.
    observed_at: date | None = None
    #: How much the source is worth, 0–1. A company blog stating its own
    #: headcount is not a filing.
    reliability: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    #: Why this passage was kept, for the coverage log. Never stored on the
    #: evidence row itself — evidence is what was found, not why.
    relevance: str | None = None


class EvidenceBatch(BaseModel):
    """Everything one family found for one account.

    An empty batch is a legitimate, informative answer: `research.py` records
    it as an `empty` family rather than a failure, and a named conclusion
    becomes unreachable for this account. That is a fact a rep needs, so the
    contract must let the model say it rather than pushing it to invent.
    """

    model_config = ConfigDict(extra="forbid")

    evidence: list[FoundEvidence] = Field(default_factory=list)
    #: What the model searched but could not establish. Feeds the coverage
    #: detail line, so "we looked and there is nothing" is distinguishable
    #: from "we did not look".
    not_found: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _an_empty_batch_says_what_it_looked_for(self) -> EvidenceBatch:
        if not self.evidence and not self.not_found:
            raise ValueError(
                "an empty evidence batch must say what was searched for in `not_found`; "
                "silence is indistinguishable from the family never having run"
            )
        return self


# --------------------------------------------------------------------------
# contact research — the same rules, about named people
# --------------------------------------------------------------------------
class FoundContactEvidence(FoundEvidence):
    """A passage about one of the people named in the request."""

    #: The id of the person it is about, exactly as given. Anything else is
    #: dropped: it cannot be filed under a person, and a guess would file it
    #: under the wrong one.
    contact_id: str = Field(min_length=1)


class ContactSearch(BaseModel):
    """What was searched for one person — kept even when nothing turned up."""

    model_config = ConfigDict(extra="forbid")

    contact_id: str = Field(min_length=1)
    searched: list[str] = Field(default_factory=list)


class ContactEvidenceBatch(BaseModel):
    """One family, for up to three people at one account."""

    model_config = ConfigDict(extra="forbid")

    evidence: list[FoundContactEvidence] = Field(default_factory=list)
    #: Per person, so "nothing found" is a finding about that person.
    searched_for: list[ContactSearch] = Field(default_factory=list)
    #: Notes for the whole call — including passages grounding discarded.
    not_found: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _silence_is_not_an_answer(self) -> ContactEvidenceBatch:
        if not self.evidence and not self.searched_for and not self.not_found:
            raise ValueError(
                "an empty batch must say what was searched for, per person, in "
                "`searched_for`; silence reads as never having looked"
            )
        return self
