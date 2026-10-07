"""What a company is, as against what has just happened to it.

A signal answers *why now*. This answers *who are they*, and the two need
different handling: a signal expires, and "they are a commercial insurance
brokerage serving contractors in southern California" does not. Giving that a
TTL would mean expiring a fact that has not changed.

It rides on `account.profile` and is read by the context builder, so every
later stage — qualification, strategy, drafting — can say what the company
does without re-deriving it per call. It is deliberately **not** a signal type:
proposed during curation as `firmographic_baseline`, and nothing in it says
*now*.

Every field is optional. A profile that only knows three things says three
things; inventing the rest is how a draft ends up describing a company that
does not exist.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Passage(BaseModel):
    """One piece of source text, kept **whole**, with where it came from.

    The structured fields above are a synthesis: capped, compressed, and shaped
    for deterministic use. This is what they were made from, uncut.

    It exists because the stages that write a cadence — strategy and drafting —
    read `profile`, not `evidence`. A summary capped at four hundred characters
    is the right thing to score on and the wrong thing to write from: the phrase
    a rep would actually quote is usually the one the cap removed.

    Chunked rather than one blob, so each passage keeps the URL that reopens it.
    A sentence a draft leans on has to be checkable, and a concatenated wall of
    text cannot say which part came from where.
    """

    #: The source text, as retrieved. Not summarised, not trimmed.
    text: str = Field(min_length=1)
    #: Where it came from, so a rep can open it and a draft can be checked.
    url: str | None = None
    #: What produced it — a registry source key, so a passage can be traced to
    #: the thing that cost money to read.
    source: str | None = None


class CompanyProfile(BaseModel):
    """Firmographics, in the company's own terms where possible."""

    #: The source text these fields were synthesised from, kept whole.
    #: Strategy and drafting read the profile rather than the evidence, so
    #: without this the only words they ever see are the capped ones.
    verbatim: list[Passage] = Field(default_factory=list, max_length=20)
    #: One sentence a rep could read aloud. Their words if they have them.
    what_they_do: str | None = Field(default=None, max_length=400)
    #: Lines of business they sell. For a brokerage: commercial lines,
    #: employee benefits, personal lines, surety, risk management.
    services: list[str] = Field(default_factory=list, max_length=20)
    #: Who they sell *to* — the thing most often missing and most often
    #: needed, because it is what makes a pitch sound like it was written for
    #: them. "Contractors", "non-profits", "mid-market manufacturers".
    target_customers: list[str] = Field(default_factory=list, max_length=20)
    #: Verticals they name themselves as serving. Distinct from
    #: `target_customers`: one is a kind of buyer, the other a sector.
    industries_served: list[str] = Field(default_factory=list, max_length=20)
    #: As stated, not as estimated — "about 40 employees", "a team of 12".
    size: str | None = Field(default=None, max_length=120)
    locations: list[str] = Field(default_factory=list, max_length=20)
    #: What they are pushing right now: a practice they are building, a market
    #: they are entering, a capability they keep writing about. The closest
    #: thing here to a signal, and still not one — it has no date.
    current_focus: list[str] = Field(default_factory=list, max_length=12)
    #: Independent, part of a group, private-equity backed, recently acquired.
    #: Matters for who actually decides anything.
    ownership: str | None = Field(default=None, max_length=200)
    founded: str | None = Field(default=None, max_length=40)
    #: Where this came from. Not evidence rows — a profile is not a claim that
    #: needs citing the way a signal is — but a rep asking "says who?" deserves
    #: an answer, and a stale profile needs somewhere to re-read.
    sources: list[str] = Field(default_factory=list, max_length=12)

    def is_empty(self) -> bool:
        """Nothing was established. Worth distinguishing from "not looked"."""
        #  counts: passages read but not synthesised are still the
        # company's own words, and a draft can quote them.
        return not any(
            (
                self.verbatim,
                self.what_they_do,
                self.services,
                self.target_customers,
                self.industries_served,
                self.size,
                self.locations,
                self.current_focus,
                self.ownership,
                self.founded,
            )
        )


class ContactProfile(BaseModel):
    """Who a person is, as against what has just happened to them.

    Stored **undated and ungated**, like the company profile and for the same
    reason: that someone runs operations at a brokerage is not a fact with an
    expiry, and the durability window would throw it away for being old when
    it is simply true. A *role change* is the dated event; this is the standing
    description.

    Carries only what `contact` does not already hold. Title, seniority,
    persona and buying role are columns; repeating them here would give two
    answers to one question.

    **No contact details, ever.** Not email, not phone, not a guess at either.
    Those come from a verification provider with a status attached, and a
    generated address that happens to look right is how a sending domain gets
    blacklisted.
    """

    #: The source text these fields were synthesised from, kept whole. A
    #: profile snippet is already short; capping it twice leaves a draft
    #: nothing to quote.
    verbatim: list[Passage] = Field(default_factory=list, max_length=20)
    #: One sentence a rep could open with. Their public self-description where
    #: there is one.
    summary: str | None = Field(default=None, max_length=400)
    #: What they actually own — the systems, teams, budgets or lines named as
    #: theirs. The part that decides whether a pitch is addressed to the right
    #: person.
    responsibilities: list[str] = Field(default_factory=list, max_length=12)
    #: As stated: "joined in 2019", "eight years with the firm". Not computed
    #: from a profile date, because a profile has no date.
    tenure: str | None = Field(default=None, max_length=120)
    #: Where they were before, if said in public. Useful for a warm line and
    #: for guessing what they will compare you to.
    background: list[str] = Field(default_factory=list, max_length=10)
    #: What they write, speak or post about. The nearest thing to a hook here,
    #: and still not a signal — it has no date.
    focus_areas: list[str] = Field(default_factory=list, max_length=10)
    #: What they appear able to decide alone, in the words used about them.
    #: An inference dressed as a fact is worse than silence.
    decision_scope: str | None = Field(default=None, max_length=240)
    sources: list[str] = Field(default_factory=list, max_length=12)

    def is_empty(self) -> bool:
        # `verbatim` counts. A model that synthesised nothing but returned
        # the passages it read has still produced something a draft can
        # quote, and discarding it would throw away the only words we have.
        return not any(
            (
                self.verbatim,
                self.summary,
                self.responsibilities,
                self.tenure,
                self.background,
                self.focus_areas,
                self.decision_scope,
            )
        )
