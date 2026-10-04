"""LinkedIn links a company publishes on its own website.

Enrichment asks Apollo for a contact's LinkedIn profile and, at identity
matching, for the company's page. When Apollo has neither, the company's own
site often does: a LinkedIn icon in the footer, a profile link beside each
person on a leadership page. That is the company saying which page and which
people are its own — first-hand, and nothing on LinkedIn is fetched to learn it.

**Only an unambiguous link is taken.**

* A company page when the site links **exactly one**. BlueWave's homepage links
  two (`company/bluewave` and `company/bluewavetg`); guessing between them
  would identify the account by what may be someone else's page.
* A person's profile when **exactly one** profile on the site matches their
  name — by the profile's address (`/in/seth-penland`) or the link's own text or
  title. Not by the text *near* a link: on a team grid the name beside one icon
  is often the previous person's, and filing a colleague's profile under a
  contact is the wrong-person failure enrichment exists to prevent.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urljoin

from app.services import linkedin
from app.services.site_sweep import _get, allowed, answers, client

#: Where a company publishes its people. The homepage comes first because the
#: footer carries the company page on almost every site.
PATHS = (
    "/", "/about", "/about-us", "/team", "/our-team", "/leadership",
    "/company/leadership", "/people",
)
#: Pages read at most per site. BlueWave's leadership page, with fourteen
#: profile links, was found within eight.
MAX_PAGES = 8

_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Profile:
    #: `https://www.linkedin.com/in/<slug>` — one spelling per person.
    url: str
    #: The link's own words: its text, `title` and `aria-label`.
    label: str


@dataclass
class SiteLinks:
    answered: bool = True
    pages_read: int = 0
    company_pages: list[str] = field(default_factory=list)
    profiles: list[Profile] = field(default_factory=list)


def _fold(text: str | None) -> str:
    """Lower-case ASCII, so "Sophia Al-Mansoor" and "sophia-almansoor" compare."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def profiles_in(page: str | None) -> list[Profile]:
    """LinkedIn profile links on a page, with each link's own words."""
    found: list[Profile] = []
    for attrs_text, inner in _ANCHOR.findall(page or ""):
        attrs = {k.lower(): v for k, v in _ATTR.findall(attrs_text)}
        slug = linkedin.person_slug(attrs.get("href"))
        if not slug:
            continue
        words = " ".join(
            part
            for part in (attrs.get("title"), attrs.get("aria-label"), _TAGS.sub(" ", inner))
            if part and part.strip().lower() != "linkedin"
        )
        found.append(Profile(f"https://www.linkedin.com/in/{slug}", _WS.sub(" ", words).strip()))
    return found


def _name_tokens(full_name: str) -> tuple[str, str] | None:
    tokens = [t for t in re.split(r"[^a-z]+", _fold(full_name)) if t]
    if len(tokens) < 2 or len(tokens[0]) < 2 or len(tokens[-1]) < 3:
        # A single name, or an initial, matches far too much to be evidence.
        return None
    return tokens[0], tokens[-1]


def names(full_name: str, profile: Profile) -> bool:
    """Whether a profile link is plainly this person's."""
    parts = _name_tokens(full_name)
    if parts is None:
        return False
    first, last = parts
    squashed = re.sub(r"[^a-z]", "", _fold(linkedin.person_slug(profile.url)))
    if first in squashed and last in squashed:
        return True
    words = set(re.split(r"[^a-z]+", _fold(profile.label)))
    return first in words and last in words


def profile_for(full_name: str, profiles: list[Profile]) -> str | None:
    """The one profile on the site that is this person's, or None."""
    matches = {p.url for p in profiles if names(full_name, p)}
    return next(iter(matches)) if len(matches) == 1 else None


def company_page(links: SiteLinks) -> str | None:
    return links.company_pages[0] if len(links.company_pages) == 1 else None


async def read_site(domain: str, *, http=None) -> SiteLinks:
    """The LinkedIn company pages and profiles a company's own site links."""
    domain = (domain or "").strip().lower()
    result = SiteLinks()
    if not domain:
        result.answered = False
        return result

    own = http or client()
    owned = http is None
    try:
        robots: dict = {}
        if not await answers(own, domain, robots):
            result.answered = False
            return result
        home = f"https://{domain}/"
        pages: list[str] = []
        profiles: dict[str, Profile] = {}
        for path in PATHS:
            if result.pages_read >= MAX_PAGES:
                break
            url = urljoin(home, path.lstrip("/"))
            if not await allowed(own, url, robots):
                continue
            body = await _get(own, url)
            if not body:
                continue
            result.pages_read += 1
            pages.extend(linkedin.company_pages(body))
            for profile in profiles_in(body):
                # The same person linked twice — a card and a footer — keeps
                # the more descriptive of the two labels.
                held = profiles.get(profile.url)
                if held is None or len(profile.label) > len(held.label):
                    profiles[profile.url] = profile
        result.company_pages = list(dict.fromkeys(pages))
        result.profiles = list(profiles.values())
        return result
    finally:
        if owned:
            await own.aclose()
