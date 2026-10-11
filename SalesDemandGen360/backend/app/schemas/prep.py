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

import re

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
    #: What the answer changes about the approach. **A question whose answer
    #: changes nothing does not earn a place in the three a rep actually
    #: reads**, so this is required rather than decorative.
    changes: str = Field(min_length=1)
    #: Where to go next depending on what comes back. Two branches at most:
    #: this is read on a call, not studied.
    branches: list[str] = Field(default_factory=list, max_length=2)


class Opening(BaseModel):
    """One way to start, with when to use it.

    **Three options rather than one line, because they are three levels of
    exposure.** A junior BDE can say the honest-outsider opening to anyone; the
    one that names a specific technical question needs someone who can hold the
    answer. Giving a new rep a single opening they cannot defend is how a good
    brief produces a bad call.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    #: The words, as they would be said aloud. Not a paragraph.
    words: str = Field(min_length=1, max_length=600)
    use_when: str = Field(min_length=1)
    why_it_works: str = Field(min_length=1)


class NextStep(BaseModel):
    """What to do, conditional on what the prospect actually says.

    A brief that recommends one next step has assumed the call goes one way.
    """

    model_config = ConfigDict(extra="forbid")

    condition: str = Field(min_length=1)
    action: str = Field(min_length=1)


class Objection(BaseModel):
    """An objection with its pre-empt, not a rebuttal to read out."""

    model_config = ConfigDict(extra="forbid")

    objection: str = Field(min_length=1)
    pre_empt: str = Field(min_length=1)
    likelihood: Literal["low", "medium", "high"] = "medium"
    #: **Anticipated or actually raised.** A rep must never defend against a
    #: concern nobody voiced; it invents an argument and loses the room. Only
    #: a reply in evidence may be marked `observed`.
    kind: Literal["anticipated", "observed"] = "anticipated"
    #: A question that finds out whether the objection is a real barrier or a
    #: preference with exceptions.
    follow_up: str | None = None


class SalesPrepPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: **The one thing this call should establish.** First on the screen,
    #: because a rep who knows what they are trying to learn can improvise and
    #: one who knows only what to say cannot.
    #:
    #: Named `what_to_find_out` rather than `call_objective` deliberately. Told
    #: to write a "call objective", the model wrote a pitch goal three times
    #: running — *"introduce Enterprise Intelligence Amplification to help
    #: them…"* — which is what the phrase means everywhere else in sales. It
    #: was not misreading the instruction; it was reading the field name, and
    #: the field name won. This one carries no such prior.
    what_to_find_out: str = Field(min_length=1, description=(
        "The single thing this call should establish that is not known now. "
        "About them, never about us: if it mentions what you sell, it is a "
        "pitch goal and it is wrong."
    ))
    #: What an eager rep would otherwise attempt here, and should not.
    what_not_to_attempt: str | None = Field(default=None, description=(
        "The thing a rep would otherwise try on this call and must not — "
        "usually convincing the prospect they have the problem. Not the "
        "campaign avoid-list, which you already have."
    ))
    #: **That the hypothesis is a hypothesis**, in one sentence.
    #:
    #: A required field rather than an item in `do_not_assume`, because as an
    #: item it was dropped from every brief generated. Research can establish
    #: that a company shipped four AI surfaces; it cannot establish that the
    #: company *minds*. A rep who forgets that argues with a founder about his
    #: own roadmap, and the list this used to live in was exactly the wrong
    #: place for the one entry that must never be missing.
    problem_is_unproven: str = Field(min_length=1, description=(
        "One sentence naming the hypothesised problem and saying plainly that "
        "nothing establishes the prospect actually has it."
    ))
    #: Two or three ways in, at different levels of exposure.
    openings: list[Opening] = Field(default_factory=list, max_length=3)
    #: Possible findings, not expected answers — including the finding that
    #: there is nothing here.
    listen_for: list[str] = Field(default_factory=list, description="Things you could LEARN on this call, phrased as findings — not keywords. Include the finding that there is nothing here.")
    next_steps: list[NextStep] = Field(default_factory=list)

    #: Facts read from a source.
    what_we_know: list[str] = Field(default_factory=list, description="Facts read from the payload you were given — signals, the account profile, the contact profile. Never from your own knowledge.")
    #: Our reading of those facts. Not established.
    what_we_suspect: list[str] = Field(default_factory=list, description="Your reading of those facts. Never phrased as fact.")
    #: Named gaps.
    what_we_do_not_know: list[str] = Field(default_factory=list, description="Named gaps.")
    #: **Things the rep must not treat as true on the call.** Distinct from
    #: "what we do not know": an unknown is a gap, this is a trap. The more
    #: specific and personalised a brief reads, the easier it is to walk in
    #: believing its hypothesis is a finding.
    do_not_assume: list[str] = Field(default_factory=list, description="Traps, not gaps: what the rep must not treat as true on the call.")

    elevator_pitch: str = Field(min_length=1, description="Thirty seconds, if he asks what you do.")
    pitch_structure: PitchStructure
    discovery_questions: list[DiscoveryQuestion] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)
    #: What this account has already been told, in the rep's words. Generated
    #: from the sent touches, so the call does not restate the sequence.
    already_said: list[str] = Field(default_factory=list, description="Only touches that actually sent. Empty if none did.")
    #: What they said back, if anything.
    their_replies: list[str] = Field(default_factory=list, description="Their words. Empty if nobody has replied.")
    #: Named gaps a rep should know they are walking in with.
    open_questions: list[str] = Field(default_factory=list, description="Gaps the rep walks in with.")

    @model_validator(mode="after")
    def _a_brief_asks_something(self) -> SalesPrepPayload:
        if not self.discovery_questions:
            raise ValueError(
                "a prep brief with no discovery questions is a pitch script; "
                "the call exists to learn something"
            )
        if not self.do_not_assume:
            raise ValueError(
                "a prep brief that names nothing the rep must not assume has "
                "mistaken its own hypotheses for findings; research cannot "
                "establish whether a company feels a problem, and the brief "
                "has to say so"
            )
        if not self.openings:
            raise ValueError(
                "a brief with no opening leaves the rep to improvise the one "
                "sentence that decides whether the call continues"
            )
        return self

    @model_validator(mode="after")
    def _what_to_find_out_is_about_them(self) -> SalesPrepPayload:
        """A thing to find out cannot be a thing we say.

        Checked by pronoun rather than by looking for product names, which
        needs no catalogue and cannot be evaded by inventing a new one: a
        sentence describing what to establish about a prospect has no reason
        to mention us at all. The three briefs that failed this all failed on
        the same word — *"and introduce **our** EIA services"* — tacked onto
        an otherwise correct objective.
        """
        words = re.findall(r"[a-z']+", self.what_to_find_out.lower())
        ours = {"we", "our", "ours", "us", "we'll", "we're", "we've"}
        found = sorted(ours.intersection(words))
        if found:
            raise ValueError(
                "what_to_find_out mentions us "
                f"({', '.join(found)}) — it reads as a pitch goal rather than "
                "something to establish about them. Say what the call should "
                "make known, not what it should sell."
            )
        return self

    @model_validator(mode="after")
    def _an_objection_is_only_observed_if_they_said_it(self) -> SalesPrepPayload:
        """`observed` means it is in the record, and the record is `their_replies`.

        Without this the model can promote its own guess to something the
        prospect said, and a rep answers an objection nobody raised.
        """
        if any(o.kind == "observed" for o in self.objections) and not self.their_replies:
            raise ValueError(
                "an objection is marked observed but nothing has been replied; "
                "an anticipated objection must not be presented as one they raised"
            )
        return self
