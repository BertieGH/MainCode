"""The sitemap reader, tested against the shapes the survey actually found.

Every fixture here is a real shape from `scripts/survey_sitemaps.py` run across
all 53 domains on the book: a declared sitemap, an undeclared one at a
conventional path, a sitemap *index* (10 of 31 arrive this way), a site with no
sitemap at all (22 of 53), one that stamps every URL with the same date (2 of
35), and one that carries no `lastmod` (4 of 35).
"""

from __future__ import annotations

import gzip
from datetime import date
from urllib.robotparser import RobotFileParser

import pytest

from app.services import site_sweep, sitemap

pytestmark = pytest.mark.anyio


class FakeResponse:
    def __init__(self, status_code: int, body: str | bytes):
        self.status_code = status_code
        self._body = body

    @property
    def content(self) -> bytes:
        return self._body if isinstance(self._body, bytes) else self._body.encode("utf-8")

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


class FakeClient:
    def __init__(self, pages: dict[str, str | bytes]):
        self.pages = pages
        self.asked: list[str] = []

    async def get(self, url: str):
        self.asked.append(url)
        if url in self.pages:
            return FakeResponse(200, self.pages[url])
        return FakeResponse(404, "")

    async def aclose(self):
        return None


def xml(*entries: tuple[str, str | None]) -> str:
    body = "".join(
        f"<url><loc>{url}</loc>" + (f"<lastmod>{when}</lastmod>" if when else "") + "</url>"
        for url, when in entries
    )
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def index(*urls: str) -> str:
    body = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in urls)
    return f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>'


def robots_for(domain: str, *declared: str) -> dict:
    """The robots cache as `site_sweep.answers` leaves it."""
    rules = RobotFileParser()
    rules.parse([f"Sitemap: {d}" for d in declared] or ["User-agent: *"])
    return {f"https://{domain}": rules}


class TestFindingIt:
    """How the 31 sites with a sitemap actually declare one — or do not."""

    async def test_a_declared_sitemap_is_read(self):
        """8 of 31 declare it in robots.txt, and one of those declares a path
        that is **not** `/sitemap.xml` — so the declaration has to be used
        rather than treated as a hint that a conventional path will work."""
        http = FakeClient({
            "https://meridian.test/sitemap_pages.xml": xml(
                ("https://meridian.test/about-us", "2026-09-01")
            ),
        })
        found = await sitemap.discover(
            http, "meridian.test",
            robots_for("meridian.test", "https://meridian.test/sitemap_pages.xml"),
        )

        assert found
        assert found.found_at == "https://meridian.test/sitemap_pages.xml"

    async def test_the_declaration_costs_no_extra_request(self):
        """`robots.txt` has already been fetched by `site_sweep.answers`. Asking
        for it again would make the module that exists to spend fewer requests
        spend one more on every account."""
        http = FakeClient({
            "https://meridian.test/sitemap.xml": xml(("https://meridian.test/blog", None)),
        })
        await sitemap.discover(http, "meridian.test", robots_for("meridian.test"))

        assert not any(u.endswith("/robots.txt") for u in http.asked)

    async def test_a_conventional_path_is_tried_when_nothing_is_declared(self):
        """The majority case: 16 of the 31 declare nothing and have one here."""
        http = FakeClient({
            "https://meridian.test/sitemap.xml": xml(("https://meridian.test/blog", None)),
        })
        found = await sitemap.discover(http, "meridian.test", robots_for("meridian.test"))

        assert found.found_at == "https://meridian.test/sitemap.xml"

    async def test_an_index_is_followed_to_its_children(self):
        """10 of 31 arrive this way. An index lists sitemaps, not pages, so
        reading its `<loc>` elements as URLs would store sitemap files as
        evidence about the company."""
        http = FakeClient({
            "https://meridian.test/sitemap.xml": index(
                "https://meridian.test/post-sitemap.xml",
                "https://meridian.test/page-sitemap.xml",
            ),
            "https://meridian.test/post-sitemap.xml": xml(
                ("https://meridian.test/blog/lakeside", "2026-09-20")
            ),
            "https://meridian.test/page-sitemap.xml": xml(
                ("https://meridian.test/about-us", "2026-01-02")
            ),
        })
        found = await sitemap.discover(http, "meridian.test", robots_for("meridian.test"))

        urls = {e.url for e in found.entries}
        assert urls == {
            "https://meridian.test/blog/lakeside",
            "https://meridian.test/about-us",
        }

    async def test_a_gzipped_sitemap_is_decompressed(self):
        http = FakeClient({
            "https://meridian.test/sitemap.xml": gzip.compress(
                xml(("https://meridian.test/news", None)).encode()
            ),
        })
        found = await sitemap.discover(http, "meridian.test", robots_for("meridian.test"))

        assert [e.url for e in found.entries] == ["https://meridian.test/news"]

    async def test_no_sitemap_is_an_empty_answer_not_an_error(self):
        """22 of 53 domains. The guess path has to still work for them."""
        found = await sitemap.discover(
            FakeClient({}), "meridian.test", robots_for("meridian.test")
        )

        assert not found
        assert found.entries == ()

    async def test_the_candidates_are_bounded(self):
        """Each miss is a timeout, on every account, on every sweep."""
        http = FakeClient({})
        await sitemap.discover(http, "meridian.test", robots_for("meridian.test"))

        assert len(http.asked) <= sitemap.MAX_CANDIDATES


class TestWhatThePagesAreCalled:
    """The synonyms are derived from the book, not invented.

    `/blog` is on 13 of the 31 sites and `/news` on 3 — which the old guess list
    had backwards, leading with `/news` and never containing `/blog`.
    """

    @pytest.mark.parametrize("path", ["/blog", "/news", "/resources", "/insights", "/press"])
    def test_the_measured_news_spellings_all_match(self, path):
        assert sitemap.classify(f"https://x.test{path}") == ("news", True)

    @pytest.mark.parametrize("path", ["/about-us", "/about", "/team", "/who-we-are", "/staff"])
    def test_the_measured_about_spellings_all_match(self, path):
        assert sitemap.classify(f"https://x.test{path}") == ("about", True)

    @pytest.mark.parametrize("path", ["/careers", "/join"])
    def test_the_measured_careers_spellings_all_match(self, path):
        """Both spellings found on the book: `/careers` on 6 sites, `/join` on 1."""
        assert sitemap.classify(f"https://x.test{path}") == ("careers", True)

    def test_a_page_under_a_hub_is_an_article_not_a_hub(self):
        assert sitemap.classify("https://x.test/blog/we-acquired-lakeside") == ("news", False)

    def test_a_theme_word_deeper_in_the_path_does_not_match(self):
        """`/services/business-insurance/news-for-brokers` is a product page.
        Treating it as a newsroom filled the budget with marketing copy on the
        two sites that have such paths."""
        assert sitemap.classify("https://x.test/services/insurance/news-for-brokers") is None

    def test_a_pdf_is_not_a_page(self):
        assert sitemap.classify("https://x.test/resources/2026-rate-guide.pdf") is None

    def test_an_unrelated_page_matches_nothing(self):
        assert sitemap.classify("https://x.test/commercial-insurance") is None

    @pytest.mark.parametrize(
        "path", ["/work-at-meridian", "/life-at-acme", "/careers-at-vantreo", "/jobs-at-x"]
    )
    def test_a_slug_ending_in_the_company_name_still_matches(self, path):
        """`/work-at-[company]` cannot be enumerated — the tail is whatever the
        company calls itself — so these match as prefixes."""
        assert sitemap.classify(f"https://x.test{path}") == ("careers", True)

    def test_a_staff_directory_is_an_about_page_not_a_jobs_page(self):
        """`/people` and `/our-people` were suggested as careers synonyms and
        are deliberately filed under about: on this book they list the staff a
        brokerage **has**, not the roles it wants. The theme becomes the
        passage's label, so calling a staff directory a jobs page is how "no
        roles listed" turns into a fact about the company."""
        assert sitemap.classify("https://x.test/our-people") == ("about", True)
        assert sitemap.classify("https://x.test/people") == ("about", True)

    def test_a_long_vocabulary_costs_nothing(self):
        """The asymmetry this module exists for: these are matched against URLs
        a site has already declared, so a spelling that never matches is free —
        where each entry in the guess list costs a timeout per site."""
        assert len(sitemap.THEMES["news"]) > len(site_sweep.PAGE_PATHS)
        assert len(sitemap.THEMES["careers"]) > len(site_sweep.PAGE_PATHS)


class TestWhichPagesToFetch:
    def test_one_hub_per_theme_comes_first(self):
        """A hub is a standing description of the company, there is at most one
        of each, and the about page is on 24 of 31 sites — the richest
        description available. It must never be the one crowded out."""
        found = sitemap.Sitemap(
            tuple(
                sitemap.Entry(u, date(2026, 9, n + 1))
                for n, u in enumerate([
                    "https://x.test/blog/one",
                    "https://x.test/blog/two",
                    "https://x.test/blog/three",
                    "https://x.test/blog",
                    "https://x.test/about-us",
                    "https://x.test/careers",
                ])
            ),
            dates_vary=True,
        )
        picked = sitemap.pick(found, limit=4)

        assert [p.theme for p in picked[:3]] == ["about", "news", "careers"]
        assert all(p.hub for p in picked[:3])

    def test_the_better_known_spelling_wins_the_one_hub_slot(self):
        """A site with both `/magazine` and `/news` has two candidate hubs and
        one slot. Without the ranking the winner is whichever the sitemap
        listed first — the site's own accident, not a judgement about which
        page is its newsroom."""
        found = sitemap.Sitemap((
            sitemap.Entry("https://x.test/magazine"),
            sitemap.Entry("https://x.test/news"),
            sitemap.Entry("https://x.test/blog"),
        ))
        picked = sitemap.pick(found, limit=6)

        assert [p.url for p in picked] == ["https://x.test/blog"]

    def test_articles_come_newest_changed_first(self):
        found = sitemap.Sitemap(
            (
                sitemap.Entry("https://x.test/blog/old", date(2024, 1, 1)),
                sitemap.Entry("https://x.test/blog/newest", date(2026, 10, 1)),
                sitemap.Entry("https://x.test/blog/middle", date(2025, 6, 1)),
            ),
            dates_vary=True,
        )
        picked = sitemap.pick(found, limit=3)

        assert [p.url.rsplit("/", 1)[-1] for p in picked] == ["newest", "middle", "old"]

    def test_nothing_is_dropped_for_being_old(self):
        """A sitemap is a living list: every entry is a page the site serves
        today. `lastmod` means *modified*, not *published*, so a cutoff on it
        would discard live pages on the strength of a field that cannot carry
        that weight. One real domain's stamps run 2019-08-28 to 2021-04-28 and
        its articles are still the only thing it publishes."""
        found = sitemap.Sitemap(
            (
                sitemap.Entry("https://x.test/blog/2019", date(2019, 8, 28)),
                sitemap.Entry("https://x.test/blog/2021", date(2021, 4, 28)),
            ),
            dates_vary=True,
        )
        assert len(sitemap.pick(found, limit=6)) == 2

    def test_lastmod_never_becomes_a_passage_date(self):
        """The dangerous direction. A 2019 post re-rendered by a theme upgrade
        carries today's stamp; filing that as `observed_at` would turn a
        re-render into a dated event, and a dated event is what becomes a
        signal. Dates come from the page text instead."""
        found = sitemap.Sitemap(
            (sitemap.Entry("https://x.test/blog/post", date(2026, 10, 1)),), dates_vary=True
        )
        page = sitemap.pick(found, limit=1)[0]

        assert page.lastmod == date(2026, 10, 1), "still usable as a sort key"
        assert not hasattr(page, "observed_at")

    def test_an_undated_article_is_kept_and_sorts_last(self):
        """4 domains of 35 publish no `lastmod` at all. Discarding a company's
        announcements over a missing attribute is the mistake `parse_feed`
        already refuses to make."""
        found = sitemap.Sitemap(
            (
                sitemap.Entry("https://x.test/blog/undated"),
                sitemap.Entry("https://x.test/blog/dated", date(2026, 9, 1)),
            ),
            dates_vary=True,
        )
        picked = sitemap.pick(found, limit=2)

        assert [p.url.rsplit("/", 1)[-1] for p in picked] == ["dated", "undated"]

    def test_a_single_bulk_stamp_is_not_used_to_sort(self):
        """2 of 35 domains stamp every URL with one date. It orders nothing, so
        carrying it would be a tie-break that means nothing."""
        found = sitemap.Sitemap(
            (
                sitemap.Entry("https://x.test/blog/a", date(2026, 5, 5)),
                sitemap.Entry("https://x.test/blog/b", date(2026, 5, 5)),
            ),
            dates_vary=False,
        )
        assert all(p.lastmod is None for p in sitemap.pick(found, limit=2))

    def test_a_deep_about_page_is_not_fetched(self):
        """One staff biography per person is a crawl. The hub lists them."""
        found = sitemap.Sitemap(
            (
                sitemap.Entry("https://x.test/team"),
                sitemap.Entry("https://x.test/team/jane-doe"),
                sitemap.Entry("https://x.test/team/john-roe"),
            )
        )
        picked = sitemap.pick(found, limit=6)

        assert [p.url for p in picked] == ["https://x.test/team"]

    def test_the_limit_holds(self):
        found = sitemap.Sitemap(
            tuple(sitemap.Entry(f"https://x.test/blog/p{n}") for n in range(40))
        )
        assert len(sitemap.pick(found, limit=6)) == 6

    def test_a_sitemap_naming_no_known_page_picks_nothing(self):
        """Not an error — it is what lets the caller fall back to guessing."""
        found = sitemap.Sitemap(
            (sitemap.Entry("https://x.test/"), sitemap.Entry("https://x.test/contact"))
        )
        assert sitemap.pick(found, limit=6) == []


NO_FEED_HOME = "<html><head><title>Meridian</title></head><body>Meridian</body></html>"
PROSE = "<html><body><p>" + ("Meridian writes commercial lines for contractors. " * 10) + "</p></body></html>"


class TestTheSweepAsksTheSiteFirst:
    """What this buys `site_sweep`, end to end."""

    async def test_a_declared_page_is_read_and_the_route_is_named(self):
        http = FakeClient({
            "https://meridian.test/robots.txt": "Sitemap: https://meridian.test/sitemap.xml",
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/sitemap.xml": xml(
                ("https://meridian.test/insights", "2026-09-01")
            ),
            "https://meridian.test/insights": PROSE,
        })
        result = await site_sweep.sweep_account(
            _account("meridian.test"), http=http
        )

        assert [e.source_url for e in result.batch.evidence] == [
            "https://meridian.test/insights"
        ]
        assert "sitemap" in result.notes
        assert "read_pages" not in result.notes

    async def test_a_spelling_the_guess_list_would_have_missed(self):
        """`/newsroom` is not in `PAGE_PATHS` — the guess list has six entries
        and cannot hold every spelling, because each one it holds costs a
        timeout on every site that lacks it. A declared URL costs nothing."""
        http = FakeClient({
            "https://meridian.test/robots.txt": "User-agent: *",
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/sitemap.xml": xml(("https://meridian.test/newsroom", None)),
            "https://meridian.test/newsroom": PROSE,
        })
        result = await site_sweep.sweep_account(_account("meridian.test"), http=http)

        assert "/newsroom" not in "".join(site_sweep.PAGE_PATHS)
        assert [e.source_url for e in result.batch.evidence] == [
            "https://meridian.test/newsroom"
        ]

    async def test_no_page_is_guessed_at_when_the_sitemap_answered(self):
        """The saving. Six guessed paths at eight seconds each is the cost this
        replaces."""
        http = FakeClient({
            "https://meridian.test/robots.txt": "User-agent: *",
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/sitemap.xml": xml(("https://meridian.test/insights", None)),
            "https://meridian.test/insights": PROSE,
        })
        await site_sweep.sweep_account(_account("meridian.test"), http=http)

        guessed = [u for u in http.asked if u.endswith(site_sweep.PAGE_PATHS)]
        assert guessed == []

    async def test_the_guess_still_runs_when_there_is_no_sitemap(self):
        """22 of 53 domains, so this is not a corner case."""
        http = FakeClient({
            "https://meridian.test/robots.txt": "User-agent: *",
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/blog": PROSE,
        })
        result = await site_sweep.sweep_account(_account("meridian.test"), http=http)

        assert [e.source_url for e in result.batch.evidence] == ["https://meridian.test/blog"]
        assert "read_pages" in result.notes

    async def test_a_sitemap_that_names_nothing_useful_falls_through_to_the_guess(self):
        """The themes come from this book; a site may spell things in a way the
        survey never saw. Finding a sitemap is not a reason to stop looking."""
        http = FakeClient({
            "https://meridian.test/robots.txt": "User-agent: *",
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/sitemap.xml": xml(
                ("https://meridian.test/contact", None), ("https://meridian.test/quote", None)
            ),
            "https://meridian.test/about-us": PROSE,
        })
        result = await site_sweep.sweep_account(_account("meridian.test"), http=http)

        assert [e.source_url for e in result.batch.evidence] == [
            "https://meridian.test/about-us"
        ]
        assert "read_pages" in result.notes

    async def test_a_feed_still_wins(self):
        """A feed is dated, bounded and meant for machines. The sitemap route
        must not fire ahead of it — it would re-read what the feed just gave."""
        feed = (
            '<?xml version="1.0"?><rss version="2.0"><channel>'
            "<item><title>Meridian acquires Lakeside</title>"
            "<link>https://meridian.test/news/lakeside</link>"
            "<pubDate>Mon, 15 Sep 2026 09:00:00 GMT</pubDate>"
            "<description>Adds 40 staff.</description></item></channel></rss>"
        )
        http = FakeClient({
            "https://meridian.test/robots.txt": "User-agent: *",
            "https://meridian.test/": (
                '<html><head><link rel="alternate" type="application/rss+xml" '
                'href="/feed"></head><body>Meridian</body></html>'
            ),
            "https://meridian.test/feed": feed,
            "https://meridian.test/sitemap.xml": xml(("https://meridian.test/blog", None)),
        })
        result = await site_sweep.sweep_account(_account("meridian.test"), http=http)

        assert result.batch.evidence[0].observed_at == date(2026, 9, 15)
        assert not any("sitemap" in u for u in http.asked)

    async def test_a_page_read_from_the_sitemap_is_still_undated(self):
        """The same rule as every other page read. The date is in the text, and
        extraction is what reads it."""
        http = FakeClient({
            "https://meridian.test/robots.txt": "User-agent: *",
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/sitemap.xml": xml(
                ("https://meridian.test/blog/lakeside", "2026-10-01")
            ),
            "https://meridian.test/blog/lakeside": PROSE,
        })
        result = await site_sweep.sweep_account(_account("meridian.test"), http=http)

        assert result.batch.evidence[0].observed_at is None

    async def test_a_declared_page_that_is_a_script_shell_is_still_refused(self):
        """A declared URL is not a promise of prose. The emptiness floor has to
        apply to both routes, or the sitemap becomes a way around it."""
        http = FakeClient({
            "https://meridian.test/robots.txt": "User-agent: *",
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/sitemap.xml": xml(("https://meridian.test/blog", None)),
            "https://meridian.test/blog": "<html><body><div id='root'></div></body></html>",
        })
        result = await site_sweep.sweep_account(_account("meridian.test"), http=http)

        assert result.batch.evidence == []

    async def test_a_title_says_whether_it_is_a_section_or_an_article(self):
        """Two different kinds of evidence. A section describes the company; an
        article is a thing it did. Extraction should not have to guess."""
        http = FakeClient({
            "https://meridian.test/robots.txt": "User-agent: *",
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/sitemap.xml": xml(
                ("https://meridian.test/about-us", "2026-01-01"),
                ("https://meridian.test/blog/lakeside", "2026-10-01"),
            ),
            "https://meridian.test/about-us": PROSE,
            "https://meridian.test/blog/lakeside": PROSE.replace("commercial", "specialty"),
        })
        result = await site_sweep.sweep_account(_account("meridian.test"), http=http)

        assert {e.title for e in result.batch.evidence} == {
            "about (section)", "news (article)",
        }


class _Account:
    def __init__(self, domain: str):
        self.id, self.domain, self.name = 1, domain, "Meridian"


def _account(domain: str) -> _Account:
    return _Account(domain)
