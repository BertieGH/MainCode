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

    #: **The single most important outcome of this call.** The first thing on
    #: the screen, because a rep who knows what they are trying to achieve can
    #: improvise and one who knows only what to say cannot. One sentence.
    call_objective: str = Field(min_length=1)
    #: What this call is explicitly *not* for. Usually the thing an eager rep
    #: would otherwise try: convincing the prospect they have a problem.
    objective_excludes: str | None = None
    #: Two or three ways in, at different levels of exposure.
    openings: list[Opening] = Field(default_factory=list, max_length=3)
    #: Possible findings, not expected answers — including the finding that
    #: there is nothing here.
    listen_for: list[str] = Field(default_factory=list)
    next_steps: list[NextStep] = Field(default_factory=list)

    #: Facts read from a source.
    what_we_know: list[str] = Field(default_factory=list)
    #: Our reading of those facts. Not established.
    what_we_suspect: list[str] = Field(default_factory=list)
    #: Named gaps.
    what_we_do_not_know: list[str] = Field(default_factory=list)
    #: **Things the rep must not treat as true on the call.** Distinct from
    #: "what we do not know": an unknown is a gap, this is a trap. The more
    #: specific and personalised a brief reads, the easier it is to walk in
    #: believing its hypothesis is a finding.
    do_not_assume: list[str] = Field(default_factory=list)

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
