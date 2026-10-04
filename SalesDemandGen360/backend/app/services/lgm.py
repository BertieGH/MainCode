"""The La Growth Machine adapter — the only component with send capability.

Nothing else in the system can put a message in front of a person. That is
worth stating as a boundary rather than a convention: no LLM tool wraps this,
and no research or drafting path can reach it. A model that can send is a model
that can be induced to send by text on a page it was asked to read.

What LGM owns and we do not:

* **Cadence structure.** Touch count and timing live in a pre-built LGM
  campaign. We select a registered shape and fill its `custom_attribute_N`
  slots. There is no step editor here, ever.
* **The copy, once written.** LGM reads from the lead's attributes, not from
  us. After enrolment the words are frozen — the only levers are stop-sequence
  and stop-campaign.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

#: LGM allows twenty custom attributes per lead, globally across campaigns.
#: Measured, not read: 11, 15 and 20 all store and read back on a live account,
#: and a 21st is refused with the 404 LGM uses for a validation error.
ATTRIBUTE_BUDGET = 20

#: And 1000 characters in each. LGM truncates quietly; a truncated touch still
#: sends, so the arc is refused before it can be written.
ATTRIBUTE_MAX_CHARS = 1000

#: How a lead attribute is spelled on the wire, and how we spell it here.
_WIRE = re.compile(r"^customAttribute(\d{1,2})$")
_OURS = re.compile(r"^custom_attribute_(\d{1,2})$")


def wire_attribute(name: str) -> str:
    """`custom_attribute_7` → `customAttribute7`, which is what LGM accepts.

    It lives beside the protocol rather than inside the live client so that
    **the stub validates names too**. That is the whole lesson of the bug it
    exists for: two vocabularies met at the boundary, nobody translated, and
    every real enrolment was rejected for an unknown field — while the tests
    stayed green, because the stub happily stored whatever it was handed. A
    fake that accepts more than the real thing does not prove anything.

    An unrecognised name is refused rather than passed through: one unknown
    field makes LGM reject the entire lead, body included.
    """
    ours = _OURS.match(name)
    if ours:
        number = int(ours.group(1))
    else:
        wire = _WIRE.match(name)
        if not wire:
            raise LgmError(
                f"{name!r} is not a lead attribute La Growth Machine knows; it accepts "
                f"customAttribute1 to customAttribute{ATTRIBUTE_BUDGET}"
            )
        number = int(wire.group(1))
    if not 1 <= number <= ATTRIBUTE_BUDGET:
        raise LgmError(
            f"{name!r} is outside the {ATTRIBUTE_BUDGET} attributes La Growth Machine allows"
        )
    return f"customAttribute{number}"


@dataclass(frozen=True)
class LgmLead:
    lead_id: str
    email: str | None = None
    linkedin_url: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LgmCampaignMeta:
    """What the metadata endpoint exposes.

    Deliberately small: LGM cannot return the sequence structure, so
    `updated_at` and `channels` are the only change detectors available. See
    `docs/07` L4.
    """

    campaign_id: str
    status: str
    updated_at: datetime | None = None
    channels: tuple[str, ...] = ()


class LgmError(RuntimeError):
    """The provider refused or could not be reached."""


@runtime_checkable
class LgmAdapter(Protocol):
    """Read metadata, write attributes, enrol, stop.

    There is no `update_attributes_for_running_lead` and no `edit_step`: both
    would let content diverge from what a rep approved, and LGM offers no way
    to make the change visible afterwards.
    """

    async def campaign_meta(self, lgm_campaign_id: str) -> LgmCampaignMeta: ...

    async def upsert_lead(
        self,
        *,
        email: str | None,
        linkedin_url: str | None,
        attributes: dict[str, str],
        audience: str | None = None,
        person: object | None = None,
    ) -> LgmLead:
        """Create or match a lead and write its attributes in one call.

        One call because the attributes are the message bodies: writing them in
        several round trips leaves a window where a campaign could start
        half-written, and LGM gives no way to detect that after the fact.

        `audience` is how enrolment actually happens: LGM campaigns run over an
        audience and have no per-lead enrol call, so the name given here is what
        puts this person into the campaign. `person` carries the matching fields
        and our contact id (`crm_id`), which is the join key for everything that
        comes back later — replies, conversations, stats.
        """
        ...

    async def enrol(self, *, lead_id: str, lgm_campaign_id: str) -> str:
        """Confirm this campaign will send to the audience the lead was written to.

        Not a call to LGM's API — it has none. Membership is enrolment; this
        refuses when the campaign is in a state that will never send.
        """
        ...

    async def stop_lead(self, *, lead_id: str, lgm_campaign_id: str) -> None:
        """Halt this lead's remaining touches. The only post-enrolment lever."""
        ...

    async def stop_campaign(self, lgm_campaign_id: str) -> None: ...


@dataclass
class StubLgmAdapter:
    """In-memory stand-in, until credentials and the auth scheme land (`07` Q3).

    Faithful about the things that shape our code: it enforces the attribute
    budget the way LGM does — by **silently dropping the overflow** rather than
    erroring, which is exactly why the budget is checked before we get here.
    """

    leads: dict[str, LgmLead] = field(default_factory=dict)
    #: audience name → who was written into it, as the live client does.
    audiences: dict[str, list[str]] = field(default_factory=dict)
    enrolments: dict[str, str] = field(default_factory=dict)
    stopped_leads: set[tuple[str, str]] = field(default_factory=set)
    stopped_campaigns: set[str] = field(default_factory=set)
    meta: dict[str, LgmCampaignMeta] = field(default_factory=dict)
    available: bool = True
    #: Enforce the per-lead cap, as LGM does: an over-budget write is refused,
    #: not truncated. The name is historical — it was set when we believed the
    #: overflow was dropped in silence.
    drop_over_budget: bool = True

    def _check(self) -> None:
        if not self.available:
            raise LgmError("stub LGM marked unavailable")

    async def campaign_meta(self, lgm_campaign_id: str) -> LgmCampaignMeta:
        self._check()
        if lgm_campaign_id in self.meta:
            return self.meta[lgm_campaign_id]
        return LgmCampaignMeta(
            campaign_id=lgm_campaign_id, status="active", updated_at=datetime.now(UTC)
        )

    async def upsert_lead(
        self,
        *,
        email: str | None,
        linkedin_url: str | None,
        attributes: dict[str, str],
        audience: str | None = None,
        person: object | None = None,
    ) -> LgmLead:
        self._check()
        if audience:
            self.audiences.setdefault(audience, []).append(email or linkedin_url or "?")
        if not email and not linkedin_url:
            raise LgmError("a lead needs an email or a LinkedIn URL to be matched")

        # Validated exactly as the live adapter validates, so a name LGM would
        # reject fails here too instead of passing in tests and failing live.
        for name in attributes:
            wire_attribute(name)
        written = dict(attributes)
        if self.drop_over_budget and len(written) > ATTRIBUTE_BUDGET:
            # The stub used to discard the overflow in silence, because the
            # documentation said that is what LGM does. It is not: a 21st
            # attribute is **refused**. A stub that loses a touch where the
            # real thing would refuse the write teaches the wrong lesson, so
            # this now refuses too.
            raise LgmError(
                f"{len(written)} attributes exceeds the {ATTRIBUTE_BUDGET} La Growth Machine "
                "allows per lead; the write is refused rather than truncated"
            )

        key = (linkedin_url or email or "").lower()
        existing = self.leads.get(key)
        lead_id = existing.lead_id if existing else f"lgm-lead-{uuid.uuid4().hex[:10]}"
        lead = LgmLead(
            lead_id=lead_id, email=email, linkedin_url=linkedin_url, attributes=written
        )
        self.leads[key] = lead
        return lead

    async def enrol(self, *, lead_id: str, lgm_campaign_id: str) -> str:
        self._check()
        if lgm_campaign_id in self.stopped_campaigns:
            raise LgmError(f"campaign {lgm_campaign_id} is stopped and cannot accept enrolments")
        ref = f"lgm-enrol-{uuid.uuid4().hex[:10]}"
        self.enrolments[lead_id] = ref
        return ref

    async def stop_lead(self, *, lead_id: str, lgm_campaign_id: str) -> None:
        self._check()
        self.stopped_leads.add((lead_id, lgm_campaign_id))

    async def stop_campaign(self, lgm_campaign_id: str) -> None:
        self._check()
        self.stopped_campaigns.add(lgm_campaign_id)
