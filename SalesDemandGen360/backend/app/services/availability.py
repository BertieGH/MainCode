"""Which models this installation may point a stage at.

Two questions were being answered by one list, and they have different owners:

* **What does the vendor offer?** A fact about the vendor. Lives in
  `provider_catalogue`, changes when they ship something.
* **What is this installation willing to run?** A commercial decision — a
  workspace entitled to the frontier model may still choose to run extraction
  on the cheap one — and it changes without a deploy.

Collapsing them put every model a vendor sells into every stage's dropdown,
which is both a longer list than anyone wants and a standing invitation to
point a nightly batch at the most expensive thing available.

The load-bearing rule here is the **in-use guard**. Removing a model that an
active stage is configured with does not fail at save time; it fails at that
stage's next real call, mid-run, on somebody's account. So a removal that would
strand a stage is refused and names the stages — the same delete-if-unused rule
this codebase applies to signal types, account lists, queues and credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import LlmConfig, ModelAvailability
from app.services import provider_catalogue as catalogue
from app.services.versioning import get_active


@dataclass
class ProviderAvailability:
    """One provider's shortlist, and everything it could have been."""

    provider: str
    label: str
    runnable: bool
    #: Model ids this installation may use.
    enabled: list[str] = field(default_factory=list)
    #: Everything the catalogue knows for this provider, enabled or not.
    catalogue: list[str] = field(default_factory=list)
    #: Enabled ids the catalogue has never heard of — typed in by hand. Kept
    #: rather than dropped: vendor ids drift, and this installation's Gemini
    #: ids were wrong in the catalogue before they were right.
    custom: list[str] = field(default_factory=list)
    #: True when no choice has been made and the catalogue is standing in.
    defaulted: bool = False


@dataclass
class Availability:
    providers: list[ProviderAvailability] = field(default_factory=list)

    def for_provider(self, provider: str) -> ProviderAvailability | None:
        return next((p for p in self.providers if p.provider == provider), None)

    def allows(self, provider: str, model: str) -> bool:
        entry = self.for_provider(provider)
        if entry is None:
            # A provider somebody added. We have no shortlist and no catalogue
            # to check against, so anything they type is allowed — refusing
            # would make an added provider unusable.
            return True
        return model in entry.enabled


async def resolve(session: AsyncSession) -> Availability:
    """The shortlist as it stands, filling in defaults where none was set.

    An absent provider resolves to its whole catalogue rather than to nothing.
    A fresh install with twelve stages and an empty dropdown is a broken
    install, and "we have not decided yet" is much closer to "all of them" than
    to "none of them".
    """
    row = await get_active(session, ModelAvailability)
    stored: dict = dict(row.enabled or {}) if row else {}

    providers: list[ProviderAvailability] = []
    for cat in catalogue.of_kind("llm"):
        known = [m.id for m in cat.models]
        chosen = stored.get(cat.key)
        defaulted = chosen is None
        enabled = list(known) if defaulted else [m for m in chosen]
        providers.append(
            ProviderAvailability(
                provider=cat.key,
                label=cat.label,
                runnable=cat.runnable,
                enabled=enabled,
                catalogue=known,
                custom=[m for m in enabled if m not in known],
                defaulted=defaulted,
            )
        )

    # Providers somebody added, which the catalogue has nothing to say about.
    for key, models in stored.items():
        if key in catalogue.BY_KEY:
            continue
        providers.append(
            ProviderAvailability(
                provider=key,
                label=key,
                runnable=catalogue.is_runnable(key),
                enabled=list(models),
                catalogue=[],
                custom=list(models),
            )
        )
    return Availability(providers=providers)


@dataclass(frozen=True)
class InUse:
    provider: str
    model: str
    scenarios: tuple[str, ...]


async def models_in_use(session: AsyncSession) -> list[InUse]:
    """Every (provider, model) an active stage is configured with."""
    rows = list(
        (
            await session.execute(
                select(LlmConfig.provider, LlmConfig.model, LlmConfig.scenario).where(
                    LlmConfig.is_active.is_(True)
                )
            )
        ).all()
    )
    grouped: dict[tuple[str, str], list[str]] = {}
    for provider, model, scenario in rows:
        grouped.setdefault((provider, model), []).append(scenario)
    return [
        InUse(provider=p, model=m, scenarios=tuple(sorted(s)))
        for (p, m), s in sorted(grouped.items())
    ]


class ModelInUseError(ValueError):
    """A model a stage still points at cannot be removed from the shortlist.

    Not a warning. Removing it does not break anything at save time — it breaks
    that stage's next real call, after research has already been paid for, with
    an error naming a model rather than the setting that removed it.
    """

    def __init__(self, stranded: list[InUse]):
        self.stranded = stranded
        detail = "; ".join(
            f"{u.model} ({u.provider}) is used by {', '.join(u.scenarios)}"
            for u in stranded
        )
        super().__init__(
            f"these models are still configured on active stages: {detail}. "
            "Point those stages at something else first."
        )


async def assert_no_stage_is_stranded(
    session: AsyncSession, proposed: dict[str, list[str]]
) -> None:
    """Refuse a shortlist that would leave a stage pointing at nothing."""
    stranded = [
        use
        for use in await models_in_use(session)
        # A provider missing from the proposal has made no choice, which means
        # its catalogue applies — the same reading `resolve` uses.
        if use.provider in proposed and use.model not in proposed[use.provider]
    ]
    if stranded:
        raise ModelInUseError(stranded)
