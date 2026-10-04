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


def _words_contain(haystack: str, needle: str) -> bool:
    """Whole-phrase containment, so "logistics" matches "logistics and supply
    chain" but "it" does not match "digital"."""
    return f" {needle} " in f" {haystack} "


def _strings(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _size(count: int | None, band: object) -> Check | None:
    if band in (None, "", []):
        return None
    parsed = parse_employees(band)
    if parsed is None:
        # An ICP range nobody can read constrains nothing. Said, not guessed at.
        return Check("size", "unknown", f"the ICP's size {band!r} is not a range this can read")
    low, high = parsed
    wanted = f"{low}+" if high is None else f"{low}-{high}"
    if count is None:
        return Check("size", "unknown", f"no headcount on the account to compare with {wanted}")
    inside = count >= low and (high is None or count <= high)
    return Check(
        "size",
        "match" if inside else "mismatch",
        f"{count} employees is {'inside' if inside else 'outside'} {wanted}",
    )


def _industry(industry: str | None, wanted: list[str]) -> Check | None:
    if not wanted:
        return None
    listed = ", ".join(wanted)
    have = normalise_industry(industry)
    if not have:
        return Check("industry", "unknown", f"no industry on the account to compare with {listed}")
    for w in wanted:
        key = normalise_industry(w)
        if have == key or _words_contain(have, key):
            return Check("industry", "match", f"industry {industry!r} is {w}")
    return Check("industry", "mismatch", f"industry {industry!r} is not one of {listed}")


def _region(country: str | None, wanted: list[str]) -> Check | None:
    if not wanted:
        return None
    listed = ", ".join(wanted)
    have = normalise_industry(country)
    if not have:
        return Check("region", "unknown", f"no country on the account to compare with {listed}")
    for w in wanted:
        key = normalise_industry(w)
        if have in REGIONS.get(key, frozenset({key})):
            return Check("region", "match", f"{country} is in {w}")
    return Check("region", "mismatch", f"{country} is not in {listed}")


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
    excluded = _excluded(account.industry, _strings(definition.get("exclusions")))
    if excluded is not None:
        return Fit(
            score=0.0,
            basis=FIRMOGRAPHICS,
            reason=f"{label}: {account.industry!r} is on its do-not-target list ({excluded}).",
            icp=icp,
        )

    checks = tuple(
        c
        for c in (
            _size(account.employee_count, definition.get("employees")),
            _industry(account.industry, _strings(definition.get("industries"))),
            _region(getattr(account, "hq_country", None), _strings(definition.get("regions"))),
        )
        if c is not None
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
        basis=FIRMOGRAPHICS,
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
