"""Reading a company's own announcements, without a model.

Every other family asks a model to search. This one fetches a feed, so the
tests are about the two things a fetch can get wrong: reading the wrong thing,
and claiming more than the source said.

No network. The client is a fake that answers from a dict, which is also the
point — a family that needs no model needs no fixtures either.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import site_sweep

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Meridian Cloud blog</title>
  <item>
    <title>Meridian ships zero-downtime migrations</title>
    <link>https://meridiancloud.io/blog/zero-downtime</link>
    <description>&lt;p&gt;Our new migration runner moves a live cluster with no
      write pause.&lt;/p&gt;</description>
    <pubDate>Tue, 05 Aug 2026 09:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Ancient history</title>
    <link>https://meridiancloud.io/blog/old</link>
    <description>From another era.</description>
    <pubDate>Tue, 05 Aug 2020 09:00:00 +0000</pubDate>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Meridian news</title>
  <entry>
    <title>Series B closed</title>
    <link rel="alternate" href="https://meridiancloud.io/news/series-b"/>
    <summary>We raised $40m led by Acme Ventures.</summary>
    <published>2026-08-20T10:00:00Z</published>
  </entry>
</feed>"""

HOME = """<html><head>
  <link rel="alternate" type="application/rss+xml" href="/blog/feed.xml">
</head><body>Meridian Cloud</body></html>"""


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    @property
    def content(self) -> bytes:
        """As httpx does. The sitemap reader needs the raw bytes to spot a
        gzipped sitemap before anything tries to decode it as text."""
        return self.text.encode("utf-8")


class FakeClient:
    """Answers from a map; anything else is a 404. Records what was asked."""

    def __init__(self, pages: dict[str, str], *, fail: set[str] | None = None):
        self.pages = pages
        self.fail = fail or set()
        self.asked: list[str] = []

    async def get(self, url: str):
        self.asked.append(url)
        if url in self.fail:
            raise ConnectionError("refused")
        if url in self.pages:
            return FakeResponse(200, self.pages[url])
        return FakeResponse(404, "")

    async def aclose(self):
        return None


class Account:
    def __init__(self, domain: str | None = "meridiancloud.io"):
        self.domain = domain


TODAY = date(2026, 9, 12)


async def sweep(pages, **kwargs):
    http = FakeClient(pages)
    result = await site_sweep.sweep_account(Account(), http=http, today=TODAY, **kwargs)
    return result, http


class TestFindingTheFeed:
    async def test_the_page_s_own_link_is_preferred(self):
        result, http = await sweep({
            "https://meridiancloud.io/": HOME,
            "https://meridiancloud.io/blog/feed.xml": RSS,
        })
        assert [e.title for e in result.batch.evidence] == [
            "Meridian ships zero-downtime migrations"
        ]
        assert "https://meridiancloud.io/blog/feed.xml" in http.asked

    async def test_the_conventional_paths_are_tried_when_nothing_is_advertised(self):
        result, http = await sweep({
            "https://meridiancloud.io/": "<html><body>no feed here</body></html>",
            "https://meridiancloud.io/feed": ATOM,
        })
        assert [e.title for e in result.batch.evidence] == ["Series B closed"]

    async def test_a_site_with_no_feed_says_so_rather_than_going_quiet(self):
        result, _ = await sweep({"https://meridiancloud.io/": "<html></html>"})
        assert result.batch.evidence == []
        assert any("no feed found" in n for n in result.misses)
        assert "meridiancloud.io" in result.misses[0]

    async def test_an_unreachable_site_is_a_finding_not_a_crash(self):
        http = FakeClient({}, fail={"https://meridiancloud.io/"})
        result = await site_sweep.sweep_account(Account(), http=http, today=TODAY)
        assert any("no feed found" in n for n in result.misses)

    async def test_an_account_with_no_domain_is_left_alone(self):
        http = FakeClient({})
        result = await site_sweep.sweep_account(Account(domain=None), http=http, today=TODAY)
        assert http.asked == [], "fetched something for an account with no site"
        assert "no domain" in result.misses[0]


class TestADeadSiteCostsOneRequest:
    """Seen on the Test Data list: three domains that do not answer cost forty
    seconds each — one timeout after another — to conclude "no feed"."""

    async def test_a_site_that_does_not_answer_is_asked_once(self):
        http = FakeClient({}, fail={"https://meridiancloud.io/robots.txt"})
        result = await site_sweep.sweep_account(Account(), http=http)
        assert http.asked == ["https://meridiancloud.io/robots.txt"]
        assert result.misses == ("meridiancloud.io did not answer — no feed could be read",)
        assert result.batch.evidence == []

    async def test_a_live_site_does_not_fetch_robots_twice(self):
        http = FakeClient({"https://meridiancloud.io/": HOME, "https://meridiancloud.io/blog/feed.xml": RSS})
        await site_sweep.sweep_account(Account(), http=http)
        assert http.asked.count("https://meridiancloud.io/robots.txt") == 1


class TestRobotsIsObeyed:
    async def test_a_disallowed_feed_is_not_fetched(self):
        """This product sends email from the same domains it researches.
        Ignoring robots is how that reputation gets spent."""
        http = FakeClient({
            "https://meridiancloud.io/": HOME,
            "https://meridiancloud.io/robots.txt": "User-agent: *\nDisallow: /blog/",
            "https://meridiancloud.io/blog/feed.xml": RSS,
        })
        result = await site_sweep.sweep_account(Account(), http=http, today=TODAY)
        assert "https://meridiancloud.io/blog/feed.xml" not in http.asked
        assert result.batch.evidence == []

    async def test_a_missing_robots_allows(self):
        result, _ = await sweep({
            "https://meridiancloud.io/": HOME,
            "https://meridiancloud.io/blog/feed.xml": RSS,
        })
        assert len(result.batch.evidence) == 1


class TestWhatBecomesEvidence:
    async def test_their_words_their_date_their_link(self):
        result, _ = await sweep({
            "https://meridiancloud.io/": HOME,
            "https://meridiancloud.io/blog/feed.xml": RSS,
        })
        found = result.batch.evidence[0]
        assert found.source_url == "https://meridiancloud.io/blog/zero-downtime"
        assert found.observed_at == date(2026, 8, 5), "dated by the feed, not by today"
        assert "migration runner moves a live cluster" in found.excerpt
        assert "<p>" not in found.excerpt, "markup reached the quote"
        assert found.source_name == "meridiancloud.io"
        assert found.reliability == 0.85

    async def test_entries_older_than_the_window_are_dropped_and_counted(self):
        result, _ = await sweep({
            "https://meridiancloud.io/": HOME,
            "https://meridiancloud.io/blog/feed.xml": RSS,
        })
        assert len(result.batch.evidence) == 1
        assert any("older than 18 months" in n for n in result.notes)

    async def test_only_the_newest_handful_are_kept(self):
        items = "".join(
            f"<item><title>Post {i}</title><link>https://meridiancloud.io/p/{i}</link>"
            f"<description>Body {i}</description>"
            f"<pubDate>Tue, 0{(i % 9) + 1} Aug 2026 09:00:00 +0000</pubDate></item>"
            for i in range(8)
        )
        result, _ = await sweep(
            {
                "https://meridiancloud.io/": HOME,
                "https://meridiancloud.io/blog/feed.xml":
                    f'<?xml version="1.0"?><rss><channel>{items}</channel></rss>',
            },
            max_items=3,
        )
        assert len(result.batch.evidence) == 3
        assert any("more recent entries not kept" in n for n in result.notes), (
            "a sweep that kept fewer than it found is a remark, not a miss"
        )

    async def test_an_undated_entry_is_kept_rather_than_dated_today(self):
        """A feed without dates is common. Stamping it with today would turn
        a five-year-old page into this week's trigger."""
        result, _ = await sweep({
            "https://meridiancloud.io/": HOME,
            "https://meridiancloud.io/blog/feed.xml":
                '<?xml version="1.0"?><rss><channel><item>'
                "<title>Undated</title><link>https://meridiancloud.io/u</link>"
                "<description>No date on this one.</description></item></channel></rss>",
        })
        assert result.batch.evidence[0].observed_at is None

    async def test_a_long_entry_is_cut_at_a_word_and_marked(self):
        body = "word " * 400
        result, _ = await sweep({
            "https://meridiancloud.io/": HOME,
            "https://meridiancloud.io/blog/feed.xml":
                '<?xml version="1.0"?><rss><channel><item>'
                f"<title>Long</title><link>https://meridiancloud.io/l</link>"
                f"<description>{body}</description></item></channel></rss>",
        })
        excerpt = result.batch.evidence[0].excerpt
        assert len(excerpt) <= 600
        assert excerpt.endswith("…")


class TestParsingBothDialects:
    @pytest.mark.parametrize(("feed", "title"), [(RSS, "Meridian ships zero-downtime migrations"),
                                                 (ATOM, "Series B closed")])
    def test_rss_and_atom_both_read(self, feed, title):
        items = site_sweep.parse_feed(feed, "https://meridiancloud.io/feed")
        assert items[0].title == title
        assert items[0].url.startswith("https://meridiancloud.io/")

    def test_rubbish_is_not_a_feed(self):
        assert site_sweep.parse_feed("<html>not xml at all", "https://x/") == []

    def test_an_unparseable_date_is_absent_not_invented(self):
        assert site_sweep._when("last Tuesday-ish") is None
        assert site_sweep._when(None) is None
        assert site_sweep._when("2026-08-20T10:00:00Z") == date(2026, 8, 20)


class TestTheHomepageNamesItsLinkedInPage:
    async def test_one_company_page_is_carried_back(self):
        home = HOME.replace(
            "</body>", '<a href="https://www.linkedin.com/company/meridian-cloud/">in</a></body>'
        )
        http = FakeClient({"https://meridiancloud.io/": home, "https://meridiancloud.io/blog/feed.xml": RSS})
        result = await site_sweep.sweep_account(Account(), http=http)
        assert result.linkedin_company == "https://linkedin.com/company/meridian-cloud"

    async def test_two_different_pages_are_not_guessed_between(self):
        home = HOME.replace(
            "</body>",
            '<a href="https://www.linkedin.com/company/meridian-cloud/">a</a>'
            '<a href="https://www.linkedin.com/company/meridian-labs/">b</a></body>',
        )
        http = FakeClient({"https://meridiancloud.io/": home, "https://meridiancloud.io/blog/feed.xml": RSS})
        result = await site_sweep.sweep_account(Account(), http=http)
        assert result.linkedin_company is None
