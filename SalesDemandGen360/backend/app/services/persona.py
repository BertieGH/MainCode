"""Title normalisation — seniority, persona role, and buying role.

One shared taxonomy so the Strategy layer's persona weighting and the Buyer
dimension always agree on who somebody is. "VP Eng", "Head of Engineering", and
"Engineering Lead" have to resolve to the same persona or the two disagree
silently and nobody can tell which is right.

Deterministic and dependency-free: no LLM call to classify a job title.
"""

from __future__ import annotations

import re

# Order matters — the first match wins, so more senior patterns come first.
# "VP of Engineering" must not match the 'manager' pattern on the word "of".
# Checked before everything else. "Vice President" contains "president", which
# is a C-level needle, so without this every VP was classified as C-level — and
# the persona key for the same person differed depending on how their title was
# written.
DEMOTIONS: tuple[tuple[str, str], ...] = (
    ("vice president", "vp"),
)

SENIORITY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (
        "c_level",
        (
            "chief", "ceo", "cto", "cfo", "coo", "cmo", "cio", "ciso", "cpo", "cro",
            "chief executive", "chief technology", "chief information", "chief financial",
            "founder", "co-founder", "cofounder", "president", "managing director",
            "owner", "partner",
        ),
    ),
    ("vp", ("vice president", "vp", "svp", "evp", "head of")),
    ("director", ("director",)),
    ("manager", ("manager", "team lead", "lead")),
    (
        "ic",
        (
            "engineer", "analyst", "specialist", "coordinator", "designer",
            "developer", "associate", "consultant", "architect",
        ),
    ),
]

BUYING_ROLE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    # Blockers are checked first: a "Director of Procurement" is a blocker, not
    # a champion, and the department is what decides that.
    ("blocker", ("procurement", "legal", "general counsel", "compliance", "infosec",
                 "information security", "purchasing")),
    ("economic_buyer", ("ceo", "cfo", "coo", "president", "founder", "co-founder",
                        "managing director", "owner", "chief executive", "chief financial",
                        "chief operating")),
    ("technical_buyer", ("cto", "vp engineering", "vp of engineering", "head of platform",
                         "head of engineering", "chief architect", "cio",
                         "chief technology", "chief information")),
]

DEPARTMENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("engineering", ("engineer", "engineering", "platform", "infrastructure", "devops",
                     "software", "technical", "architect", "cto", "sre")),
    ("product", ("product", "cpo", "ux", "design")),
    ("data", ("data", "analytics", "machine learning", "ml ")),
    ("it", ("cio", "chief information", "information technology", "it", "helpdesk")),
    ("security", ("security", "ciso", "infosec")),
    ("sales", ("sales", "revenue", "account executive", "business development", "cro")),
    ("marketing", ("marketing", "growth", "demand gen", "cmo", "brand")),
    ("finance", ("finance", "cfo", "accounting", "controller")),
    ("operations", ("operations", "coo", " ops")),
    ("executive", ("ceo", "founder", "president", "owner", "managing director")),
]


# Each C-suite key with every spelling that means it.
C_SUITE_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cto", ("cto", "chief technology")),
    ("cio", ("cio", "chief information")),
    ("ciso", ("ciso", "chief information security")),
    ("ceo", ("ceo", "chief executive")),
    ("cfo", ("cfo", "chief financial")),
    ("coo", ("coo", "chief operating")),
    ("cmo", ("cmo", "chief marketing")),
)


def _normalise(title: str) -> str:
    return f" {re.sub(r'[^a-z0-9 &/-]', ' ', title.lower())} "


# Compiled once. Word-boundary matching is not a nicety here: plain substring
# matching classified every "Director" as C-level, because "dire(cto)r" contains
# "cto". The same bug put "Director of Marketing" in the engineering department.
_CACHE: dict[str, re.Pattern[str]] = {}


def _pattern(needle: str) -> re.Pattern[str]:
    if needle not in _CACHE:
        _CACHE[needle] = re.compile(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])")
    return _CACHE[needle]


def _matches(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(_pattern(n).search(haystack) for n in needles)


def classify_seniority(title: str | None) -> str:
    if not title:
        return "unknown"
    t = _normalise(title)
    for needle, level in DEMOTIONS:
        if _pattern(needle).search(t):
            return level
    for level, needles in SENIORITY_PATTERNS:
        if _matches(t, needles):
            return level
    return "unknown"


def classify_department(title: str | None) -> str | None:
    if not title:
        return None
    t = _normalise(title)
    for dept, needles in DEPARTMENT_PATTERNS:
        if _matches(t, needles):
            return dept
    return None


def classify_buying_role(title: str | None) -> str | None:
    """Economic buyer, technical buyer, champion, influencer, or blocker.

    Champion is deliberately *not* a keyword match. It is a VP or Director in
    the department that feels the pain — which the title alone cannot settle, so
    it falls out of seniority plus department rather than a word list.
    """
    if not title:
        return None
    t = _normalise(title)

    for role, needles in BUYING_ROLE_PATTERNS:
        if _matches(t, needles):
            return role

    seniority = classify_seniority(title)
    if seniority in ("vp", "director"):
        return "champion"
    if seniority in ("manager", "ic"):
        return "influencer"
    return None


def persona_role(title: str | None) -> str | None:
    """A stable key such as ``vp_engineering`` or ``cto``.

    Built from seniority and department rather than the raw title, so
    "VP Eng", "Head of Engineering", and "VP, Engineering" collapse to one key.
    """
    if not title:
        return None
    seniority = classify_seniority(title)
    dept = classify_department(title)

    t = _normalise(title)
    # "CIO" and "Chief Information Officer" are the same persona and must yield
    # the same key, or the Learning layer counts them as two different people.
    for short, spellings in C_SUITE_KEYS:
        if _matches(t, spellings):
            return short

    if seniority == "unknown":
        return None
    if dept is None:
        return seniority
    return f"{seniority}_{dept}"


def classify(title: str | None) -> dict[str, str | None]:
    """Everything at once — what the import path and enrichment both call."""
    return {
        "seniority": classify_seniority(title),
        "department": classify_department(title),
        "buying_role": classify_buying_role(title),
        "persona_role": persona_role(title),
    }
