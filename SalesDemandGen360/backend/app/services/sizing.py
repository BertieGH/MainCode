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
