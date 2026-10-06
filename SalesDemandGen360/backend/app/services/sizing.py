"""Company size, derived from headcount rather than detected.

Market and size are separate questions about a company, and this answers the
second. The first is `industry`, which the ICP already names — see `docs/09`
for why they were ever one field.

The important property is that a band is **derived, not classified**. Headcount
is a fact already on the row, so this needs no model to produce it, no
confidence score to qualify it, and no stored value at all. None of that
machinery is required to answer "how many people work here".

The band names are deliberately *not* the cadence shape names. `enterprise_8_23`
and `startup_5_11` are shapes registered in La Growth Machine — invariant 6 says
Gen360 never authors a cadence, it selects a registered one. Naming our band
`large` and mapping it onto their `enterprise_8_23` keeps the two vocabularies
separate; naming both `enterprise` would couple them by coincidence, and the
day LGM renames a shape the coupling is what breaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

SizeBand = Literal["small", "mid", "large", "unknown"]

#: Where the bands cut. Chosen to preserve the two cadence rules already in
#: place — a company of 1,000+ gets the long enterprise sequence, one under 50
#: gets the short startup one — rather than to be interesting.
SMALL_BELOW = 50
LARGE_FROM = 1000

#: Every band except `unknown`. `unknown` is the absence of a fact, not a size,
#: and must never carry multipliers: an account nobody has sized should score on
#: the base weights, visibly, rather than on a guess.
BANDS: tuple[str, ...] = ("small", "mid", "large")


def band_for(employee_count: int | None) -> SizeBand:
    """Which band a headcount falls in.

    `None` is `unknown` rather than defaulting into a band. An account imported
    from a CSV with no headcount column is not small; it is unmeasured, and
    scoring it as small would be an invention that nothing on the screen would
    reveal.
    """
    if employee_count is None:
        return "unknown"
    if employee_count < 0:
        # Not a headcount. Treated as absent rather than clamped to zero, so a
        # bad import does not silently become the smallest band.
        return "unknown"
    if employee_count < SMALL_BELOW:
        return "small"
    if employee_count >= LARGE_FROM:
        return "large"
    return "mid"


LABELS: dict[str, str] = {
    "small": f"Small (under {SMALL_BELOW})",
    "mid": f"Mid ({SMALL_BELOW}–{LARGE_FROM - 1})",
    "large": f"Large ({LARGE_FROM}+)",
    "unknown": "Unknown headcount",
}


@dataclass(frozen=True)
class HeadcountChange:
    """What a fresh observation did to the stored one."""

    #: `first` — nothing was known. `same` — re-observed, unchanged.
    #: `changed` — a real move, and the only one worth a signal.
    outcome: Literal["first", "same", "changed", "ignored"]
    before: int | None = None
    after: int | None = None
    #: Days between the two observations. `None` unless something changed and
    #: both dates are known — a delta without a window is not a growth rate.
    over_days: int | None = None

    @property
    def delta(self) -> int | None:
        if self.outcome != "changed" or self.before is None or self.after is None:
            return None
        return self.after - self.before


def record_headcount(
    account, count: int | None, *, observed_on: date | None = None
) -> HeadcountChange:
    """Store a headcount observation, keeping the number it replaced.

    One place decides what an observation means, because the rule is not
    obvious and was previously absent altogether: `resolution` wrote the count
    **only when the field was empty**, so a second run never refreshed it,
    nothing recorded when it was true, and a change would have destroyed the
    value it replaced. A delta was uncomputable however good the source.

    The rule:

    * nothing known yet — store it and date it;
    * the same number again — refresh the date only. We looked and it had not
      moved, which is information, and overwriting `before` with an identical
      value would collapse the window a real change is measured over;
    * a different number — the current value becomes `before` with its own
      date, and the new one takes its place.

    `observed_on` defaults to today and is **ours, not theirs**: a directory
    page or a company profile carries no date, so the only honest timestamp is
    when we looked.

    A `None` count is ignored rather than clearing the field. Every source
    returns `None` for "I do not know", and letting that erase a number we hold
    would make the stored value depend on which source happened to answer last.
    """
    if count is None or count < 0:
        return HeadcountChange(outcome="ignored", before=account.employee_count)

    today = observed_on or datetime.now(UTC).date()
    current = account.employee_count

    if current is None:
        account.employee_count = count
        account.employee_count_as_of = today
        return HeadcountChange(outcome="first", after=count)

    if current == count:
        account.employee_count_as_of = today
        return HeadcountChange(outcome="same", before=current, after=count)

    was_on = account.employee_count_as_of
    account.employee_count_before = current
    account.employee_count_before_as_of = was_on
    account.employee_count = count
    account.employee_count_as_of = today
    return HeadcountChange(
        outcome="changed",
        before=current,
        after=count,
        over_days=(today - was_on).days if was_on else None,
    )
