"""Deciding whether a contact is somebody an ICP wants to reach.

The first version was a casefolded substring test: does any target string
appear anywhere in the contact's title, persona role, buying role or seniority?
It ran, it reported honestly, and on a real list it excluded **every** contact:

    Bertie          "vp"          does not match what EIA targets
    vinoo Selvaraj  "President"   does not match what EIA targets

The second version fixed that by expanding abbreviations and comparing rank
and function — and then let the wrong people in. Against targets of
`CEO, CTO, CIO, IT head` it admitted a VP of Sales, a VP of Business
Development and a Chief Security Officer, and left out a Managing Director:

* `VP` expanded to `vice president`, and `president` on its own ranks as a
  CEO. A target of `CEO` named no function, so it was read as "anyone at chief
  level" — which a VP now reached.
* `Chief Security Officer` was chief level too, by the same route.
* `development` meant engineering, so `Business Development` was a tech title.
* `Managing Director` ranked as a director, well below a CEO.

So this version works on **phrases**, not words:

* Multi-word titles collapse to one token first — `vice president` → `vp`,
  `managing director` → `md`, `chief technology officer` → `cto`,
  `business development` → `bizdev` — so a word inside a phrase can no longer
  be read on its own.
* Running the company is a **function** of its own (`general`): CEO,
  president, managing director, founder, owner, general manager. A target of
  `CEO` asks for that function, not for any title at chief level.
* A title naming a **different** function never matches. `Head of Sales` does
  not answer `IT head`; `VP of Sales` does not answer `CEO`.
* A title naming **no** function — a bare `VP`, `Partner` — is judged on rank
  alone, and must reach the target's rank without slack. Seniority is all it
  says; refusing it would drop real buyers whose titles were imported short.

Deterministic on purpose. A model call per contact is still the deeper fix for
genuinely odd titles, but these misses were vocabulary, not judgement — and a
table is cheaper, faster, and inspectable when it gets something wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The closed set a persona's buying role comes from — `contact.buying_role_valid`.
#: A target in this set is matched against a contact's buying role, exactly,
#: and never against a title: "technical_buyer" is not a job anybody holds.
BUYING_ROLES = frozenset(
    {"economic_buyer", "technical_buyer", "champion", "influencer", "blocker"}
)

#: Multi-word titles collapsed to one token before anything else is read.
#: Longest first, so `senior vice president` is not read as `senior` + `vp`.
PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("chief", "information", "security", "officer"), "ciso"),
    (("chief", "executive", "officer"), "ceo"),
    (("chief", "technology", "officer"), "cto"),
    (("chief", "technical", "officer"), "cto"),
    (("chief", "information", "officer"), "cio"),
    (("chief", "operating", "officer"), "coo"),
    (("chief", "operations", "officer"), "coo"),
    (("chief", "financial", "officer"), "cfo"),
    (("chief", "finance", "officer"), "cfo"),
    (("chief", "marketing", "officer"), "cmo"),
    (("chief", "revenue", "officer"), "cro"),
    (("chief", "data", "officer"), "cdo"),
    (("chief", "product", "officer"), "cpo"),
    (("chief", "security", "officer"), "ciso"),
    (("executive", "vice", "president"), "evp"),
    (("senior", "vice", "president"), "svp"),
    (("assistant", "vice", "president"), "avp"),
    (("vice", "president"), "vp"),
    (("managing", "director"), "md"),
    (("general", "manager"), "gm"),
    (("business", "development"), "bizdev"),
    (("information", "technology"), "it"),
    (("human", "resources"), "hr"),
    (("quality", "assurance"), "qa"),
    (("co", "founder"), "cofounder"),
    # M&A and strategy, not engineering. With `corporate` dropped as noise,
    # `development` alone read as tech, and Apollo's SVP Corporate Development
    # at BlueWave was suggested as a technical buyer.
    (("corporate", "development"), "bizdev"),
)

#: How senior a token is. Used to compare two titles, not to score a person.
SENIORITY: dict[str, int] = {
    "ceo": 5, "cto": 5, "cio": 5, "coo": 5, "cfo": 5, "ciso": 5, "cmo": 5,
    "cro": 5, "cdo": 5, "cpo": 5, "chief": 5, "president": 5, "md": 5,
    "founder": 5, "cofounder": 5, "owner": 5,
    "evp": 4, "svp": 4, "vp": 4, "gm": 4, "partner": 4, "principal": 4,
    "avp": 3, "director": 3, "head": 3,
    "manager": 2, "lead": 2,
    "senior": 1, "engineer": 1, "analyst": 1, "associate": 1, "assistant": 1,
    "intern": 0,
}

#: Which area of the business a token belongs to. `general` is running the
#: company — the CEO's function, which no other chief title shares.
FUNCTIONS: dict[str, str] = {
    # running the company
    "ceo": "general", "president": "general", "md": "general", "gm": "general",
    "founder": "general", "cofounder": "general", "owner": "general",
    # chief titles, by what they are chief of
    "cto": "tech", "cio": "tech", "ciso": "security", "cdo": "data",
    "cfo": "finance", "cmo": "marketing", "cro": "sales", "coo": "ops",
    "cpo": "product",
    # technology
    "technology": "tech", "technical": "tech", "tech": "tech", "it": "tech",
    "information": "tech", "engineering": "tech", "software": "tech",
    "development": "tech", "digital": "tech", "eng": "tech", "dev": "tech",
    "sw": "tech", "sre": "tech", "infrastructure": "tech", "cloud": "tech",
    "data": "data", "analytics": "data", "science": "data",
    "security": "security", "infosec": "security", "cyber": "security",
    "cybersecurity": "security",
    "product": "product", "pm": "product",
    "marketing": "marketing", "growth": "marketing", "brand": "marketing",
    "sales": "sales", "revenue": "sales", "commercial": "sales",
    "bizdev": "sales", "partnerships": "sales", "account": "sales",
    "finance": "finance", "financial": "finance", "accounting": "finance",
    "people": "hr", "hr": "hr", "talent": "hr", "recruiting": "hr",
    "recruitment": "hr",
    "operations": "ops", "operating": "ops", "delivery": "ops", "ops": "ops",
    "quality": "quality", "qa": "quality", "testing": "quality",
}

#: Words that carry no meaning for matching. `head of engineering` and
#: `head, engineering` are the same job.
NOISE = {
    "of", "the", "and", "a", "an", "for", "at", "in", "to", "&",
    "global", "group", "corporate", "regional", "worldwide",
}

_SPLIT = re.compile(r"[^a-z0-9+]+")
_LONGEST = max(len(p) for p, _ in PHRASES)
_BY_PHRASE = {p: t for p, t in PHRASES}


def tokens(text: str | None) -> list[str]:
    """A title reduced to comparable tokens, multi-word titles collapsed."""
    if not text:
        return []
    words = [w for w in _SPLIT.split(text.casefold()) if w]
    # Phrases are read before noise is dropped — `corporate development` has a
    # noise word in it — and again after, so `chief information and security
    # officer` still collapses as it did.
    return _collapse([w for w in _collapse(words) if w not in NOISE])


def _collapse(words: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(words):
        for size in range(min(_LONGEST, len(words) - i), 1, -1):
            token = _BY_PHRASE.get(tuple(words[i : i + size]))
            if token:
                out.append(token)
                i += size
                break
        else:
            out.append(words[i])
            i += 1
    return out


def rank(words: list[str]) -> int:
    """The seniority a title implies. 0 when it says nothing about level."""
    return max((SENIORITY.get(w, 0) for w in words), default=0)


def functions(words: list[str]) -> set[str]:
    """Which areas of the business a title touches."""
    return {FUNCTIONS[w] for w in words if w in FUNCTIONS}


@dataclass(frozen=True)
class _Title:
    words: frozenset[str]
    rank: int
    functions: frozenset[str]


def _read(text: str | None) -> _Title:
    words = tokens(text)
    return _Title(frozenset(words), rank(words), frozenset(functions(words)))


def matches(title: str | None, target: str) -> bool:
    """Does `title` describe somebody the `target` persona was asking for?

    Both are free text — a target may be `IT head`, `CTO`, or `President` —
    so this compares meaning rather than spelling.
    """
    want, have = _read(target), _read(title)
    if not want.words or not have.words:
        return False

    # The cheap case, and the common one: `cto` in `founder cto`.
    if want.words <= have.words:
        return True

    if want.functions:
        if have.functions:
            # Both name a job, and it has to be the same job. This is the rule
            # that keeps `VP of Sales` out of a search for a CEO.
            if not (want.functions & have.functions):
                return False
            if not want.rank:
                return True
            # One step of slack within a function: a target of `IT head` reaches
            # a director or VP of technology, because org charts disagree.
            return have.rank >= want.rank - 1
        # The title names no function at all — `VP`, `Partner`. Judged on rank
        # alone and without slack: seniority is all it says.
        return bool(want.rank) and have.rank >= want.rank

    # A target naming only a rank — `VP`, `Director` — is asking about level.
    if want.rank:
        return have.rank >= want.rank
    return False


def matches_any(title: str | None, targets: tuple[str, ...] | list[str]) -> bool:
    return any(matches(title, t) for t in targets if t)
