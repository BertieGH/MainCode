"""Cheap, regex-based country detection from article text or Signal.location.

Used at ingest time to tag every Article with an ISO-2 country code without
spending an LLM call. Articles that don't match any preset get country="" and
can be filled in later via the LLM backfill endpoint.

Tokens are matched case-insensitively with word boundaries so e.g. "USA"
doesn't accidentally match "Susan", " UK " doesn't match "lookup", and the
2-letter state code "CA" only counts when standing alone (not "California").

The preset is intentionally hardcoded — tweak this file when adding countries.
"""
from __future__ import annotations

import re

# Each entry is (country_code, list_of_keyword_tokens). Order is significant only
# for tie-breaks (first wins on equal scores). State 2-letter codes are split out
# so they can be matched only with the strict word-boundary regex.
COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "US": [
        "United States", "U.S.", "USA", "American",
        # Top US cities
        "San Francisco", "New York", "Boston", "Los Angeles", "Chicago",
        "Seattle", "Austin", "Denver", "Atlanta", "Miami", "Dallas",
        "Houston", "Philadelphia", "Washington DC", "Washington, D.C.",
        "Brooklyn", "Manhattan", "Silicon Valley", "Palo Alto",
        "Mountain View", "Cambridge, MA", "San Diego", "Portland",
        "Minneapolis", "Pittsburgh", "Nashville", "Phoenix",
        # State names (selected — most-mentioned in funding press)
        "California", "Massachusetts", "Texas", "Florida", "Washington state",
    ],
    "GB": [
        "United Kingdom", "U.K.", "Britain", "British", "England", "Scotland",
        "London", "Manchester", "Edinburgh", "Cambridge, UK", "Oxford",
        "Bristol", "Glasgow", "Birmingham, UK",
    ],
    "IN": [
        "India", "Indian", "Bengaluru", "Bangalore", "Mumbai", "New Delhi",
        "Delhi", "Hyderabad", "Chennai", "Pune", "Gurgaon", "Gurugram", "Noida",
    ],
    "CA": [
        "Canada", "Canadian", "Toronto", "Vancouver", "Montreal", "Ottawa",
        "Calgary", "Waterloo", "Quebec",
    ],
    "DE": [
        "Germany", "German", "Berlin", "Munich", "Hamburg", "Frankfurt",
    ],
    "FR": [
        "France", "French", "Paris", "Lyon",
    ],
    "IL": [
        "Israel", "Israeli", "Tel Aviv", "Herzliya",
    ],
    "SG": [
        "Singapore", "Singaporean",
    ],
    "AU": [
        "Australia", "Australian", "Sydney", "Melbourne", "Brisbane",
    ],
    "NL": [
        "Netherlands", "Dutch", "Amsterdam", "Rotterdam",
    ],
    "IE": [
        "Ireland", "Irish", "Dublin",
    ],
}

# Strict 2-letter US state codes — only counted with `\b<code>\b` so we don't
# false-match every word that happens to contain the letters.
US_STATE_CODES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY",
]


# Pre-compile one regex per country at import time. Each pattern is built as
# `\b(?:tok1|tok2|...)\b` with re.IGNORECASE; tokens with punctuation (e.g.
# "U.S.") get the punctuation escaped.
def _build_pattern(tokens: list[str]) -> re.Pattern[str]:
    parts = sorted({re.escape(t) for t in tokens}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE)


_COUNTRY_PATTERNS: dict[str, re.Pattern[str]] = {
    code: _build_pattern(toks) for code, toks in COUNTRY_KEYWORDS.items()
}
# US states get their own pattern with case-sensitive matching to avoid
# false positives on common short words (e.g. "in", "or", "me").
_US_STATE_PATTERN = re.compile(r"\b(?:" + "|".join(US_STATE_CODES) + r")\b")


KNOWN_COUNTRY_CODES: set[str] = set(COUNTRY_KEYWORDS.keys()) | {"Other"}


def _score_text(text: str) -> dict[str, int]:
    """Count word-bounded keyword hits per country in `text`."""
    if not text:
        return {}
    scores: dict[str, int] = {}
    for code, pat in _COUNTRY_PATTERNS.items():
        n = len(pat.findall(text))
        if n:
            scores[code] = n
    # US state codes (case-sensitive) supplement the US score.
    n_states = len(_US_STATE_PATTERN.findall(text))
    if n_states:
        scores["US"] = scores.get("US", 0) + n_states
    return scores


def _best_country(scores: dict[str, int]) -> str:
    if not scores:
        return ""
    return max(scores.items(), key=lambda kv: (kv[1], -list(COUNTRY_KEYWORDS).index(kv[0])))[0]


def detect_country_from_text(title: str, summary: str) -> str:
    """Best-effort country code from article title + summary. Empty if no match."""
    return _best_country(_score_text(f"{title or ''}\n{summary or ''}"))


def detect_country_from_location(location: str) -> str:
    """Country code derived from a Signal's `location` field. More accurate than
    the article body since the location is already HQ-focused."""
    return _best_country(_score_text(location or ""))
