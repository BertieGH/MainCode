"""The company's own announcements, read from its own site.

Every other family asks a model to search. This one fetches: a company's feed
is a dated, first-party list of what it has chosen to say about itself, and
parsing it costs nothing, invents nothing, and gives a rep a link that opens
the exact page.

That matters beyond the saving. A grounded search returns what a model chose
to quote from a page it chose to read; a feed returns the company's own words
with the company's own date on them. For "what has this account announced
recently" the second is simply better evidence, and the model's job moves to
where it belongs — deciding what a launch *means*, not finding it.

**No model call, so no `not_found` guessing.** When a site has no feed the
family records `empty` with that reason, which reads on the coverage tab as a
gap with an explanation rather than as silence.

Scope is deliberately small: the feed a site advertises, the newest handful of
entries, and nothing crawled beyond that. `robots.txt` is honoured, because a
tool that ignores it in a product that also sends email is a tool that gets a
sending domain blocked.
"""

from __future__ import annotations

import logging
import re
import ssl
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from app.schemas.evidence import EvidenceBatch, FoundEvidence

log = logging.getLogger(__name__)

#: How many entries are kept. A feed is a firehose on an active blog, and the
#: twentieth post from last year adds nothing a signal would cite.
MAX_ITEMS = 10
#: How far back an entry still counts. Roughly eighteen months: older than that
#: and it is company history, not a trigger.
WINDOW_DAYS = 540
#: One request should not hold a research run open. Measured against real
#: sites: a slow marketing host answers in two or three seconds, and anything
#: past eight is a host that will not answer at all.
TIMEOUT_SECONDS = 8.0
#: How many candidate feed URLs are tried before giving up. Ten paths at eight
#: seconds each is two minutes on a site with no feed — for one family, of
#: seven, per account. A site that advertises no feed and has none at the four
#: commonest paths does not have one.
MAX_CANDIDATES = 5
#: Tried in order when a site advertises no feed. These are the conventional
#: locations; anything more would be guessing at a site's shape.
FEED_PATHS = (
    "/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml",
    "/blog/feed", "/blog/rss.xml", "/news/feed", "/blog/index.xml",
)
#: Read as HTML when no feed answers **and the site declares no sitemap**.
#:
#: Careers pages are here because **`ats_boards` is paused at 26 attempts and
#: no evidence**: a twenty-person broker runs no Greenhouse board, but it has a
#: careers page. This fetch already runs for every account and costs no model
#: call, so the roles it exposes — and the stack named in them — arrive free.
#: A job advert asking for a legacy skill is evidence the system still runs.
#:
#: `/security`, `/trust` and `/compliance` were read here and are **dropped at
#: the owner's instruction**. They existed for `compliance_security_deadline`,
#: which has produced nothing on this book, and each miss costs an eight-second
#: timeout on every account that has no such page — which is most of them. The
#: type is not orphaned: it keeps `trade_press`, `regulators_and_registers` and
#: its own search instruction, which can still ask a search engine for those
#: paths without us fetching them blind.
#:
#: **Reordered from measurement** (`scripts/survey_sitemaps.py`,
#: all 53 domains). Among the 31 sites that declare a sitemap:
#:
#: * `/blog` appears on **13** sites and `/news` on **3** — this list led with
#:   `/news` and did not contain `/blog` at all, so on the commonest shape of
#:   site it timed out looking for the page that was not there and never asked
#:   for the one that was;
#: * `/about-us` (12) and `/about` (8) make the about page the most common page
#:   on the book, 24 sites of 31, and it was never fetched. It is also the best
#:   description of the company a profile can be built from;
#: * `/careers` is on 6 and `/join` on 1 — rare for real, which confirms §94's
#:   one-in-twenty from the other direction.
#:
#: Only a guess when `sitemap.discover` finds nothing, which is a third of the
#: book. Order is frequency order, because `MAX_PAGES` stops the loop early and
#: whatever is last is what a productive site never reaches.
PAGE_PATHS = (
    "/blog", "/about-us",
    "/careers", "/news",
    "/about", "/resources",
)
#: Kept per account. Each *guessed* miss costs a timeout; a sitemap-chosen URL
#: is a page the site has declared, so it costs a fetch and no gamble — which
#: is why the sitemap path gets a larger budget.
MAX_PAGES = 4
MAX_SITEMAP_PAGES = 6
#: Below this a page is a shell that renders with a script, or a redirect stub.
#: Storing it files "Skip to main content" as evidence about the company.
#:
#: 250, not the 400 first written: a shell measures **zero** characters of text
#: once the tags are stripped, so the threshold needs nowhere near that much
#: headroom — and a terse but genuine trust page runs to about 380, which 400
#: would have thrown away. The floor is here to exclude emptiness, not brevity.
MIN_PAGE_CHARS = 250
#: What a page is called once a second path returns the same text. Measured
#: across twenty accounts: nine sites answer nothing at all, four have a
#: real feed, **six return one page under every path**, and exactly one has
#: genuinely distinct pages. So the common case for a page read is not a
#: careers page — it is a homepage, and it is still worth keeping, because
#: a homepage describes the company and that is what a profile is made of.
#: It is only worth keeping under its real name.
CATCH_ALL_TITLE = "site (same page under every path)"
#: A page is not an entry: it has navigation, a footer and a cookie banner
#: around whatever matters.
#:
#: **2500, raised from 1200.** The first live run showed every site page
#: arriving at exactly 1200 — min, mean and max alike, which is a wall rather
#: than a distribution. The company's own site is the only source on this book
#: that reliably produces anything, and it was the one place text was being
#: thrown away.
#:
#: The cut matters most on the pages added in §82. A `/careers` page opens with
#: navigation and a masthead; the roles, and the platforms named in their
#: requirements, sit below that. An `/news` page is the same shape. Clipping at
#: 1200 kept the boilerplate and dropped the evidence.
#:
#: It is not free: every stored character is an extraction input token later,
#: and four pages at 2500 is ten thousand characters an account against
#: extraction's measured 3,645-token average. Chosen over 4000 for that reason
#: — far enough past the masthead to reach the content, short enough not to
#: double the bill.
PAGE_EXCERPT_CHARS = 2500
#: Said plainly, because a rep will see it: we are a research tool reading a
#: public feed, and a site owner should be able to tell who called.
USER_AGENT = "SalesDemandGen360-research/1.0 (+company announcement reader)"

_LINK_TAG = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"""(\w[\w-]*)\s*=\s*["']([^"']*)["']""")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
#: Whole elements whose *contents* are not prose. Stripping tags alone
#: leaves what is between them, and on a React or Next.js site that is a
#: few kilobytes of JavaScript — which sails past `MIN_PAGE_CHARS` and gets
#: stored as a passage about the company. Four such rows were filed for one
#: account before this existed, each beginning
#: `requestAnimationFrame(function(){$RT=performance.now()})`.
#:
#: This is the same failure `MIN_PAGE_CHARS` was written for — "a shell
#: that renders its content with a script" — arriving by the one route that
#: measurement could not catch, because the shell was not short.
_NOT_PROSE = re.compile(
    r"<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class SweepResult:
    """What one sweep found, ready for `evidence.store_found`."""

    batch: EvidenceBatch
    #: What was looked at and did not produce evidence — the coverage detail.
    misses: tuple[str, ...] = ()
    #: Remarks about the shape of what came back: how much was kept, how much
    #: was older than the window. Not misses — see `research_coverage.notes`.
    notes: tuple[str, ...] = ()
    #: The LinkedIn company page the homepage links to, when it links exactly
    #: one. A site linking two is ambiguous, and a guess here would identify the
    #: account by someone else's page.
    linkedin_company: str | None = None


@dataclass
class _Item:
    url: str
    title: str
    summary: str
    published: date | None = None


def client(timeout: float = TIMEOUT_SECONDS):
    """An httpx client that trusts the operating system's certificates.

    Same reasoning as the provider clients: certifi does not carry a corporate
    proxy's root, and the handshake failure reads as "the site is down".
    """
    import httpx

    try:
        import truststore

        verify: Any = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 — fall back to the bundled roots
        verify = True
    return httpx.AsyncClient(
        timeout=timeout, verify=verify, follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


async def _get(http, url: str) -> str | None:
    """Fetch a URL, or None. A site being unreachable is a finding, not a fault."""
    try:
        response = await http.get(url)
    except Exception as exc:  # noqa: BLE001 — one site must not cost the run
        log.info("site_sweep.unreachable url=%s err=%s", url, type(exc).__name__)
        return None
    if response.status_code != 200:
        return None
    return response.text


async def _get_bytes(http, url: str) -> bytes | None:
    """The raw body, for a document that may be compressed.

    `_get` returns `response.text`, which decodes a gzipped sitemap as mojibake
    rather than failing — so the sitemap reader needs the bytes to spot the
    gzip magic number before any decoding happens.
    """
    try:
        response = await http.get(url)
    except Exception as exc:  # noqa: BLE001 — one site must not cost the run
        log.info("site_sweep.unreachable url=%s err=%s", url, type(exc).__name__)
        return None
    if response.status_code != 200:
        return None
    return response.content


async def allowed(http, url: str, cache: dict[str, RobotFileParser | None] | None = None) -> bool:
    """Whether `robots.txt` permits fetching this URL.

    A missing or unreadable robots.txt allows, which is the convention. A
    present one is obeyed — this product also sends email from the same
    domains, and ignoring robots is how that reputation is lost.

    Fetched once per host and remembered: without the cache a sweep asked for
    robots.txt before *every* candidate feed, which on a site with no feed
    doubled an already pointless walk.
    """
    parts = urlparse(url)
    host = f"{parts.scheme}://{parts.netloc}"
    cache = cache if cache is not None else {}
    if host not in cache:
        body = await _get(http, f"{host}/robots.txt")
        if body is None:
            cache[host] = None
        else:
            parser = RobotFileParser()
            parser.parse(body.splitlines())
            cache[host] = parser
    rules = cache[host]
    return True if rules is None else rules.can_fetch(USER_AGENT, url)


async def answers(http, domain: str, robots: dict[str, RobotFileParser | None]) -> bool:
    """Whether the site answers at all, reading its robots.txt on the way.

    A host that does not answer times out on every request, and a sweep makes
    several: on the Test Data list three dead domains cost forty seconds each,
    all of it waiting, to conclude what the first request already said. Asked
    once, of the robots.txt that would have been fetched first anyway, and the
    answer is kept in `robots` for `allowed` — so a live site pays nothing extra.
    """
    host = f"https://{domain}"
    try:
        response = await http.get(f"{host}/robots.txt")
    except Exception as exc:  # noqa: BLE001 — an unreachable site is a finding
        log.info("site_sweep.unreachable domain=%s err=%s", domain, type(exc).__name__)
        return False
    if response.status_code == 200:
        rules = RobotFileParser()
        rules.parse(response.text.splitlines())
        robots[host] = rules
    else:
        robots[host] = None
    return True


def feeds_in(html: str, base: str) -> list[str]:
    """Feed URLs a page advertises, in the order it lists them.

    A regex over `<link>` tags rather than a parser: the whole job is two
    attributes on one tag, and a dependency that renders a DOM to find them
    would be the largest thing in this module.
    """
    found: list[str] = []
    for tag in _LINK_TAG.findall(html or ""):
        attrs = {k.lower(): v for k, v in _ATTR.findall(tag)}
        if "alternate" not in attrs.get("rel", "").lower():
            continue
        if not any(kind in attrs.get("type", "").lower() for kind in ("rss", "atom")):
            continue
        href = attrs.get("href")
        if href:
            found.append(urljoin(base, href))
    return found


def _text(value: str | None) -> str:
    """Readable text, with script and style bodies removed first.

    Order matters: the elements go before the tags, because once the tags
    are gone there is nothing left to say where a script began and ended.
    """
    return _WS.sub(" ", _TAGS.sub(" ", _NOT_PROSE.sub(" ", value or ""))).strip()


async def _read_pages(http, domain: str, robots: dict) -> tuple[list[FoundEvidence], str]:
    """Pages read as HTML when there is no feed. Asks the site first, then guesses.

    Returns the evidence and a tag saying which route produced it, so a
    coverage query can tell a declared page from a lucky guess.

    **The sitemap comes first** because it turns the guess into a lookup. The
    survey behind `sitemap.THEMES` found that two sites in three declare one,
    and that the paths this function used to guess were the wrong ones — a site
    is thirteen times more likely to call it `/blog` than `/news`. A declared
    URL also costs no gamble: it is a page the site says exists, where every
    guessed miss costs an eight-second timeout.

    The guess survives for the other third, reordered by what the survey
    measured.

    **Undated either way, and left that way.** A page carries no publication
    date the way a feed entry does; a sitemap's `lastmod` is not one either and
    is used only to order the fetches. `observed_at` stays null — the intake
    gate admits undated evidence precisely so this is possible, and extraction
    takes the date from the text when the text gives one.
    """
    from app.services import sitemap

    found = await sitemap.discover(http, domain, robots)
    if found:
        chosen = sitemap.pick(found, limit=MAX_SITEMAP_PAGES)
        if chosen:
            pages = await _fetch_pages(
                http, domain, [(p.url, p.title) for p in chosen], robots,
                limit=MAX_SITEMAP_PAGES,
            )
            if pages:
                return pages, "sitemap"
        # A sitemap that names no page of any theme is a real answer about the
        # site, but not a reason to skip the guess: the themes are derived from
        # this book and a site may simply spell things in a way it has not seen.
        log.info("site_sweep.sitemap_unhelpful domain=%s urls=%d", domain, len(found.entries))

    pages = await _fetch_pages(
        http, domain,
        [(f"https://{domain}{path}", path.strip("/").replace("-", " ")) for path in PAGE_PATHS],
        robots, limit=MAX_PAGES,
    )
    return pages, "read_pages"


async def _fetch_pages(
    http, domain: str, candidates: list[tuple[str, str]], robots: dict, *, limit: int
) -> list[FoundEvidence]:
    """Fetch `(url, title)` candidates in order and keep what reads as prose.

    Shared by both routes so the two cannot drift: the same emptiness floor,
    the same excerpt length, and the same same-page detection apply whether a
    URL was declared by the site or guessed at.
    """
    out: list[FoundEvidence] = []
    #: Text already taken this sweep. Many sites answer **every** path with the
    #: same page — a catch-all route, or a single-page app serving its shell —
    #: so `/news`, `/careers`, `/newsroom` and `/jobs` came back byte-identical
    #: and were stored as four separate passages of the same navigation menu.
    #:
    #: `evidence.excerpt_hash` could not catch it: that key is URL **plus**
    #: text, and these differ by URL. Correctly so, because the same sentence on
    #: two genuinely different pages is two findings. Within one sweep of one
    #: site it is the opposite — the same page under four names — and here is
    #: the only place that can be told apart.
    #:
    #: It also means a 200 from `/careers` does not prove a careers page
    #: exists, which the paths added in §82 had quietly assumed.
    seen: set[str] = set()
    #: fingerprint -> the row kept for it, so a later path matching the
    #: same text can correct that row's title rather than being dropped
    #: silently. Dropping it is right; leaving it mislabelled is not.
    by_text: dict[str, FoundEvidence] = {}
    for url, name in candidates:
        if len(out) >= limit:
            break
        if not await allowed(http, url, robots):
            continue
        body = await _get(http, url)
        if not body:
            continue
        text = _text(body)
        if len(text) < MIN_PAGE_CHARS:
            # A shell that renders its content with a script, or a redirect
            # stub. Storing it would file "Skip to main content" as evidence.
            continue
        fingerprint = _WS.sub(" ", text[:PAGE_EXCERPT_CHARS]).strip().casefold()
        if fingerprint in seen:
            # Seen under another path, so the site answers everything with one
            # page. Say so on the row we already kept: calling it "careers"
            # tells extraction it is reading a jobs page, and a generic
            # homepage read as a careers page is how "no roles listed" becomes
            # a fact about the company rather than about the site.
            kept = by_text.get(fingerprint)
            if kept is not None and kept.title != CATCH_ALL_TITLE:
                kept.title = CATCH_ALL_TITLE
            continue
        seen.add(fingerprint)
        out.append(
            FoundEvidence(
                source_type="web",
                source_url=url,
                source_name=domain,
                title=name or domain,
                excerpt=text[:PAGE_EXCERPT_CHARS],
                observed_at=None,
            )
        )
        by_text[fingerprint] = out[-1]
    return out


def _when(value: str | None) -> date | None:
    """A feed date, from either dialect. Unparseable is None, never today."""
    if not value:
        return None
    raw = value.strip()
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_feed(body: str, base: str) -> list[_Item]:
    """Entries from an RSS or Atom feed, newest first as the feed ordered them."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return []

    items: list[_Item] = []
    # RSS: channel/item. Atom: feed/entry, namespaced.
    for node in root.iter():
        tag = node.tag.split("}")[-1].lower()
        if tag not in ("item", "entry"):
            continue
        get = lambda name: node.find(f"{{*}}{name}")  # noqa: E731 — local shorthand
        title = _text((get("title") is not None and get("title").text) or "")
        link_node = get("link")
        url = ""
        if link_node is not None:
            url = (link_node.text or link_node.get("href") or "").strip()
        if not url:
            for child in node.iter():
                if child.tag.split("}")[-1].lower() == "link" and child.get("href"):
                    url = child.get("href", "")
                    break
        summary = ""
        for name in ("description", "summary", "content"):
            found = get(name)
            if found is not None and (found.text or "").strip():
                summary = _text(found.text)
                break
        published = None
        for name in ("pubDate", "published", "updated", "date"):
            found = get(name)
            if found is not None:
                published = _when(found.text)
                if published:
                    break
        if url and (title or summary):
            items.append(_Item(urljoin(base, url), title, summary, published))
    return items


def to_evidence(item: _Item, *, domain: str) -> FoundEvidence:
    """One entry as evidence: their words, their date, their link.

    `reliability` is high but not certain — a company's own announcement is
    first-hand about what it says, and an advertisement about what it means.
    """
    excerpt = item.summary or item.title
    if len(excerpt) > 600:
        excerpt = excerpt[:597].rsplit(" ", 1)[0] + "…"
    return FoundEvidence(
        source_type="web",
        source_url=item.url,
        source_name=domain,
        title=item.title or None,
        excerpt=excerpt,
        observed_at=item.published,
        reliability=0.85,
        relevance="published by the company itself",
    )


async def sweep_account(
    account, *, http=None, today: date | None = None, max_items: int = MAX_ITEMS
) -> SweepResult:
    """Read the account's own feed. No model call, no crawl beyond the feed."""
    today = today or datetime.now(UTC).date()
    domain = (getattr(account, "domain", None) or "").strip().lower()
    if not domain:
        return SweepResult(
            EvidenceBatch(not_found=["no domain on the account — nothing to read"]),
            ("no domain on the account",),
        )

    own = http or client()
    owned = http is None
    try:
        robots: dict = {}
        if not await answers(own, domain, robots):
            note = f"{domain} did not answer — no feed could be read"
            return SweepResult(EvidenceBatch(not_found=[note]), (note,))

        home = f"https://{domain}/"
        candidates: list[str] = []
        html = await _get(own, home)
        if html:
            candidates.extend(feeds_in(html, home))
        from app.services import linkedin

        company_pages = linkedin.company_pages(html) if html else []
        linkedin_company = company_pages[0] if len(company_pages) == 1 else None
        candidates.extend(urljoin(home, path) for path in FEED_PATHS)

        items: list[_Item] = []
        used = ""
        tried = 0
        for url in dict.fromkeys(candidates):
            if tried >= MAX_CANDIDATES:
                break
            if not await allowed(own, url, robots):
                continue
            tried += 1
            body = await _get(own, url)
            if not body:
                continue
            found = parse_feed(body, url)
            if found:
                items, used = found, url
                break

        if not items:
            # No feed. Read the site's pages directly instead — a company with
            # no RSS still has a newsroom, an about page and sometimes a
            # careers page, and `_read_pages` asks the sitemap which of them
            # exist before falling back to guessing at paths.
            #
            # A fallback, deliberately, and not the first thing tried: a feed
            # is dated, bounded and meant to be read by machines, where a page
            # is none of those. The other route to these pages is a search with
            # `site:` operators, which costs a model call instead of a few HTTP
            # requests. Both exist so the comparison can be made on evidence
            # rather than argued — this one writes `sitemap` or `read_pages`
            # into its notes so a coverage query can tell all three apart.
            pages, how = await _read_pages(own, domain, robots)
            if pages:
                via = (
                    "from its sitemap" if how == "sitemap"
                    else "at the conventional paths"
                )
                note = (
                    f"no feed at {domain}; read {len(pages)} "
                    f"page{'s' if len(pages) != 1 else ''} {via}"
                )
                log.info(
                    "site_sweep.pages domain=%s read=%d via=%s", domain, len(pages), how
                )
                return SweepResult(
                    EvidenceBatch(evidence=pages),
                    (),
                    notes=(note, how),
                    linkedin_company=linkedin_company,
                )
            note = (
                f"no feed found at {domain} — tried the page's own links, "
                f"{tried} conventional path{'s' if tried != 1 else ''}, its "
                f"sitemap and {len(PAGE_PATHS)} standard pages"
            )
            return SweepResult(
                EvidenceBatch(not_found=[note]), (note,), linkedin_company=linkedin_company
            )

        cutoff = today - timedelta(days=WINDOW_DAYS)
        # An undated entry is kept: a feed without dates is common, and the
        # alternative is discarding a company's own announcement for a missing
        # attribute. Too old is dropped, because that is a decision we can make.
        recent = [i for i in items if i.published is None or i.published >= cutoff]
        dropped = len(items) - len(recent)
        kept = recent[:max_items]

        # Remarks about the shape of what came back. Not misses: a feed with
        # thirty entries of which ten are kept has established a great deal,
        # and reporting it as "1 not established" said close to the opposite.
        notes: list[str] = []
        if dropped:
            notes.append(f"{dropped} entr{'y' if dropped == 1 else 'ies'} older than 18 months")
        if len(recent) > len(kept):
            notes.append(f"{len(recent) - len(kept)} more recent entries not kept")
        misses: list[str] = []
        if not kept:
            misses.append(f"{used} has nothing published in the last 18 months")

        log.info(
            "site_sweep.done domain=%s feed=%s items=%d kept=%d", domain, used, len(items), len(kept)
        )
        return SweepResult(
            EvidenceBatch(
                evidence=[to_evidence(i, domain=domain) for i in kept],
                not_found=misses,
            ),
            tuple(misses),
            notes=tuple(notes),
            linkedin_company=linkedin_company,
        )
    finally:
        if owned:
            await own.aclose()
