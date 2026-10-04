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


class FakeClient:
    """Answers from a map; anything else is a 404. Records what was asked."""

    def __init__(self, pages: dict[str, str], *, fail: set[str] | None = None):
        self.pages = pages
        self.fail = fail or set()
        self.asked: list[str] = []

    async def get(self, url: str):
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
        assert "no job board found on bluewave.net — looked for Greenhouse, Lever and Ashby" in result.misses[0]
        assert not any(host in u for u in http.asked for host in ("greenhouse.io", "lever.co", "ashbyhq"))

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

    async def test_a_job_board_is_read_by_the_job_board_reader(self, monkeypatch):
        from app.services import evidence as evidence_service
        from app.services import pipeline, sources

        async def by_key(session):
            return {"job_board": SimpleNamespace(key="job_board", kind="fetch")}

        called: list[str] = []

        async def job_sweep(acc):
            called.append("job_board")
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

        outcome = await pipeline.llm_family_runner(object())(account(), "job_board")
        assert called == ["job_board"]
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
