"""Ask a site what its pages are called, instead of guessing.

`site_sweep` used to guess: `/news`, then `/careers`, then `/newsroom`, then
`/jobs`, each miss costing an eight-second timeout. A sitemap replaces the
guess with a lookup, and the survey behind this module (`scripts/survey_sitemaps.py`,
run across all 53 domains on the book) says three things that could not have
been reasoned out:

**Two sites in three have one.** 31 of 53 answered with a parseable sitemap —
16 at a conventional path with nothing declared, 8 declared in `robots.txt`,
and 10 of those only via a sitemap *index*. So this is the common case, and the
old path-guessing has to stay for the other third.

**The guess list named the wrong page.** Across those sites `/blog` appears on
13 and `/news` on **3**. `PAGE_PATHS` led with `/news` and did not contain
`/blog` at all, so on the commonest shape of site the sweep timed out looking
for a page that was never there and ignored the one that was. `/about-us`
(12 sites) and `/about` (8) were likewise never fetched, although the about
page is the single most common page on the book — 24 of 31 sites — and is the
best raw material a company profile has.

**Careers pages are genuinely rare**, not just badly addressed: 7 of 31,
spelled `/careers` on 6 and `/join` on 1. That confirms §94 from the other
direction — the one-in-twenty hit rate was the sites' doing, not the guess
list's.

**`<lastmod>` orders the list and nothing more.** Measured separately: of 35
domains with a sitemap, 29 carry stamps that genuinely vary (one runs
2014‑01‑20 to 2026‑10‑01, 304 distinct days across 1,138 URLs), 2 stamp every
URL with one date, and 4 carry none.

It is tempting to use that as a date, and it must not be. A sitemap is a
**living** list: everything in it is a page the site currently serves, so there
is no stale entry to filter out, and a cutoff on `lastmod` would only throw
away live pages on the strength of a field that means *modified* rather than
*published*. The same field in the other direction is worse — a 2019 post
re-rendered by a theme upgrade carries today's stamp, and filing that as
`observed_at` would turn a re-render into a dated event, which is precisely
what becomes a false "why now".

So it is a **sort key**: fetch the most recently changed articles first. When
the stamps are good that is the ranking a path guess could never do, and when
they are junk it merely reorders. Dates continue to come from the page text,
and `observed_at` stays null exactly as it does for the pages `site_sweep`
already reads.
"""

from __future__ import annotations

import gzip
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlparse

log = logging.getLogger(__name__)

#: Tried when `robots.txt` declares nothing — which is the majority case: 16 of
#: the 31 sites with a sitemap declare none and have one here anyway.
CONVENTIONAL = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml")

#: Candidate sitemap URLs tried before giving up. Each miss is a timeout, and a
#: site with none of these does not have one.
MAX_CANDIDATES = 4
#: Child sitemaps followed from an index. 10 of the 35 arrive this way, and a
#: large site lists dozens of children — this is a reader, not a crawler.
#:
#: **Which** five matters more than how many. A WordPress index lists nine:
#: `post-sitemap.xml` and `page-sitemap.xml` carry the pages, while
#: `attachment-sitemap.xml` is the media library, `category-sitemap.xml` and
#: `post_tag-sitemap.xml` are taxonomy stubs, and `author-sitemap.xml` is one
#: page per staff login. Taking the first five blind spent fetches on those and
#: let their URLs crowd the article list — corpstrat.com harvested 1,138 URLs
#: that way, most of them attachments. See `_worth_following`.
MAX_CHILDREN = 5

#: Child sitemaps to skip outright. Measured on the three indexed sites that
#: list more than five children: every one of these holds either media or
#: taxonomy pages, and neither is prose about the company.
SKIP_CHILDREN = (
    "attachment", "category", "tag", "author", "feed", "image", "video",
    "product", "download", "location_category",
)
#: Preferred children, best first. `post` and `page` cover the pages on all ten
#: indexed sites; `team` and `testimonial` exist as their own children on
#: corpstrat.com and heffnetwork.com, which is where the about and proof hubs
#: live on a site built that way.
PREFER_CHILDREN = (
    "post", "page", "news", "blog", "career", "job", "team", "testimonial", "press",
)
#: Parsed per domain. The largest on the book declares 1,138.
MAX_ENTRIES = 3000

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_URL_BLOCK = re.compile(r"<url\b[^>]*>(.*?)</url\s*>", re.IGNORECASE | re.DOTALL)
_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)", re.IGNORECASE)

#: What each kind of page is called. **Ordered by preference**: the spellings
#: the survey actually counted come first, then the conventional alternatives.
#: The order is load-bearing — `pick` takes one hub per theme and uses this
#: ranking to choose which, so a site with both `/news` and `/insights` gets
#: read at the one more likely to be its newsroom.
#:
#: Length is free here and only here. These are compared against URLs a site
#: has **already declared**, so a spelling that never matches costs nothing —
#: where every entry in `site_sweep.PAGE_PATHS` costs an eight-second timeout
#: on every site that lacks it. That asymmetry is the whole argument for
#: reading a sitemap, and it is why this list can afford to be exhaustive while
#: the guess list is capped at six.
#:
#: Paths are lowercased before matching, so `/Careers` and `/JOBS/` match
#: already. The **un-delimited** spellings at the end of each tuple —
#: `joinus`, `aboutus`, `pressroom` — are the case lowercasing cannot reach,
#: because `/JoinUs` becomes `joinus` and never equals `join-us`. Measured: not
#: one of them occurs on this book. They are kept because a word that never
#: matches costs nothing here, which is exactly the asymmetry above; they are
#: ranked last so a site with both spellings is read at the real one.
THEMES: dict[str, tuple[str, ...]] = {
    # On 19 of the 31 sites. /blog beats /news 13 to 3 — which the guess list
    # had backwards. `resources` (7) and `resource-center` outrank most of the
    # conventional names on this book, which is not what intuition would say.
    "news": (
        "blog", "blogs", "resources", "resource-center", "news", "latest-news",
        "insights", "thought-leadership", "press", "press-room", "press-center",
        "press-releases", "press-release", "articles", "article", "media",
        "media-center", "mediaroom", "newsroom", "announcements", "updates",
        "company-updates", "stories", "our-stories", "perspectives",
        "magazine", "journal", "knowledge", "library",
        "pressroom", "latestnews", "pressreleases",
    ),
    # 24 of 31 — the most common page on the book, and never fetched until now.
    #
    # `people` and `our-people` are **kept here rather than under careers**,
    # against the suggested grouping. On this book they are team pages: a
    # brokerage's `/our-people` lists the staff it has, not the roles it wants.
    # The theme decides the passage's label, so filing a staff directory as a
    # jobs page is how "no roles listed" becomes a fact about the company
    # instead of a fact about the page — the same error §93 corrected for
    # catch-all sites.
    "about": (
        "about-us", "about", "team", "our-team", "who-we-are", "staff",
        "our-story", "leadership", "people", "our-people", "meet-the-team",
        "management", "why-us", "our-firm", "company",
        "aboutus", "ourteam", "whoweare", "ourstory", "meettheteam", "ourpeople",
    ),
    # 7 of 31: `/careers` on 6 and `/join` on 1. Rare for real, not
    # mis-addressed — which confirms §94's one-in-twenty from the other side.
    "careers": (
        "careers", "career", "join", "join-us", "join-our-team", "jobs", "job",
        "work-with-us", "employment", "opportunities", "openings",
        "current-openings", "open-positions", "available-positions",
        "positions", "vacancies", "hiring", "recruitment", "recruit",
        "job-openings", "culture", "joinus", "workwithus", "openpositions",
        "jobopenings",
    ),
    # 7 of 35 sites — the same hit rate as careers, which is why it earns a
    # theme of its own rather than being folded into news. It is **not** news:
    # a testimonial is undated marketing, so it can never be a "why now".
    #
    # What it is good for is the strategy stage. A brokerage's client list and
    # testimonials name the industries it serves and the wins it is proud of,
    # which is what a pitch is aimed at — and `/events` and `/webinars`, offered
    # alongside, are **refused**: 2 sites of 35, and the 297 `/events` URLs in
    # the first tally were one carrier's habit read as a pattern.
    "proof": (
        "testimonials", "testimonial", "case-studies", "case-study",
        "success-stories", "customers", "clients", "our-clients",
        "casestudies", "successstories",
    ),
}

#: Segments that are a theme once something is appended — `/work-at-meridian`,
#: `/news-events`, `/careers-at-x`. Matched as prefixes because the tail is the
#: company's own name or a second noun, neither of which can be enumerated.
#:
#: `blog-` was here and is **dropped**: re-run against the book it matched
#: exactly one page, `/blog-maintenence`, which is a maintenance notice. A
#: prefix is looser than a word and earns its place by what it finds; `news-`
#: found a real `/news-events` and stays.
THEME_PREFIXES: dict[str, tuple[str, ...]] = {
    "careers": ("work-at-", "life-at-", "careers-at-", "jobs-at-", "join-"),
    "news": ("news-",),
}

#: Not prose, whatever its path says. A sitemap lists these alongside pages.
_NOT_A_PAGE = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip",
    ".doc", ".docx", ".xls", ".xlsx", ".mp4", ".mp3", ".xml",
)


@dataclass(frozen=True)
class Entry:
    """One URL a sitemap declares, with the date the sitemap gives it."""

    url: str
    lastmod: date | None = None


@dataclass(frozen=True)
class Sitemap:
    """What a domain's sitemap declares, and how much to trust its dates."""

    entries: tuple[Entry, ...] = ()
    #: Which candidate answered — recorded so a coverage row can say whether a
    #: page was found or guessed at.
    found_at: str | None = None
    #: Whether `lastmod` varies across the sitemap. A single stamp on every URL
    #: is a bulk re-render (2 of 35 domains), and reading it as a page date
    #: would date a company's whole history to one day.
    dates_vary: bool = False

    def __bool__(self) -> bool:
        return bool(self.entries)


@dataclass(frozen=True)
class Page:
    """A page worth fetching: where it is, what it is, and when it changed."""

    url: str
    #: The theme it matched — becomes the stored passage's title, so extraction
    #: knows whether it is reading a jobs page or an about page.
    theme: str
    #: True for a single-segment hub (`/blog`, `/about-us`): a standing
    #: description of the company. False for an item beneath one
    #: (`/blog/2026/we-acquired-x`): a thing that happened.
    hub: bool
    #: Only ever a sort key. Never written to a passage — see the module
    #: docstring on why `lastmod` must not become `observed_at`.
    lastmod: date | None = None

    @property
    def title(self) -> str:
        """What the passage is called. Says hub or article, because they are
        different kinds of evidence and extraction should not confuse them."""
        return f"{self.theme} ({'section' if self.hub else 'article'})"


def _decode(body: bytes, url: str) -> str | None:
    if url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except Exception:  # noqa: BLE001 — a corrupt sitemap is just a miss
            return None
    return body.decode("utf-8", "replace")


def _when(value: str | None) -> date | None:
    """A `lastmod`, or None. Never today: a missing date must stay missing."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None


def parse(body: str) -> tuple[list[Entry], list[str]]:
    """Entries and child-sitemap URLs from one sitemap document.

    Both are returned because an index and a sitemap are told apart by which
    one came back non-empty, not by reading the root element — a few real sites
    wrap `<url>` blocks in a `<sitemapindex>` and vice versa.
    """
    children: list[str] = []
    if "<sitemapindex" in body[:2000].lower():
        children = _LOC.findall(body)

    entries: list[Entry] = []
    for block in _URL_BLOCK.findall(body):
        loc = _LOC.search(block)
        if not loc:
            continue
        stamp = _LASTMOD.search(block)
        entries.append(Entry(loc.group(1).strip(), _when(stamp.group(1) if stamp else None)))
    if not entries and not children:
        # A sitemap with bare <loc> and no <url> wrapper. Rare, but cheap to allow.
        entries = [Entry(u) for u in _LOC.findall(body)]
    return entries[:MAX_ENTRIES], children


def _worth_following(children: list[str]) -> list[str]:
    """Child sitemaps, junk dropped and the useful ones first.

    The budget is five fetches. Spending them in the order an index happens to
    list its children is fine on the ten sites measured — a WordPress index
    puts `post` and `page` first — but it is luck, and the children it puts
    *after* those are the media library and the taxonomy stubs, whose URLs then
    outnumber the real pages in the pool `pick` chooses from.
    """
    def name(url: str) -> str:
        return urlparse(url).path.rsplit("/", 1)[-1].lower()

    kept = [c for c in children if not any(word in name(c) for word in SKIP_CHILDREN)]
    # `post_tag-sitemap.xml` contains "post", so preference is tested only
    # after the skip list has removed it. Order matters, not just membership.
    def rank(url: str) -> int:
        label = name(url)
        for position, word in enumerate(PREFER_CHILDREN):
            if word in label:
                return position
        return len(PREFER_CHILDREN)

    return sorted(kept, key=rank) or children


async def discover(http, domain: str, robots: dict) -> Sitemap:
    """Find and read the domain's sitemap, or return an empty one.

    The declared locations come from the `robots.txt` **already fetched** by
    `site_sweep.answers` — `RobotFileParser.site_maps()` keeps the `Sitemap:`
    directives it parsed, so finding them costs no extra request. That matters:
    this runs for every account on every sweep, and the point of the module is
    to spend fewer requests, not more.
    """
    from app.services.site_sweep import _get_bytes, allowed

    rules = robots.get(f"https://{domain}")
    declared = list(rules.site_maps() or []) if rules is not None else []
    # One site declares a sitemap that is not at /sitemap.xml, and sixteen
    # declare nothing but answer at a conventional path, so both are tried.
    candidates = declared + [f"https://{domain}{path}" for path in CONVENTIONAL]

    tried = 0
    for candidate in dict.fromkeys(candidates):
        if tried >= MAX_CANDIDATES:
            break
        if not await allowed(http, candidate, robots):
            continue
        tried += 1
        raw = await _get_bytes(http, candidate)
        if raw is None:
            continue
        body = _decode(raw, candidate)
        if not body or "<loc" not in body.lower():
            continue
        entries, children = parse(body)
        for child in _worth_following(children)[:MAX_CHILDREN]:
            child_raw = await _get_bytes(http, child)
            if child_raw is None:
                continue
            child_body = _decode(child_raw, child)
            if child_body:
                entries.extend(parse(child_body)[0])
        if entries:
            stamps = {e.lastmod for e in entries if e.lastmod}
            log.info(
                "sitemap.found domain=%s at=%s urls=%d dated=%d",
                domain, candidate, len(entries), len(stamps),
            )
            return Sitemap(
                tuple(entries[:MAX_ENTRIES]), candidate, dates_vary=len(stamps) > 1
            )
    return Sitemap()


def _segments(url: str) -> list[str]:
    path = urlparse(url).path.strip("/").lower()
    if path.endswith(_NOT_A_PAGE):
        return []
    return [s for s in path.split("/") if s]


def classify(url: str) -> tuple[str, bool] | None:
    """`(theme, is_hub)` for a URL, or None when it matches no theme.

    A theme word in the **first** segment only. A match deeper down —
    `/services/business-insurance/news-for-brokers` — is a page about the
    company's product, not its newsroom, and treating it as one filled the
    budget with marketing copy on the two sites that have such paths.
    """
    segments = _segments(url)
    if not segments:
        return None
    theme = _theme_of(segments[0])
    return None if theme is None else (theme, len(segments) == 1)


def _theme_of(segment: str) -> str | None:
    for theme, words in THEMES.items():
        if segment in words:
            return theme
    for theme, prefixes in THEME_PREFIXES.items():
        if segment.startswith(prefixes):
            return theme
    return None


def _rank(segment: str, theme: str) -> int:
    """How preferred this spelling is within its theme — lower is better.

    A site with both `/news` and `/insights` has two candidate hubs and only
    one slot. Without a ranking the winner is whichever the sitemap happened to
    list first, which is the site's alphabetical accident rather than a
    judgement about which page is its newsroom.
    """
    words = THEMES[theme]
    return words.index(segment) if segment in words else len(words)


def pick(found: Sitemap, *, limit: int) -> list[Page]:
    """The pages worth fetching, best first.

    Two kinds, in this order, because they answer different questions and the
    budget has to cover both:

    1. **One hub per theme** — about, news, careers. These are standing
       descriptions, which is what a company profile is made of, and there is
       at most one of each so they cannot crowd anything out.
    2. **News articles, most recently changed first.** These are the specific
       things the company has said about itself.

    **Nothing is excluded for being old.** Every entry is a page the site
    serves today, and `lastmod` is too weak a signal to overrule that — see the
    module docstring. Undated articles sort last and are still kept: 4 domains
    in 35 publish no stamps at all, and dropping a company's announcements over
    a missing attribute is the mistake `parse_feed` already refuses to make.
    """
    if not found:
        return []

    hubs: dict[str, tuple[int, Page]] = {}
    articles: list[Page] = []
    for entry in found.entries:
        segments = _segments(entry.url)
        if not segments:
            continue
        theme = _theme_of(segments[0])
        if theme is None:
            continue
        is_hub = len(segments) == 1
        # A single bulk stamp orders nothing — every URL carries it — so it is
        # discarded rather than used as a tie-break that means nothing.
        stamp = entry.lastmod if found.dates_vary else None
        if is_hub:
            rank = _rank(segments[0], theme)
            if theme not in hubs or rank < hubs[theme][0]:
                hubs[theme] = (rank, Page(entry.url, theme, True, stamp))
            continue
        if theme != "news":
            # A deep page under about, careers or proof is one staff biography,
            # one job advert or one testimonial. The hub lists them; fetching
            # each is a crawl.
            #
            # Measured before being refused: `/careers/engineering`-style
            # department paths are on **0 of 35** sites and individual postings
            # (`/jobs/details/`, `/careers/apply/`) on **0 of 35**. Two sites
            # have any page at all beneath a careers hub, one of them a
            # thousand-person carrier outside the ICP band. The tech-stack
            # argument for reading them is sound and the pages do not exist.
            continue
        articles.append(Page(entry.url, theme, False, stamp))

    articles.sort(key=lambda p: p.lastmod or date.min, reverse=True)
    # Hubs in a fixed order so the about page — present on 28 of 35 sites and
    # the richest description of the company — is never the one dropped, and
    # `proof` is, since it is the one that cannot carry a "why now".
    ordered = [hubs[t][1] for t in ("about", "news", "careers", "proof") if t in hubs]
    return (ordered + articles)[:limit]
