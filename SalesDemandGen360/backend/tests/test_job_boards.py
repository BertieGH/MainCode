"""Reading a company's open roles from its own job board. No network.

Greenhouse, Lever and Ashby. The fixture shapes are the APIs' own, as they
answered for BlueWave (Greenhouse), Palantir (Lever) and Linear (Ashby).
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.schemas.evidence import EvidenceBatch
from app.services import job_boards, site_sweep

HOME = """<html><body>
  <a href="/company/about/">About</a>
  <a href="/company/careers/">Careers</a>
  <a href="https://twitter.com/careers">elsewhere</a>
</body></html>"""

CAREERS = """<html><body>
  <div id="grnhse_app"></div>
  <script src="https://boards.greenhouse.io/embed/job_board/js?for=bluewavetechnologygroup"></script>
</body></html>"""

JOBS = {
    "jobs": [
        {
            "id": 5063960008, "title": "Corporate Development Associate",
            "updated_at": "2026-09-01T12:26:14-04:00", "first_published": "2026-01-29T23:51:36-05:00",
            "absolute_url": "https://bluewave.net/company/careers/?gh_jid=5063960008",
            "location": {"name": "Salt Lake City, UT"},
            "departments": [{"name": "Finance & Administration"}],
            "content": "&lt;p&gt;Support &lt;strong&gt;M&amp;amp;A&lt;/strong&gt; diligence.&lt;/p&gt;",
        },
        {
            "id": 5394249008, "title": "Solution Advisor, Cloud & Infrastructure",
            "updated_at": "2026-09-04T19:47:30-04:00", "first_published": "2026-09-04T19:47:30-04:00",
            "absolute_url": "https://bluewave.net/company/careers/?gh_jid=5394249008",
            "location": {"name": "Remote - Nationwide, USA"},
            "departments": [{"name": "Solution Advisors"}],
            "content": "&lt;p&gt;Help clients adopt cloud and managed services.&lt;/p&gt;",
        },
        {
            "id": 5170814008, "title": "Business Development Director - Regional Healthcare",
            "updated_at": "2026-03-30T20:16:54-04:00", "first_published": "2026-03-30T20:16:54-04:00",
            "absolute_url": "https://bluewave.net/company/careers/?gh_jid=5170814008",
            "location": {"name": "Nashville, TN"},
            "departments": [{"name": "Client Advisory"}],
            "content": "",
        },
    ]
}

API = "https://boards-api.greenhouse.io/v1/boards/bluewavetechnologygroup"

#: Lever answers with a bare list; `createdAt` is milliseconds since the epoch.
LEVER = [
    {
        "id": "ac978161", "text": "Forward Deployed Software Engineer",
        "createdAt": 1756944000000,  # 2025-09-04
        "hostedUrl": "https://jobs.lever.co/palantir/ac978161",
        "categories": {"team": "Engineering", "department": "Business Development",
                       "location": "London, United Kingdom", "commitment": "Full-time"},
        "descriptionPlain": "Build and deploy software with customers.",
    },
    {
        "id": "bd0c11aa", "text": "Administrative Business Partner",
        "createdAt": 1711403416463,  # 2024-03-25
        "hostedUrl": "https://jobs.lever.co/palantir/bd0c11aa",
        "categories": {"team": "Administrative", "location": "New York, NY"},
        "descriptionPlain": "",
        "openingPlain": "Support a fast-moving team.",
    },
]
LEVER_API = "https://api.lever.co/v0/postings/palantir?mode=json"

ASHBY = {
    "apiVersion": "1",
    "jobs": [
        {
            "id": "d3bc1ced", "title": "Senior / Staff Fullstack Engineer", "department": "Product",
            "team": "Engineering", "location": "Europe", "publishedAt": "2026-08-27T20:13:45.158+00:00",
            "jobUrl": "https://jobs.ashbyhq.com/linear/d3bc1ced", "isListed": True,
            "descriptionPlain": "Work on the Linear sync engine.",
        },
        {
            "id": "hidden01", "title": "Stealth Role", "department": "Product", "team": "Engineering",
            "location": "Remote", "publishedAt": "2026-09-01T00:00:00+00:00",
            "jobUrl": "https://jobs.ashbyhq.com/linear/hidden01", "isListed": False,
            "descriptionPlain": "Not advertised.",
        },
    ],
}
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/linear?includeCompensation=false"


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    @property
    def content(self) -> bytes:
        """As httpx does — `site_sweep._get_bytes` reads the raw body so a
        gzipped sitemap is recognised before any decoding."""
        return self.text.encode("utf-8")


class FakeClient:
    """Answers from a map; anything else is a 404. Records what was asked."""

    def __init__(self, pages: dict[str, str], *, fail: set[str] | None = None):
        self.pages = pages
        self.fail = fail or set()
        self.asked: list[str] = []
        self.posted: list[tuple[str, dict | None]] = []

    async def get(self, url: str):
        self.asked.append(url)
        if url in self.fail:
            raise ConnectionError("timed out")
        if url in self.pages:
            return FakeResponse(200, self.pages[url])
        return FakeResponse(404, "")

    async def post(self, url: str, json=None):
        """Workday's board answers a POST and nothing else.

        Recorded separately from `asked` so a test can assert that a GET board
        was never POSTed to, and vice versa — the two are not interchangeable
        and a reader that sent the wrong verb would quietly find no roles.
        """
        self.posted.append((url, json))
        self.asked.append(url)
        if url in self.fail:
            raise ConnectionError("timed out")
        if url in self.pages:
            return FakeResponse(200, self.pages[url])
        return FakeResponse(404, "")

    async def aclose(self):
        return None


def bluewave(**over):
    pages = {
        "https://bluewave.net/": HOME,
        "https://bluewave.net/company/careers/": CAREERS,
        API: json.dumps({"name": "Bluewave Technology Group", "content": ""}),
        f"{API}/jobs?content=true": json.dumps(JOBS),
    }
    pages.update(over)
    return FakeClient(pages)


def account(domain="bluewave.net"):
    return SimpleNamespace(id=uuid.uuid4(), domain=domain)


class TestFindingTheBoard:
    @pytest.mark.parametrize(
        "page",
        [
            '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>',
            '<iframe src="https://boards.greenhouse.io/embed/job_board?for=acme&b=x"></iframe>',
            '<a href="https://job-boards.greenhouse.io/acme/jobs/123">Apply</a>',
            '<a href="https://boards.greenhouse.io/acme">Open roles</a>',
            'fetch("https://boards-api.greenhouse.io/v1/boards/acme/jobs")',
        ],
    )
    def test_every_way_a_site_names_a_greenhouse_board(self, page):
        assert job_boards.greenhouse_tokens(page) == ["acme"]

    @pytest.mark.parametrize(
        ("page", "board"),
        [
            ('<a href="https://jobs.lever.co/palantir/61eaa54c">Apply</a>',
             job_boards.Board("lever", "palantir")),
            ('fetch("https://api.lever.co/v0/postings/palantir?mode=json")',
             job_boards.Board("lever", "palantir")),
            ('<a href="https://jobs.eu.lever.co/acme/1">Apply</a>',
             job_boards.Board("lever", "acme", eu=True)),
            ('<a href="https://jobs.ashbyhq.com/Linear/069c4628">Role</a>',
             job_boards.Board("ashby", "Linear")),
            ('<script src="https://jobs.ashbyhq.com/ramp/embed?version=2"></script>',
             job_boards.Board("ashby", "ramp")),
            ('fetch("https://api.ashbyhq.com/posting-api/job-board/ramp")',
             job_boards.Board("ashby", "ramp")),
        ],
    )
    def test_every_way_a_site_names_a_lever_or_ashby_board(self, page, board):
        assert job_boards.boards_named(page) == [board]

    def test_a_json_escaped_link_is_still_read(self):
        """Ramp and Linear name their postings inside scripts, as `\\/`."""
        page = '{"url":"https:\\/\\/jobs.ashbyhq.com\\/ramp\\/03e2d4e1\\/application\\"}'
        assert job_boards.boards_named(page.replace("\\/", "/")) == [job_boards.Board("ashby", "ramp")]

    def test_the_first_board_named_comes_first(self):
        page = (
            '<a href="https://jobs.ashbyhq.com/acme/1">A</a>'
            '<a href="https://jobs.lever.co/acme/2">B</a>'
        )
        assert [b.provider for b in job_boards.boards_named(page)] == ["ashby", "lever"]

    def test_a_sentence_full_stop_is_not_part_of_the_name(self):
        assert job_boards.boards_named("Apply at jobs.lever.co/acme.") == [job_boards.Board("lever", "acme")]

    def test_embed_is_not_mistaken_for_a_board_name(self):
        assert "embed" not in job_boards.greenhouse_tokens(CAREERS)

    def test_nothing_named_is_nothing_found(self):
        assert job_boards.boards_named("<html>We are hiring!</html>") == []

    def test_career_links_stay_on_the_site(self):
        links = job_boards.career_links(HOME, "https://bluewave.net/")
        assert links == ["https://bluewave.net/company/careers/"]

    async def test_the_careers_page_the_site_links_is_read_before_guesses(self):
        http = bluewave()
        await job_boards.sweep_account(account(), http=http)
        pages = [u for u in http.asked if "robots.txt" not in u and "greenhouse" not in u]
        assert pages == ["https://bluewave.net/", "https://bluewave.net/company/careers/"]

    async def test_a_board_is_never_guessed_from_the_name(self):
        """A guessed token reads a namesake's openings as this account's hiring."""
        http = bluewave(**{"https://bluewave.net/company/careers/": "<html>Join us</html>"})
        result = await job_boards.sweep_account(account(), http=http)
        assert result.batch.evidence == []
        assert (
            "no job board found on bluewave.net — looked for "
            "Greenhouse, Lever, Ashby and Workday" in result.misses[0]
        )
        assert not any(
            host in u
            for u in http.asked
            for host in ("greenhouse.io", "lever.co", "ashbyhq", "myworkdayjobs")
        )

    async def test_robots_is_honoured_on_the_site(self):
        http = bluewave(**{
            "https://bluewave.net/robots.txt": "User-agent: *\nDisallow: /company/careers/\n",
        })
        result = await job_boards.sweep_account(account(), http=http)
        assert "https://bluewave.net/company/careers/" not in http.asked
        assert result.batch.evidence == []


class TestReadingGreenhouse:
    async def test_each_open_role_is_one_passage(self):
        result = await job_boards.sweep_account(account(), http=bluewave())
        assert len(result.batch.evidence) == 3
        assert result.notes == ("3 open roles on Greenhouse board bluewavetechnologygroup",)

    async def test_newest_first_by_when_the_role_opened(self):
        """`first_published`, not `updated_at`: the associate role opened in
        January and was edited in September, and is not a September hire."""
        result = await job_boards.sweep_account(account(), http=bluewave())
        assert [e.observed_at for e in result.batch.evidence] == [
            date(2026, 9, 4), date(2026, 3, 30), date(2026, 1, 29),
        ]

    async def test_a_passage_carries_title_team_place_and_its_own_words(self):
        result = await job_boards.sweep_account(account(), http=bluewave())
        associate = next(e for e in result.batch.evidence if e.title == "Corporate Development Associate")
        assert associate.excerpt == (
            "Corporate Development Associate — Finance & Administration — Salt Lake City, UT. "
            "Support M&A diligence."
        )
        assert associate.source_type == "jobs"
        assert associate.source_url.endswith("gh_jid=5063960008")
        assert associate.source_name == "Bluewave Technology Group job board"

    async def test_a_long_description_is_cut_at_a_word(self):
        long = dict(JOBS["jobs"][1], content="&lt;p&gt;" + ("cloud " * 400) + "&lt;/p&gt;")
        http = bluewave(**{f"{API}/jobs?content=true": json.dumps({"jobs": [long]})})
        excerpt = (await job_boards.sweep_account(account(), http=http)).batch.evidence[0].excerpt
        assert len(excerpt) <= job_boards.EXCERPT_CHARS
        assert excerpt.endswith("…")

    async def test_the_cap_is_said_not_silent(self):
        many = {"jobs": [dict(JOBS["jobs"][1], id=i, absolute_url=f"https://x/{i}") for i in range(5)]}
        http = bluewave(**{f"{API}/jobs?content=true": json.dumps(many)})
        result = await job_boards.sweep_account(account(), http=http, max_jobs=2)
        assert len(result.batch.evidence) == 2
        assert "3 older roles not kept" in result.notes


class TestReadingLever:
    def palantir(self, **over):
        pages = {
            "https://palantir.com/": '<a href="/careers/">Careers</a>',
            "https://palantir.com/careers/": '<a href="https://jobs.lever.co/palantir/61eaa54c">Open role</a>',
            LEVER_API: json.dumps(LEVER),
        }
        pages.update(over)
        return FakeClient(pages)

    async def test_postings_are_read_newest_first(self):
        result = await job_boards.sweep_account(account("palantir.com"), http=self.palantir())
        assert result.notes == ("2 open roles on Lever board palantir",)
        assert [e.observed_at for e in result.batch.evidence] == [date(2025, 9, 4), date(2024, 3, 25)]

    async def test_a_posting_carries_its_team_place_and_link(self):
        result = await job_boards.sweep_account(account("palantir.com"), http=self.palantir())
        engineer = result.batch.evidence[0]
        assert engineer.excerpt == (
            "Forward Deployed Software Engineer — Business Development, Engineering — "
            "London, United Kingdom. Build and deploy software with customers."
        )
        assert engineer.source_url == "https://jobs.lever.co/palantir/ac978161"
        assert engineer.source_name == "palantir.com job board (Lever)"

    async def test_the_opening_stands_in_for_an_empty_description(self):
        result = await job_boards.sweep_account(account("palantir.com"), http=self.palantir())
        assert result.batch.evidence[1].excerpt.endswith("Support a fast-moving team.")

    async def test_an_eu_board_is_read_from_the_eu_host(self):
        http = FakeClient({
            "https://acme.eu/": '<a href="https://jobs.eu.lever.co/acme/1">Apply</a>',
            "https://api.eu.lever.co/v0/postings/acme?mode=json": json.dumps(LEVER[:1]),
        })
        result = await job_boards.sweep_account(account("acme.eu"), http=http)
        assert len(result.batch.evidence) == 1


class TestReadingAshby:
    def linear(self, **over):
        pages = {
            "https://linear.app/": '<a href="/careers">Careers</a>',
            "https://linear.app/careers": '<a href="https://jobs.ashbyhq.com/Linear/d3bc1ced">Role</a>',
            ASHBY_API: json.dumps(ASHBY),
        }
        pages.update(over)
        return FakeClient(pages)

    async def test_the_brand_spelling_of_a_board_still_answers(self):
        """Linear links "jobs.ashbyhq.com/Linear/…"; the API wants "linear"."""
        http = self.linear()
        result = await job_boards.sweep_account(account("linear.app"), http=http)
        assert len(result.batch.evidence) == 1
        assert ASHBY_API in http.asked

    async def test_an_unlisted_job_is_not_reported_as_hiring(self):
        result = await job_boards.sweep_account(account("linear.app"), http=self.linear())
        assert [e.title for e in result.batch.evidence] == ["Senior / Staff Fullstack Engineer"]
        assert result.notes == ("1 open role on Ashby board Linear",)

    async def test_a_job_carries_its_department_team_date_and_link(self):
        result = await job_boards.sweep_account(account("linear.app"), http=self.linear())
        job = result.batch.evidence[0]
        assert job.excerpt == (
            "Senior / Staff Fullstack Engineer — Product, Engineering — Europe. "
            "Work on the Linear sync engine."
        )
        assert job.observed_at == date(2026, 8, 27)
        assert job.source_url == "https://jobs.ashbyhq.com/linear/d3bc1ced"


class TestWhatNothingMeans:
    async def test_no_open_roles_is_a_finding(self):
        http = bluewave(**{f"{API}/jobs?content=true": json.dumps({"jobs": []})})
        result = await job_boards.sweep_account(account(), http=http)
        assert result.misses == ("Greenhouse board bluewavetechnologygroup has no open roles",)

    async def test_a_board_that_does_not_answer_says_so(self):
        http = bluewave()
        del http.pages[f"{API}/jobs?content=true"]
        result = await job_boards.sweep_account(account(), http=http)
        assert "does not answer" in result.misses[0]

    async def test_no_domain(self):
        result = await job_boards.sweep_account(account(domain=None), http=FakeClient({}))
        assert "no domain" in result.misses[0]

    async def test_a_site_that_does_not_answer_is_asked_once(self):
        """Seen on the Test Data list: forty seconds per dead domain, five
        timeouts in a row, to conclude what the first one already said."""
        http = FakeClient({}, fail={"https://gone.example/robots.txt"})
        result = await job_boards.sweep_account(account("gone.example"), http=http)
        assert http.asked == ["https://gone.example/robots.txt"]
        assert result.misses == ("gone.example did not answer — no careers page could be read",)

    async def test_a_live_site_does_not_fetch_robots_twice(self):
        http = bluewave()
        await job_boards.sweep_account(account(), http=http)
        assert http.asked.count("https://bluewave.net/robots.txt") == 1


class TestTheRunnerUsesTheRightReader:
    """Two sources are read rather than searched. Dispatching every fetch
    source to the feed reader would read BlueWave's blog and call it hiring."""

    async def test_an_ats_board_is_read_by_the_job_board_reader(self, monkeypatch):
        """Keyed by the **registry** name. `c1f7e3b89d24` renamed `job_board` to
        `ats_boards`; the dispatch table was not part of that rename, so the
        source went active with no reader behind it."""
        from app.services import evidence as evidence_service
        from app.services import pipeline, sources

        async def by_key(session):
            return {"ats_boards": SimpleNamespace(key="ats_boards", kind="fetch")}

        called: list[str] = []

        async def job_sweep(acc):
            called.append("ats_boards")
            # An empty batch has to say what was looked at — the schema refuses
            # silence, since it reads the same as never having run.
            return site_sweep.SweepResult(EvidenceBatch(not_found=["3 open roles"]), ("3 open roles",))

        async def feed_sweep(acc):
            called.append("company_site")
            return site_sweep.SweepResult(EvidenceBatch(not_found=["no feed"]), ("no feed",))

        async def store_found(session, **kwargs):
            return SimpleNamespace(count=0, duplicates=0, stale=0)

        monkeypatch.setattr(sources, "by_key", by_key)
        monkeypatch.setattr(job_boards, "sweep_account", job_sweep)
        monkeypatch.setattr(site_sweep, "sweep_account", feed_sweep)
        monkeypatch.setattr(evidence_service, "store_found", store_found)

        outcome = await pipeline.llm_family_runner(object())(account(), "ats_boards")
        assert called == ["ats_boards"]
        assert outcome.not_found == ("3 open roles",)

    async def test_a_fetch_source_with_no_reader_fails_by_name(self, monkeypatch):
        """Recorded as a failed source with a reason, rather than read by the
        wrong reader or quietly returning nothing."""
        from app.services import pipeline, sources

        async def by_key(session):
            return {"mystery_feed": SimpleNamespace(key="mystery_feed", kind="fetch")}

        monkeypatch.setattr(sources, "by_key", by_key)
        with pytest.raises(RuntimeError, match="mystery_feed"):
            await pipeline.llm_family_runner(object())(account(), "mystery_feed")


# --------------------------------------------------------------------------
# Workday — the enterprise board
# --------------------------------------------------------------------------
#: A tenant's own host. The cluster (`wd1`) and the site (`External`) are both
#: part of the address; neither can be guessed from the company name.
WORKDAY_CAREERS = """<html><body>
  <p>Search and apply for open roles.</p>
  <a href="https://meridian.wd1.myworkdayjobs.com/en-US/External">View openings</a>
</body></html>"""

WORKDAY_API = "https://meridian.wd1.myworkdayjobs.com/wday/cxs/meridian/External/jobs"

#: `postedOn` is prose, not a date — which is the point of the last test here.
WORKDAY_JOBS = {
    "total": 2,
    "jobPostings": [
        {
            "title": "Senior Claims Systems Analyst",
            "externalPath": "/job/Remote/Senior-Claims-Systems-Analyst_R-4471",
            "locationsText": "Remote, United States",
            "postedOn": "Posted 30+ Days Ago",
            "bulletFields": ["R-4471", "Information Technology"],
        },
        {
            "title": "Applied Epic Administrator",
            "externalPath": "/job/Dallas/Applied-Epic-Administrator_R-4502",
            "locationsText": "Dallas, TX",
            "postedOn": "Posted Today",
            "startDate": "2026-10-01",
            "bulletFields": ["R-4502"],
        },
    ],
}


def workday(**over):
    pages = {
        "https://meridian.test/": (
            '<html><body><a href="/careers">Careers</a></body></html>'
        ),
        "https://meridian.test/careers": WORKDAY_CAREERS,
        WORKDAY_API: json.dumps(WORKDAY_JOBS),
    }
    pages.update(over)
    return FakeClient(pages)


class TestWorkday:
    """The board 57 accounts were on while the reader knew three others.

    Greenhouse, Lever and Ashby host startups. A non-technology company of any
    size is on Workday, iCIMS or Taleo — which is why `job_board` produced zero
    evidence across every run rather than "these companies are not hiring".
    """

    async def test_the_tenant_cluster_and_site_all_come_from_the_page(self):
        boards = job_boards.boards_named(WORKDAY_CAREERS)

        assert len(boards) == 1
        board = boards[0]
        assert (board.provider, board.token, board.cluster, board.site) == (
            "workday", "meridian", "wd1", "External",
        )

    async def test_a_locale_segment_does_not_become_the_site_name(self):
        """`/en-US/External` is the locale and then the site. Reading the first
        path segment would address a board called "en-US", which answers
        nothing and looks like a company that is not hiring."""
        boards = job_boards.boards_named(
            '<a href="https://acme.wd5.myworkdayjobs.com/en-US/External_Careers">jobs</a>'
        )

        assert boards[0].site == "External_Careers"
        assert boards[0].cluster == "wd5"

    async def test_the_api_url_is_built_from_all_three_parts(self):
        board = job_boards.Board("workday", "meridian", False, "wd1", "External")

        assert board.jobs_url() == WORKDAY_API

    async def test_it_is_read_with_a_post_not_a_get(self):
        """Workday's careers API is a search endpoint and returns nothing to a
        GET. The wrong verb would read as a company with no open roles."""
        http = workday()
        result = await job_boards.sweep_account(account(domain="meridian.test"), http=http)

        assert [u for u, _ in http.posted] == [WORKDAY_API]
        assert result.batch.evidence, "no roles read from the Workday board"

    async def test_the_search_body_asks_for_a_bounded_page(self):
        http = workday()
        await job_boards.sweep_account(account(domain="meridian.test"), http=http)
        _, body = http.posted[0]

        assert body["limit"] == job_boards.MAX_JOBS
        assert body["offset"] == 0

    async def test_the_roles_carry_their_title_place_and_posting_age(self):
        http = workday()
        result = await job_boards.sweep_account(account(domain="meridian.test"), http=http)
        excerpts = "\n".join(e.excerpt for e in result.batch.evidence)

        assert "Senior Claims Systems Analyst" in excerpts
        assert "Applied Epic Administrator" in excerpts
        assert "Remote, United States" in excerpts
        # The whole hiring_bottleneck signal, stated by the employer.
        assert "Posted 30+ Days Ago" in excerpts

    async def test_posted_on_prose_is_never_parsed_into_a_date(self):
        """"Posted 30+ Days Ago" is not a date, and inventing one would put a
        guess in the field every expiry calculation trusts. A real `startDate`
        is used; prose leaves `observed_at` null."""
        http = workday()
        result = await job_boards.sweep_account(account(domain="meridian.test"), http=http)
        by_title = {
            e.excerpt.split(" — ")[0].strip(): e for e in result.batch.evidence
        }

        assert by_title["Senior Claims Systems Analyst"].observed_at is None
        assert by_title["Applied Epic Administrator"].observed_at == date(2026, 10, 1)

    async def test_a_board_that_does_not_answer_is_a_finding(self):
        http = workday(**{WORKDAY_API: None})
        http.pages.pop(WORKDAY_API)
        result = await job_boards.sweep_account(account(domain="meridian.test"), http=http)

        assert result.batch.evidence == []
        assert "does not answer" in result.misses[0]


# --------------------------------------------------------------------------
# The sub-path fallback — Route B
# --------------------------------------------------------------------------
NO_FEED_HOME = '<html><body><h1>Meridian</h1><p>Insurance brokerage.</p></body></html>'

CAREERS_PAGE = (
    "<html><body><nav>Skip to main content</nav><h1>Careers at Meridian</h1>"
    "<p>We are hiring a Senior Benefits Analyst, a Client Service Manager and "
    "two Account Executives across our Portland and Boise offices. The "
    "Benefits Analyst role requires three years on Applied Epic and comfort "
    "moving historical policy data out of it; experience with Vertafore AMS360 "
    "is an advantage. All roles are hybrid and report to the Director of "
    "Operations.</p>"
    "<footer>© Meridian</footer></body></html>"
)


class TestTheSubPathFallback:
    """Read the conventional pages when there is no feed.

    `company_site` is a feed reader, and the pages that matter most to a small
    company are never in a feed. Open roles are the clearest case: a
    twenty-person broker runs no applicant-tracking board — `ats_boards` is
    paused at 26 attempts and no evidence — but it has a `/careers` page, and
    that page names both the roles and the platform they are hiring around.

    `/security`, `/trust` and `/compliance` were read here too, for
    `compliance_security_deadline`. Dropped: that type produced nothing on this
    book and each miss cost an eight-second timeout on every account without
    such a page. It keeps its other routes.

    A fallback, not the first choice: a feed is dated, bounded and meant to be
    read by a machine. The other route to these pages is a search with `site:`
    operators; both exist so the comparison is evidence rather than argument.
    """

    async def test_pages_are_read_when_no_feed_answers(self):
        http = FakeClient({
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/careers": CAREERS_PAGE,
        })
        result = await site_sweep.sweep_account(
            account(domain="meridian.test"), http=http
        )

        assert result.batch.evidence, "no feed and no pages read"
        # The platform named in a job advert, which is the thing this page is
        # read for: a role asking for three years on Applied Epic is evidence
        # that system is still running, and no feed would ever have carried it.
        assert "Applied Epic" in result.batch.evidence[0].excerpt

    async def test_the_route_is_named_so_the_two_can_be_compared(self):
        """The whole point of keeping both. Without a marker, "which worked
        better" is a question nobody can answer from the data."""
        http = FakeClient({
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/careers": CAREERS_PAGE,
        })
        result = await site_sweep.sweep_account(
            account(domain="meridian.test"), http=http
        )

        assert "read_pages" in result.notes

    async def test_a_feed_still_wins_when_there_is_one(self):
        """The fallback must not fire on a site that advertises a feed — it
        would spend four requests to re-read what the feed already gave."""
        feed = (
            '<?xml version="1.0"?><rss version="2.0"><channel>'
            "<item><title>Meridian acquires Lakeside Benefits</title>"
            "<link>https://meridian.test/news/lakeside</link>"
            "<pubDate>Mon, 15 Sep 2026 09:00:00 GMT</pubDate>"
            "<description>The acquisition adds 40 staff.</description></item>"
            "</channel></rss>"
        )
        http = FakeClient({
            "https://meridian.test/": (
                '<html><head><link rel="alternate" type="application/rss+xml" '
                'href="/feed"></head><body>Meridian</body></html>'
            ),
            "https://meridian.test/feed": feed,
            "https://meridian.test/careers": CAREERS_PAGE,
        })
        result = await site_sweep.sweep_account(
            account(domain="meridian.test"), http=http
        )

        assert result.batch.evidence, "the feed itself should have been read"
        assert "read_pages" not in result.notes
        assert not any("/careers" in u for u in http.asked)

    async def test_a_script_shell_is_not_stored_as_evidence(self):
        """Otherwise "Skip to main content" is filed as a fact about the
        company, and cited in a draft."""
        http = FakeClient({
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/news": "<html><body><div id='root'></div></body></html>",
        })
        result = await site_sweep.sweep_account(
            account(domain="meridian.test"), http=http
        )

        assert result.batch.evidence == []

    async def test_a_page_is_left_undated(self):
        """A page carries no publication date. Dating it from the fetch would
        put today on a company's entire history."""
        http = FakeClient({
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/careers": CAREERS_PAGE,
        })
        result = await site_sweep.sweep_account(
            account(domain="meridian.test"), http=http
        )

        assert result.batch.evidence[0].observed_at is None

    async def test_it_stops_at_the_cap(self):
        """Each miss costs a timeout, and a site without these at the
        conventional spellings does not have them.

        **Distinct** content per path, deliberately. The fixture used to serve
        one page at every path, which the same-page dedup now collapses to one
        — so the test would have passed for the wrong reason, proving the dedup
        rather than the cap.
        """
        pages = {"https://meridian.test/": NO_FEED_HOME}
        for n, path in enumerate(site_sweep.PAGE_PATHS):
            pages[f"https://meridian.test{path}"] = CAREERS_PAGE.replace(
                "Careers at Meridian", f"Careers at Meridian, office {n}"
            ).replace("Senior Benefits Analyst", f"Senior Benefits Analyst {n}")
        http = FakeClient(pages)
        result = await site_sweep.sweep_account(
            account(domain="meridian.test"), http=http
        )

        assert len(result.batch.evidence) == site_sweep.MAX_PAGES


class TestAScriptShellIsNotProse:
    """Stripping tags leaves what is *between* them.

    `MIN_PAGE_CHARS` was written for "a shell that renders its content with a
    script", and it caught the short ones. A React or Next.js page defeats it
    from the other direction: the inline script body is thousands of characters,
    so the shell is not short — it is long and meaningless.

    Four such rows were filed as evidence about one company on the first live
    run, each beginning `requestAnimationFrame(function(){$RT=performance.now()})`.
    Extraction would have read them as passages about the business.
    """

    def test_a_script_body_is_not_counted_as_text(self):
        shell = (
            "<html><head><script>requestAnimationFrame(function(){x=1});"
            + ("var y=1;" * 200)
            + "</script></head><body><div id=root></div></body></html>"
        )
        assert site_sweep._text(shell) == ""

    def test_style_and_noscript_go_the_same_way(self):
        page = (
            "<html><head><style>" + (".a{color:red}" * 60) + "</style></head>"
            "<body><noscript>" + ("Enable JavaScript. " * 30) + "</noscript></body></html>"
        )
        assert site_sweep._text(page) == ""

    def test_real_prose_survives_a_page_that_also_has_scripts(self):
        """The fix must not throw away a page merely for carrying analytics."""
        page = (
            "<html><body><script>" + ("track();" * 200) + "</script>"
            "<p>" + ("Vantreo writes commercial lines for contractors. " * 8) + "</p></body></html>"
        )
        text = site_sweep._text(page)
        assert "Vantreo writes commercial lines" in text
        assert "track()" not in text
        assert len(text) >= site_sweep.MIN_PAGE_CHARS

    def test_the_tags_still_go(self):
        assert site_sweep._text("<p>Hello <b>there</b></p>") == "Hello there"


class TestOnePageUnderFourNames:
    """Many sites answer every path with the same page.

    A catch-all route, or a single-page app serving its shell, returns 200 and
    identical bytes for `/news`, `/careers`, `/newsroom` and `/jobs`. Measured
    live on two of three real brokerages: four evidence rows per account, all
    the same navigation menu, four times the extraction tokens for one page of
    text that was not even prose.

    `evidence.excerpt_hash` cannot catch it — that key is URL *plus* text, and
    these differ by URL. Correctly so: the same sentence on two genuinely
    different pages is two findings. Within one sweep of one site it is the
    opposite, and this is the only place that distinction can be drawn.
    """

    def _same_everywhere(self, body: str) -> dict[str, str]:
        pages = {"https://meridian.test/": NO_FEED_HOME}
        for path in site_sweep.PAGE_PATHS:
            pages[f"https://meridian.test{path}"] = body
        return pages

    async def test_identical_pages_are_stored_once(self):
        menu = (
            "<html><body><nav>Home Products Insights Newsroom Careers Contact</nav>"
            "<p>" + ("Employee Benefits and Absence Management Solutions. " * 10) + "</p>"
            "</body></html>"
        )
        http = FakeClient(self._same_everywhere(menu))
        result = await site_sweep.sweep_account(account(domain="meridian.test"), http=http)
        assert len(result.batch.evidence) == 1, [
            e.source_url for e in result.batch.evidence
        ]

    async def test_genuinely_different_pages_are_all_kept(self):
        """The dedup must not collapse a site that really does have separate
        pages — which is the case it exists to serve."""
        pages = {"https://meridian.test/": NO_FEED_HOME}
        for n, path in enumerate(site_sweep.PAGE_PATHS):
            pages[f"https://meridian.test{path}"] = (
                f"<html><body><p>Page {n}. " + (f"Distinct content number {n}. " * 12)
                + "</p></body></html>"
            )
        http = FakeClient(pages)
        result = await site_sweep.sweep_account(account(domain="meridian.test"), http=http)
        assert len(result.batch.evidence) == site_sweep.MAX_PAGES

    async def test_a_200_from_careers_does_not_prove_a_careers_page(self):
        """What the dedup really says. The paths added in §82 assumed a 200 meant
        the page existed; on a catch-all site every path answers 200."""
        menu = "<html><body><p>" + ("Generic homepage copy. " * 20) + "</p></body></html>"
        http = FakeClient(self._same_everywhere(menu))
        result = await site_sweep.sweep_account(account(domain="meridian.test"), http=http)
        kept = [e.source_url for e in result.batch.evidence]
        assert len(kept) == 1
        assert kept[0].endswith(site_sweep.PAGE_PATHS[0]), "the first path tried wins"


class TestACatchAllPageSaysSo:
    """Dropping the duplicates was right; leaving the survivor mislabelled was not.

    Measured across twenty accounts: nine sites answer nothing, four have a real
    feed, **six return one page under every path**, and exactly one has
    genuinely distinct pages. So the ordinary outcome of a page read is a
    homepage, not a careers page — and calling it `careers` tells extraction it
    is reading a jobs page. "No roles listed" then becomes a fact about the
    company rather than about the site.

    The page is still kept. A homepage describes the company, which is what a
    profile is made of. It is kept under its real name.
    """

    async def test_a_site_answering_every_path_alike_is_named_for_it(self):
        menu = "<html><body><p>" + ("Generic homepage copy. " * 20) + "</p></body></html>"
        pages = {"https://meridian.test/": NO_FEED_HOME}
        for path in site_sweep.PAGE_PATHS:
            pages[f"https://meridian.test{path}"] = menu
        result = await site_sweep.sweep_account(
            account(domain="meridian.test"), http=FakeClient(pages)
        )
        assert len(result.batch.evidence) == 1
        assert result.batch.evidence[0].title == site_sweep.CATCH_ALL_TITLE

    async def test_one_path_answering_alone_keeps_its_name(self):
        """A single hit is not evidence of a catch-all — nothing was seen twice.
        Claiming otherwise would mislabel a site that genuinely has one page."""
        pages = {
            "https://meridian.test/": NO_FEED_HOME,
            "https://meridian.test/careers": CAREERS_PAGE,
        }
        result = await site_sweep.sweep_account(
            account(domain="meridian.test"), http=FakeClient(pages)
        )
        assert len(result.batch.evidence) == 1
        assert result.batch.evidence[0].title == "careers"

    async def test_distinct_pages_each_keep_their_own_name(self):
        pages = {"https://meridian.test/": NO_FEED_HOME}
        for n, path in enumerate(site_sweep.PAGE_PATHS[:2]):
            pages[f"https://meridian.test{path}"] = (
                f"<html><body><p>Page {n}. " + (f"Distinct copy number {n} for this page. " * 12) + "</p></body></html>"
            )
        result = await site_sweep.sweep_account(
            account(domain="meridian.test"), http=FakeClient(pages)
        )
        titles = {e.title for e in result.batch.evidence}
        assert site_sweep.CATCH_ALL_TITLE not in titles
        assert len(titles) == 2
