"""LinkedIn, understood through the URLs that point at it. Never fetched.

LinkedIn's robots.txt forbids automated access without its permission, and its
user agreement bans scraping outright — hiQ ended in a $500,000 judgment and
Proxycurl shut down after being sued. So nothing in this product requests a
linkedin.com page, logged in or out.

What it can do is understand a LinkedIn URL it meets somewhere else — a link
in a company's own homepage footer, a search result, a post a rep pasted:

* **Which company page or person it belongs to.** A passage from a different
  company's page, or a namesake's profile, is dropped rather than filed under
  this account — the same wrong-person failure contact research guards against.
* **When a post was published.** A LinkedIn activity id is a 64-bit number whose
  top 41 bits are milliseconds since the Unix epoch, so the date is written into
  the URL. A search snippet of a post carries no date of its own; this gives it
  one without opening the page.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from urllib.parse import unquote, urlsplit

#: Nothing on LinkedIn predates its launch; a decoded date before this, or in
#: the future, means the number was not an activity id.
EARLIEST = date(2003, 5, 5)

_ACTIVITY = re.compile(r"activity[-:](\d{18,20})", re.I)
_COMPANY_LINK = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[A-Za-z0-9_%.-]+/?", re.I
)


def is_linkedin(url: str | None) -> bool:
    if not url:
        return False
    host = urlsplit(url.strip()).netloc.lower()
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def post_date(url: str | None, *, today: date | None = None) -> date | None:
    """When a LinkedIn post was published, read from its URL. None if unknown."""
    if not is_linkedin(url):
        return None
    match = _ACTIVITY.search(url or "")
    if not match:
        return None
    millis = int(match.group(1)) >> 22
    try:
        published = datetime.fromtimestamp(millis / 1000, tz=UTC).date()
    except (OverflowError, OSError, ValueError):
        return None
    today = today or datetime.now(UTC).date()
    return published if EARLIEST <= published <= today else None


def _segments(url: str | None) -> list[str]:
    if not url:
        return []
    return [unquote(s) for s in urlsplit(url.strip()).path.split("/") if s]


def company_slug(url: str | None) -> str | None:
    """`bluewave` from linkedin.com/company/bluewave/…"""
    parts = _segments(url)
    if is_linkedin(url) and len(parts) >= 2 and parts[0].lower() == "company":
        return parts[1].lower()
    return None


def person_slug(url: str | None) -> str | None:
    """`danareid` from linkedin.com/in/danareid/…"""
    parts = _segments(url)
    if is_linkedin(url) and len(parts) >= 2 and parts[0].lower() == "in":
        return parts[1].lower()
    return None


def post_author(url: str | None) -> str | None:
    """Whose post it is: the vanity name before the first underscore.

    linkedin.com/posts/bluewave-technology-group_ai-networks-activity-7351…
    is the company page `bluewave-technology-group`; a member's post carries the
    member's vanity name in the same place.
    """
    parts = _segments(url)
    if is_linkedin(url) and len(parts) >= 2 and parts[0].lower() == "posts":
        return parts[1].split("_", 1)[0].lower() or None
    return None


#: The disambiguating tail LinkedIn appends to a public identifier when the
#: plain vanity name is taken — `apoorv-bhargava-94100842`.
_PUBLIC_ID_TAIL = re.compile(r"-[0-9a-f]{6,}$", re.I)


def same_slug(a: str | None, b: str | None) -> bool:
    """Whether two LinkedIn slugs name the same person, suffix or no suffix.

    **One person has two spellings and providers disagree about which to store.**
    Apollo gave us `/in/apoorv-bhargava-94100842`; his own post is at
    `/posts/apoorv-bhargava_…`. An exact comparison says those are two people,
    and the first measurement of post authorship duly reported *zero* employees
    among forty-five authors — a number produced entirely by this mismatch.

    So the tail comes off both sides before comparing. It is only ever a
    *disambiguator*: LinkedIn adds it when the plain name is taken, which means
    stripping it can in principle merge two people who share a name. That is
    accepted here because the comparison is always made within one account —
    two same-named people at one company is rarer than two spellings of one
    person, which is universal.
    """
    if not a or not b:
        return False
    a, b = a.lower(), b.lower()
    return a == b or _PUBLIC_ID_TAIL.sub("", a) == _PUBLIC_ID_TAIL.sub("", b)


def belongs(
    url: str | None, *, company_url: str | None = None, person_url: str | None = None
) -> bool | None:
    """Whether a LinkedIn URL is this company's page or this person's.

    None when it cannot be told: not a LinkedIn URL, nothing on record to compare
    with, or a LinkedIn page that names no owner (an article, a job). Only False
    is grounds to drop a passage — an unanswerable question is not a mismatch.
    """
    if not is_linkedin(url):
        return None
    wanted = [s for s in (company_slug(company_url), person_slug(person_url)) if s]
    if not wanted:
        return None
    found = company_slug(url) or person_slug(url) or post_author(url)
    if found is None:
        return None
    return any(same_slug(found, w) for w in wanted)


def company_pages(page: str | None) -> list[str]:
    """LinkedIn company pages a web page links to, normalised, in order."""
    from app.services.resolution import normalise_linkedin

    found: list[str] = []
    for match in _COMPANY_LINK.finditer(page or ""):
        normalised = normalise_linkedin(match.group(0))
        if normalised:
            found.append(normalised)
    return list(dict.fromkeys(found))
