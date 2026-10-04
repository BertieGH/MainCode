"""What a company's own domain says about who it is.

Resolution confirmed a company only when Apollo held its domain, and otherwise
asked a model — which may not confirm the domain it was shown. So a real
company on a correct domain that Apollo happened not to hold could never be
confirmed, and a domain that does not exist at all was reported only as "no
source could identify this company". On the Test Data list eight of twelve
domains had no DNS record, three were registered with nothing answering, and
one redirected to another company's site — and none of that was said.

This reads what the domain itself says, for free: whether it exists (DNS),
whether a website answers, where it lands after redirects, whether it is a
parked page, and what name the homepage gives — `og:site_name`,
`application-name`, `<title>`. A homepage on the row's own domain that names
the company is the evidence a rep would look for, and it is independent of the
row: the row supplied the domain, not what the site calls itself.

Page text is data, never instructions — only names and links are read out of
it, and nothing from it reaches a prompt.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import unicodedata
from dataclasses import dataclass, field

from app.services import linkedin
from app.services.resolution import normalise_domain
from app.services.site_sweep import allowed, client

log = logging.getLogger(__name__)

#: One homepage read. A site that has not answered in this long is not the
#: company's working website.
TIMEOUT_SECONDS = 8.0
#: Enough of a page to hold its head, without reading a whole single-page app.
READ_CHARS = 200_000

_PARKED = re.compile(
    r"(domain (name )?(is|may be) for sale|buy this domain|this domain is parked"
    r"|parked (free|domain)|hugedomains\.com|sedoparking|sedo\.com|dan\.com/|afternic"
    r"|parkingcrew|bodis\.com)",
    re.I,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""")
#: "Apex Cybersecurity | Enhance Security Today" names the company before the bar.
_SEPARATOR = re.compile(r"\s+[|\-–—:·•]\s+")

#: Where a page names its site, strongest first.
SITE_NAME_META = ("og:site_name", "application-name")
TITLE_META = ("og:title", "twitter:title")
GENERIC = frozenset({
    "home", "homepage", "home page", "welcome", "index", "untitled", "coming soon",
    "under construction", "website", "site", "page not found", "404",
})

#: Registration suffixes — never what distinguishes a company.
LEGAL = frozenset({
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
    "gmbh", "plc", "pvt", "pte", "sa", "ag", "bv", "srl", "llp", "lp", "the",
})
#: Words that say what kind of company rather than which one. "BrightByte
#: Software" is the brand BrightByte; "Cloud Solutions" alone names nobody, so
#: when every word is one of these they all count.
DESCRIPTORS = frozenset({
    "software", "solutions", "solution", "systems", "system", "technologies", "technology",
    "tech", "labs", "lab", "group", "global", "cloud", "platforms", "platform", "analytics",
    "digital", "services", "service", "consulting", "partners", "holdings", "international",
    "ai", "io", "hq", "and", "of",
})


@dataclass
class SiteIdentity:
    domain: str
    #: The domain has a DNS record (itself or `www.`).
    exists: bool = False
    #: A website answered at all, over HTTPS or HTTP.
    answered: bool = False
    status: int | None = None
    #: Where the homepage landed after redirects.
    final_domain: str | None = None
    parked: bool = False
    #: What the homepage calls the site, strongest first.
    names: list[str] = field(default_factory=list)
    company_pages: list[str] = field(default_factory=list)

    @property
    def redirected(self) -> bool:
        """Landed on another domain — not merely `www.` or a subdomain of this one."""
        return bool(self.final_domain) and self.final_domain != self.domain and not (
            self.final_domain.endswith("." + self.domain)
        )

    @property
    def calls_itself(self) -> str | None:
        return self.names[0] if self.names else None


def _fold(text: str | None) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().casefold()


def tokens(text: str | None) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _fold(text)) if t not in LEGAL]


def names_in(page: str | None) -> list[str]:
    """The names a homepage gives itself, strongest first, split at title separators."""
    head = (page or "")[:READ_CHARS]
    site_names: list[str] = []
    titles: list[str] = []
    for tag in _META.findall(head):
        attrs = {k.lower(): v for k, v in _ATTR.findall(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if not attrs.get("content"):
            continue
        if key in SITE_NAME_META:
            site_names.append(attrs["content"])
        elif key in TITLE_META:
            titles.append(attrs["content"])
    title = _TITLE.search(head)
    if title:
        titles.append(title.group(1))

    out: list[str] = []
    for raw in (*site_names, *titles):
        text = " ".join(html.unescape(raw).split())
        pieces = _SEPARATOR.split(text)
        # The piece before the separator first: it is where a title names the company.
        for part in (*pieces, text) if len(pieces) > 1 else (text,):
            part = part.strip()
            if part and len(part) <= 120 and part.casefold() not in GENERIC and part not in out:
                out.append(part)
    return out


def name_matches(company: str | None, names: list[str]) -> bool:
    """Whether any of a site's names is plainly this company's."""
    want = tokens(company)
    if not want:
        return False
    core = [t for t in want if t not in DESCRIPTORS] or want
    dropped = len(core) < len(want)
    squashed = "".join(core)
    if len(squashed) < 3:
        return False
    for name in names:
        have = tokens(name)
        if not have:
            continue
        # With the descriptors dropped, "Apex Cloud" is only "apex" — which
        # "Apex Fitness" also contains. So the site may not add a distinguishing
        # word of its own: "BrightByte" fits "BrightByte Software", "Apex
        # Fitness" does not fit "Apex Cloud".
        distinct = {t for t in have if t not in DESCRIPTORS}
        if set(core) <= set(have) and (not dropped or distinct <= set(want)):
            return True
        # "BrightByte" written "Bright Byte", or the other way round.
        if len(squashed) >= 6 and squashed in "".join(have):
            return True
    return False


async def _dns(domain: str) -> bool:
    loop = asyncio.get_running_loop()
    for host in (domain, f"www.{domain}"):
        try:
            await asyncio.wait_for(loop.getaddrinfo(host, 443), timeout=TIMEOUT_SECONDS)
            return True
        except (OSError, UnicodeError, asyncio.TimeoutError):
            continue
    return False


async def inspect(domain: str | None, *, http=None, resolve=_dns) -> SiteIdentity:
    """Read what a domain says about itself. One DNS lookup and one homepage."""
    name = normalise_domain(domain)
    result = SiteIdentity(domain=name or (domain or ""))
    if not name:
        return result
    result.exists = await resolve(name)
    if not result.exists:
        return result

    own = http or client(timeout=TIMEOUT_SECONDS)
    owned = http is None
    try:
        for url in (f"https://{name}/", f"http://{name}/"):
            try:
                response = await own.get(url)
            except Exception as exc:  # noqa: BLE001 — an unreachable site is a finding
                log.info("site_identity.unreachable url=%s err=%s", url, type(exc).__name__)
                continue
            result.answered = True
            result.status = response.status_code
            host = getattr(getattr(response, "url", None), "host", None)
            result.final_domain = normalise_domain(host) if isinstance(host, str) and host else name
            if response.status_code < 400:
                landed = f"https://{result.final_domain or name}/"
                # Checked after the read, so a dead host is not waited on twice.
                # A homepage robots forbids is not read for its names.
                if await allowed(own, landed, {}):
                    body = (response.text or "")[:READ_CHARS]
                    result.parked = bool(_PARKED.search(body))
                    result.names = names_in(body)
                    result.company_pages = linkedin.company_pages(body)
            break
    finally:
        if owned:
            await own.aclose()
    return result
