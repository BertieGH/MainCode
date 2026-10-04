"""How far back it is worth looking, and how far back a signal may be dated.

Two questions, deliberately answered in two places.

**Research and evidence intake** use `widest_durability` — the longest
durability across every active type. Not the durability of the types a family
feeds, which is the tempting narrowing and is wrong: a source says what
research *opens*, and every document it returns is interpreted against every
active signal type (see CLAUDE.md). A `news` document at 700 days is beyond
`mgt_change`'s durability and well inside `tech_adoption`'s, so filtering the
`news` sweep by its own feeds would throw away a `tech_adoption` signal that
was there to be had.

**Extraction** uses `durability_of` per type, which is the exact rule. This is
where a `mgt_change` dated 638 days ago is refused while a `tech_adoption`
dated 582 days ago is kept.

So the intake gate is the cheap, coarse one that stops paying to read the
obviously dead, and the extraction gate is the precise one. Neither is
sufficient alone, which is why both exist.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import SignalType

#: The multiple of a type's TTL that `durability_days` defaults to. A fact
#: stays worth reading about three times as long as it stays an opener — asked
#: for in those words, and kept as the default rather than written into every
#: row so that changing a TTL still carries its durability with it.
DEFAULT_DURABILITY_MULTIPLE = 3

#: Used when no active type exists to derive a window from. Research with no
#: active signal types has nothing to look for anyway; the gate must not be the
#: thing that decides that, so it stays open.
FALLBACK_DURABILITY_DAYS = 365 * DEFAULT_DURABILITY_MULTIPLE


def durability_of(signal_type: SignalType) -> int:
    """How many days a fact of this type stays worth reading."""
    explicit = signal_type.durability_days
    if explicit is not None:
        return explicit
    return signal_type.default_ttl_days * DEFAULT_DURABILITY_MULTIPLE


def widest_durability(types: list[SignalType]) -> int:
    """The longest durability among these types — the research window.

    Max, not min, and not per-family: see the module docstring. A shorter
    window would silently cost signals of the longest-lived type.
    """
    windows = [durability_of(t) for t in types]
    return max(windows) if windows else FALLBACK_DURABILITY_DAYS


async def research_cutoff(session: AsyncSession, *, today: date | None = None) -> date:
    """The oldest publication date research should bother with."""
    types = list(
        (
            await session.execute(
                select(SignalType).where(SignalType.status == "active")
            )
        ).scalars()
    )
    return (today or date.today()) - timedelta(days=widest_durability(types))


def cutoff_for_prompt(cutoff: date) -> str:
    """The cutoff as the research prompt states it: a month, not a day.

    Rounded deliberately. The cutoff moves every day, and a date that moves
    every day in the prompt means the prompt differs byte-for-byte between
    runs, which means the cache never hits — the same trap as a timestamp in
    serialised config. A month boundary moves twelve times a year instead of
    three hundred and sixty-five, and the extra few days of slack are caught by
    the intake and extraction gates anyway.
    """
    return cutoff.strftime("%B %Y")
