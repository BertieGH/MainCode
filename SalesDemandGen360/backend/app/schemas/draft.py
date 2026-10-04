"""The drafting contract: the whole arc, in one object.

One call writes every touch, so the model can see the progression and avoid
repeating itself — and so a rep approves once per thread rather than once per
touch. Six approvals × 24 threads is 144 review actions, at which point the rep
stops using the system.

`signal_dependence` is the load-bearing field. Touch 6 is written on day 0 and
sends on day 15, by which time "congrats on the raise" may be describing
something months old. Grading each touch and refusing a late `dated` one is a
schema-level guard rather than a prompt suggestion, because it is the failure a
rep cannot catch at approval: on day 0 the copy reads perfectly.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Channel = Literal[
    "linkedin_connect", "linkedin_message", "linkedin_engage", "inmail", "email"
]
#: dated    — cites a signal as current fact ("congrats on the Series B")
#: implied  — references its implication without restating it as current
#: durable  — as true on day 15 as on day 0
SignalDependence = Literal["dated", "implied", "durable"]


class TouchDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_no: Annotated[int, Field(ge=1)]
    #: Not asked for any more, and ignored when a model offers it anyway. LGM
    #: owns the schedule; we own the words. Declared rather than forbidden so a
    #: response shaped by the old prompt still parses.
    day_offset: Annotated[int | None, Field(ge=0)] = None
    channel: Channel
    purpose: str = Field(min_length=1)
    subject: str | None = None
    body: str = Field(min_length=1)
    signal_dependence: SignalDependence
    cited_signal_ids: list[str] = Field(default_factory=list)
    cited_proof_point_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dated_copy_must_name_its_signal(self) -> TouchDraft:
        """A touch claiming to be dated has to say which signal it is dated to.

        Otherwise the pre-send freshness check has nothing to re-validate, and
        the guard degrades into a label.
        """
        if self.signal_dependence == "dated" and not self.cited_signal_ids:
            raise ValueError(
                f"step {self.step_no}: signal_dependence='dated' must cite the signal "
                "it depends on, or freshness cannot be re-checked before sending"
            )
        return self


class DraftSet(BaseModel):
    """Every touch in the sequence. Partial arcs are not accepted."""

    model_config = ConfigDict(extra="forbid")

    #: No `max_length`: it reaches Gemini as `maxItems`, which that API
    #: rejects with HTTP 400. See `strategy.StrategyProposal.threads`.
    touches: list[TouchDraft] = Field(min_length=1)

    @model_validator(mode="after")
    def _the_arc_is_complete_and_ordered(self) -> DraftSet:
        steps = [t.step_no for t in self.touches]
        if sorted(steps) != list(range(1, len(steps) + 1)):
            raise ValueError(
                f"steps must be 1..{len(steps)} with no gaps or repeats, got {sorted(steps)}"
            )

        ordered = sorted(self.touches, key=lambda t: t.step_no)
        offsets = [t.day_offset for t in ordered if t.day_offset is not None]
        # Only meaningful when a model volunteered every day: a partial set
        # cannot go backwards in any way worth refusing an arc over.
        if len(offsets) == len(ordered) and offsets != sorted(offsets):
            raise ValueError(
                f"day offsets must not go backwards across the arc, got {offsets}"
            )
        return self

    def by_step(self) -> dict[int, TouchDraft]:
        return {t.step_no: t for t in self.touches}


class ArcProblem(BaseModel):
    """One reason an arc cannot be stored or enrolled."""

    step_no: int | None
    reason: str
    detail: str


class FreshnessVerdict(BaseModel):
    """The pre-send check. Stop or continue — never a redraft.

    Content is frozen on the LGM lead once enrolled, so this call has no power
    to rewrite anything. Giving it one would produce copy that differs from
    what LGM will actually send.
    """

    model_config = ConfigDict(extra="forbid")

    proceed: bool
    stop_reason: Literal["signal_expired", "reply_received", "compliance", "manual"] | None = None
    detail: str | None = None
    stale_signal_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _a_stop_says_why(self) -> FreshnessVerdict:
        if not self.proceed and self.stop_reason is None:
            raise ValueError("a stop verdict must carry a stop_reason")
        if self.proceed and self.stop_reason is not None:
            raise ValueError("a proceed verdict cannot carry a stop_reason")
        return self
