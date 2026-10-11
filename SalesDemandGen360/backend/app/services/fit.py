"""Fit: does this account match the ICP it is worked for. Computed, not judged.

Fit used to be one of the six dimensions the model assessed, and it was the one
that least needed a model. Headcount, industry and country are columns on the
account; the ICP states the range, the industries and the regions it wants.
Comparing the two is arithmetic — and asking a model to do it produced exactly
the failure arithmetic cannot: BlueWave scored fit 75 on one run and 0 on the
next, from the same account and the same evidence, because the second time the
model did not happen to spot a passage it thought was about fit.

So fit is scored here and the model's fit is replaced whenever the list's ICPs
are known (invariant 7 — scores are computed in Python). What each factor can
say:

* **match** — the account is inside what the ICP asks for;
* **mismatch** — it is outside, and the reason names both sides;
* **unknown** — the ICP asks, but the account does not say. Not counted either
  way and always named, so "fit 100" on an account with no country reads as
  "100 of what we could check", not as a verified fit.

Industry matching follows `scoring.normalise_industry` and deliberately makes no
leaps: "Financial Services and Software" is not "Fintech" here, because that is
a judgement about two different words rather than two spellings of one. A
mismatch is printed with both sides so a rep can see when the ICP's vocabulary,
not the account, is what needs changing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.scoring import normalise_industry

#: The `basis` a computed fit is stored under. Distinct from `evidence`, since
#: nothing is cited, and from `no_evidence`, since something was checked.
FIRMOGRAPHICS = "firmographics"

#: The same arithmetic, but at least one value came from the researched
#: profile rather than a firmographic column. Kept apart because the two are
#: not equally strong: a column is what a provider or an import asserted, a
#: profile line is what a model read off a page. A rep deciding whether to
#: drop an account should be able to see which kind of fact decided it.
PROFILE = "firmographics_from_profile"

#: Where a value came from, for the reason string.
_FROM_PROFILE = " (from the researched profile)"

_EU = frozenset({
    "eu", "european union", "austria", "belgium", "bulgaria", "croatia", "cyprus",
    "czechia", "czech republic", "denmark", "estonia", "finland", "france", "germany",
    "greece", "hungary", "ireland", "italy", "latvia", "lithuania", "luxembourg",
    "malta", "netherlands", "poland", "portugal", "romania", "slovakia", "slovenia",
    "spain", "sweden",
})

#: ICP region chip → the country spellings that satisfy it. Keys are the
#: normalised chips the ICP editor suggests; a chip not listed here matches
#: only a country written the same way.
REGIONS: dict[str, frozenset[str]] = {
    "us": frozenset({
        "us", "usa", "u.s.", "u.s.a.", "united states", "united states of america",
    }),
    "uk": frozenset({
        "uk", "u.k.", "united kingdom", "gb", "great britain", "england", "scotland",
        "wales", "northern ireland",
    }),
    "canada": frozenset({"canada", "ca"}),
    "in": frozenset({"in", "india"}),
    "india": frozenset({"in", "india"}),
    "australia": frozenset({"australia", "au"}),
    "eu": _EU,
    "apac": frozenset({
        "australia", "new zealand", "india", "singapore", "japan", "china", "hong kong",
        "south korea", "korea", "taiwan", "indonesia", "malaysia", "philippines",
        "thailand", "vietnam",
    }),
    "mena": frozenset({
        "uae", "united arab emirates", "saudi arabia", "qatar", "kuwait", "bahrain",
        "oman", "egypt", "israel", "jordan", "morocco", "turkey",
    }),
    "latam": frozenset({
        "mexico", "brazil", "argentina", "chile", "colombia", "peru", "uruguay",
        "costa rica", "ecuador",
    }),
}


@dataclass(frozen=True)
class Check:
    factor: str
    #: `match`, `mismatch` or `unknown`.
    outcome: str
    detail: str


@dataclass(frozen=True)
class Fit:
    score: float
    basis: str
    reason: str
    icp: str | None = None
    checks: tuple[Check, ...] = ()

    def as_assessment(self) -> dict:
        """The shape every other dimension is stored in."""
        return {
            "score": self.score,
            "reason": self.reason,
            "evidence_ids": [],
            "basis": self.basis,
        }


def parse_employees(value: object) -> tuple[int, int | None] | None:
    """`"50-500"` or `"1000+"`, as the ICP editor writes them. None otherwise."""
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"\s*(\d+)\s*\+\s*", value)
    if m:
        return int(m.group(1)), None
    return None


def _profile(account) -> dict:
    row = getattr(account, "profile", None)
    return row if isinstance(row, dict) else {}


def profile_headcount(value: object) -> tuple[int, int] | None:
    """A headcount out of a profile's free-text size.

    Profiles say things like "Approx. 100-110 employees", "~2,000 staff" or
    "11-50". A range is kept as a range and compared by overlap rather than
    collapsed to one number: an account of 400-600 against an ICP wanting
    1-500 is a genuine partial, and picking either end would decide it by
    coincidence.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", value)]
    if not numbers:
        return None
    return min(numbers), max(numbers)


def _account_headcount(account) -> tuple[tuple[int, int] | None, bool]:
    """`((low, high), from_profile)`. The column wins when it has a value."""
    count = getattr(account, "employee_count", None)
    if isinstance(count, int) and count > 0:
        return (count, count), False
    return profile_headcount(_profile(account).get("size")), True


def _account_industries(account) -> tuple[list[str], bool]:
    """The column, else every industry the profile lists.

    A profile names several — "Productivity Software, SaaS, Business
    Software" — and any one of them matching the ICP is a match, the same
    way one industry on the column would be.
    """
    if isinstance(account.industry, str) and account.industry.strip():
        return [account.industry], False
    return _strings(_profile(account).get("industries_served")), True


def _account_places(account) -> tuple[list[str], bool]:
    """The country column, else the places the profile lists.

    Profile locations are written for people — "Porto, Portugal", "Fully
    distributed worldwide" — so each is also split on commas and the parts
    tried separately, which is how "Portugal" is found inside the first and
    nothing is found inside the second.
    """
    country = getattr(account, "hq_country", None)
    if isinstance(country, str) and country.strip():
        return [country], False
    places: list[str] = []
    for line in _strings(_profile(account).get("locations")):
        places.append(line)
        places.extend(part.strip() for part in line.split(",") if part.strip())
    return places, True


def _words_contain(haystack: str, needle: str) -> bool:
    """Whole-phrase containment, so "logistics" matches "logistics and supply
    chain" but "it" does not match "digital"."""
    return f" {needle} " in f" {haystack} "


def _strings(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _size(
    have: tuple[int, int] | None, band: object, *, from_profile: bool = False
) -> Check | None:
    if band in (None, "", []):
        return None
    parsed = parse_employees(band)
    if parsed is None:
        # An ICP range nobody can read constrains nothing. Said, not guessed at.
        return Check("size", "unknown", f"the ICP's size {band!r} is not a range this can read")
    low, high = parsed
    wanted = f"{low}+" if high is None else f"{low}-{high}"
    if have is None:
        return Check("size", "unknown", f"no headcount on the account to compare with {wanted}")
    got_low, got_high = have
    said = str(got_low) if got_low == got_high else f"{got_low}-{got_high}"
    # Overlap, not containment: a 400-600 account against a 1-500 ICP is a
    # real partial, and collapsing the range to one end would decide it by
    # which end was picked.
    inside = got_high >= low and (high is None or got_low <= high)
    source = _FROM_PROFILE if from_profile else ""
    return Check(
        "size",
        "match" if inside else "mismatch",
        f"{said} employees{source} is {'inside' if inside else 'outside'} {wanted}",
    )


def _industry(
    industries: list[str], wanted: list[str], *, from_profile: bool = False
) -> Check | None:
    if not wanted:
        return None
    listed = ", ".join(wanted)
    source = _FROM_PROFILE if from_profile else ""
    usable = [i for i in industries if normalise_industry(i)]
    if not usable:
        return Check("industry", "unknown", f"no industry on the account to compare with {listed}")
    for industry in usable:
        have = normalise_industry(industry)
        for w in wanted:
            key = normalise_industry(w)
            if have == key or _words_contain(have, key):
                return Check("industry", "match", f"industry {industry!r}{source} is {w}")
    had = ", ".join(repr(i) for i in usable)
    return Check("industry", "mismatch", f"industry {had}{source} is not one of {listed}")


def _region(
    places: list[str], wanted: list[str], *, from_profile: bool = False
) -> Check | None:
    if not wanted:
        return None
    listed = ", ".join(wanted)
    source = _FROM_PROFILE if from_profile else ""
    usable = [p for p in places if normalise_industry(p)]
    if not usable:
        return Check("region", "unknown", f"no country on the account to compare with {listed}")
    for place in usable:
        have = normalise_industry(place)
        for w in wanted:
            key = normalise_industry(w)
            if have in REGIONS.get(key, frozenset({key})):
                return Check("region", "match", f"{place}{source} is in {w}")
    # Named by the first place rather than all of them: a profile may list a
    # head office and three sentences about remote work, and a mismatch that
    # recites all four is unreadable.
    return Check("region", "mismatch", f"{usable[0]}{source} is not in {listed}")


def _excluded(industry: str | None, exclusions: list[str]) -> str | None:
    have = normalise_industry(industry)
    if not have:
        return None
    for ex in exclusions:
        key = normalise_industry(ex)
        if have == key or _words_contain(have, key):
            return ex
    return None


def assess(account, definition: dict, *, icp: str | None = None) -> Fit:
    """How well one account matches one ICP definition."""
    label = icp or "the ICP"
    industries, industry_from_profile = _account_industries(account)
    places, places_from_profile = _account_places(account)
    headcount, size_from_profile = _account_headcount(account)

    # The exclusion list runs over every industry known, profile included: an
    # account kept because the column that would have excluded it was empty
    # is the expensive kind of mistake.
    for industry in industries:
        excluded = _excluded(industry, _strings(definition.get("exclusions")))
        if excluded is not None:
            return Fit(
                score=0.0,
                basis=PROFILE if industry_from_profile else FIRMOGRAPHICS,
                reason=f"{label}: {industry!r} is on its do-not-target list ({excluded}).",
                icp=icp,
            )

    checks = tuple(
        c
        for c in (
            _size(headcount, definition.get("employees"), from_profile=size_from_profile),
            _industry(
                industries,
                _strings(definition.get("industries")),
                from_profile=industry_from_profile,
            ),
            _region(
                places,
                _strings(definition.get("regions")),
                from_profile=places_from_profile,
            ),
        )
        if c is not None
    )
    # The basis follows what actually decided the score. A profile value that
    # came back `unknown` decided nothing and must not downgrade a fit that
    # the columns settled.
    from_profile = {
        "size": size_from_profile,
        "industry": industry_from_profile,
        "region": places_from_profile,
    }
    basis = (
        PROFILE
        if any(from_profile.get(c.factor) and c.outcome != "unknown" for c in checks)
        else FIRMOGRAPHICS
    )
    if not checks:
        return Fit(
            score=100.0,
            basis=FIRMOGRAPHICS,
            reason=f"{label} sets no size, industry or region, so nothing rules this account out.",
            icp=icp,
        )

    known = [c for c in checks if c.outcome != "unknown"]
    detail = "; ".join(c.detail for c in checks)
    if not known:
        # Something was asked and nothing could be checked. A zero, declared as
        # absence rather than dressed up as a computed mismatch.
        return Fit(
            score=0.0,
            basis="no_evidence",
            reason=f"{label}: nothing on the account to compare — {detail}.",
            icp=icp,
            checks=checks,
        )

    matched = sum(1 for c in known if c.outcome == "match")
    score = round(100.0 * matched / len(known), 2)
    return Fit(
        score=score,
        basis=basis,
        reason=f"{label}: {detail}. Matched {matched} of {len(known)} that could be checked.",
        icp=icp,
        checks=checks,
    )


def best(account, icps: Sequence[tuple[str, dict]]) -> Fit | None:
    """The best fit across the ICPs a list is worked for, or None with none.

    Best rather than average: an account on a list worked for two ICPs needs to
    fit one of them, not both.
    """
    fits = [assess(account, definition or {}, icp=name) for name, definition in icps]
    if not fits:
        return None
    return max(fits, key=lambda f: f.score)
