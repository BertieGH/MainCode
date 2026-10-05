"""The strategy contract: the argument, for threads already chosen.

Who is worth talking to is decided in `app/services/strategy.py` by arithmetic
over configured weights, because "why wasn't the CFO contacted?" has to have an
answer a rep can read. This contract covers only what is left after that: for
each thread the selector kept, what the argument actually is.

The contract's real job is `assert_differentiated`'s precondition. Two people
at one company receiving materially the same message is how an account learns
it is being automated at — so the model is asked for a per-persona hypothesis
and the service rejects the set if two come back the same. Making the model
produce one object covering all threads, rather than one call per thread, is
what makes that check possible at all: a per-thread call cannot see the other
threads to differ from them.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Channel = Literal[
    "linkedin_connect", "linkedin_message", "linkedin_engage", "inmail", "email"
]


class ProposedThread(BaseModel):
    """The case for approaching one person about one service."""

    model_config = ConfigDict(extra="forbid")

    #: Must be one of the contacts the selector activated. Anything else is
    #: dropped by the service — the model does not get to add a thread.
    contact_id: uuid.UUID
    service_id: uuid.UUID

    #: What we think hurts. Labelled a hypothesis everywhere it is shown,
    #: because it is our inference and not something they have said.
    problem_hypothesis: str = Field(min_length=1)
    #: The event that makes now the moment, in one line.
    trigger_summary: str = Field(min_length=1)
    #: The live signals behind that trigger. Checked against the live set by
    #: `strategy.check_triggers` — a thread pitching on an expired trigger
    #: reads as automation that did not look.
    #: Empty only for a person the rep allowed without one — the service
    #: refuses an empty list for anyone else.
    trigger_signal_ids: list[str] = Field(default_factory=list)
    #: How we frame the service against that problem, for this person.
    positioning: str = Field(min_length=1)
    channel_sequence: list[Channel] = Field(min_length=1)
    cta: str = Field(min_length=1)
    #: Angles to stay off — a competitor they just left, a layoff round.
    avoid_list: list[str] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5


class StrategyProposal(BaseModel):
    """Every active thread at one account, argued together."""

    model_config = ConfigDict(extra="forbid")

    #: Unbounded above, floored below. A `max_length` looks like the way to
    #: stop a derailed call writing threads until the output budget runs out,
    #: and it reaches Gemini as `maxItems`, which that API answers with
    #: **HTTP 400** — tried against the live model, measured, reverted.
    #:
    #: `minItems` *is* accepted, and `min_length=1` is what sends it. That
    #: floor is load-bearing: with a `default_factory` the model could satisfy
    #: the contract by returning no threads at all, and it did — repeatedly,
    #: writing its whole answer into `account_angle` and leaving this empty.
    #: A rep then saw "the model returned nothing for them", which reads as a
    #: judgement about the person rather than a malformed answer. The schema
    #: now refuses it, so the repair path gets a chance instead.
    threads: list[ProposedThread] = Field(min_length=1)
    #: The one-line account-level read the threads hang off. **One sentence.**
    #: Its length cannot be enforced here — `maxLength` draws the same HTTP 400
    #: as `maxItems` — so the prompt carries that rule, and this is the field
    #: that runs away when it does not.
    account_angle: str | None = None

    @model_validator(mode="after")
    def _one_thread_per_contact(self) -> StrategyProposal:
        """A person contacted twice about one account is the failure here.

        The selector already guarantees one cell per contact; this catches the
        model returning two proposals for the same person, which would
        otherwise become two threads and two sequences.
        """
        seen = [t.contact_id for t in self.threads]
        if len(set(seen)) != len(seen):
            dupes = sorted({str(c) for c in seen if seen.count(c) > 1})
            raise ValueError(f"more than one thread proposed for contact(s): {dupes}")
        return self
