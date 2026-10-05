"""Open roles, read from the company's own job board. No model call.

Hiring is the trigger this product leans on hardest and the one research saw
least clearly. A careers page usually renders its openings with a script from
the company's applicant-tracking system, so a model reading the page sees the
container and not the jobs — BlueWave's careers page came back as "Embedded
script required to load and display active corporate job openings from
Greenhouse", and that was all research knew about who they were hiring.

The openings are one public request away. Three applicant-tracking systems are
read, which between them host most software companies' boards, and each
publishes an unauthenticated API with every open role's title, team, location,
description and the date it opened:

* **Greenhouse** — `boards-api.greenhouse.io/v1/boards/{token}/jobs`
* **Lever** — `api.lever.co/v0/postings/{company}` (and `api.eu.lever.co`)
* **Ashby** — `api.ashbyhq.com/posting-api/job-board/{board}`

That is better evidence than any search could return: the company's own list,
complete, dated by the company. One source, `job_board`, for all three — which
system a company uses is a fact about the company, not a choice a rep makes.

**Only a board the company's own site names is read.** The token comes from an
embed script or a link on the company's pages. Guessing one from the company
name would sooner or later read a namesake's openings and file them as this
account's hiring — the same wrong-person failure contact research guards against.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from urllib.parse import urljoin, urlparse

from app.schemas.evidence import EvidenceBatch, FoundEvidence
from app.services.site_sweep import SweepResult, _get, allowed, answers, client

log = logging.getLogger(__name__)

#: Roles kept per board, newest first. A large employer lists hundreds —
#: Palantir's Lever board had 311 — and extraction reads a bounded number of
#: passages per account.
MAX_JOBS = 25
#: Pages read looking for the board: the homepage, what it links as careers,
#: then conventional paths. BlueWave's board was on the second.
MAX_PAGES = 4
#: The same cap as a feed entry. Enough for the title line and the opening of
#: the description, where a role's team and stack are usually named.
EXCERPT_CHARS = 600
CAREER_PATHS = (
    "/careers", "/careers/", "/company/careers/", "/jobs", "/about/careers", "/join-us",
)

_TOKEN = r"([A-Za-z0-9_][A-Za-z0-9_.-]*)"
#: (provider, EU host, pattern). Order is irrelevant: a page's boards are read
#: in the order the page names them.
_PATTERNS: tuple[tuple[str, bool, re.Pattern[str]], ...] = (
    # Greenhouse: the embed script, the API, a hosted board link.
    ("greenhouse", False, re.compile(
        r"boards(?:\.eu)?\.greenhouse\.io/embed/job_board(?:/js)?\?(?:[^\"'\s<>]*&)?for=([A-Za-z0-9_-]+)",
        re.I,
    )),
    ("greenhouse", False, re.compile(r"boards-api(?:\.eu)?\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)", re.I)),
    ("greenhouse", False, re.compile(
        r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?!embed\b|v1\b)([A-Za-z0-9_-]+)", re.I
    )),
    # Lever: a hosted posting or the API, on either region's host.
    ("lever", False, re.compile(r"(?<![\w.])jobs\.lever\.co/" + _TOKEN, re.I)),
    ("lever", True, re.compile(r"jobs\.eu\.lever\.co/" + _TOKEN, re.I)),
    ("lever", False, re.compile(r"(?<![\w.])api\.lever\.co/v0/postings/" + _TOKEN, re.I)),
    ("lever", True, re.compile(r"api\.eu\.lever\.co/v0/postings/" + _TOKEN, re.I)),
    # Ashby: a hosted posting or embed, or the API.
    ("ashby", False, re.compile(r"jobs\.ashbyhq\.com/" + _TOKEN, re.I)),
    ("ashby", False, re.compile(r"api\.ashbyhq\.com/posting-api/job-board/" + _TOKEN, re.I)),
    # Workday: the enterprise board, and the reason this reader found nothing
    # across 57 accounts. Greenhouse, Lever and Ashby host startups; a
    # non-technology company of any size is on Workday, iCIMS or Taleo. The
    # hosted URL carries everything the API needs — tenant, cluster and site —
    # in that order, with an optional locale segment between the last two:
    #   acme.wd1.myworkdayjobs.com/External
    #   acme.wd5.myworkdayjobs.com/en-US/External_Careers
    #   acme.wd1.myworkdayjobs.com/wday/cxs/acme/External/jobs
    ("workday", False, re.compile(
        r"([A-Za-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/"
        r"(?:wday/cxs/[A-Za-z0-9-]+/)?(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)",
        re.I,
    )),
)
_LABELS = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "workday": "Workday",
}
#: Named in the "nothing found" note, so a rep reading coverage knows what was
#: looked for rather than assuming every board was tried.
_LOOKED_FOR = "Greenhouse, Lever, Ashby and Workday"

_HREF = re.compile(r"""<a\b[^>]*\bhref\s*=\s*["']([^"']+)["']""", re.I)
_CAREER_WORDS = re.compile(r"career|jobs|join-us|join_us|work-with-us|hiring", re.I)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Board:
    """A job board a company's site names."""

    provider: str
    token: str
    eu: bool = False
    #: Workday only. Its boards are per-tenant hosts rather than one API with a
    #: token, so the cluster (`wd1`, `wd5`…) and the site name both have to be
    #: carried — `acme.wd1.myworkdayjobs.com` and `acme.wd5.…` are different
    #: machines, and guessing the cluster reaches nobody.
    cluster: str = ""
    site: str = ""

    @property
    def label(self) -> str:
        return _LABELS[self.provider]

    def jobs_url(self, token: str | None = None) -> str:
        token = token or self.token
        if self.provider == "greenhouse":
            return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        if self.provider == "lever":
            host = "api.eu.lever.co" if self.eu else "api.lever.co"
            return f"https://{host}/v0/postings/{token}?mode=json"
        if self.provider == "workday":
            return (
                f"https://{token}.{self.cluster}.myworkdayjobs.com"
                f"/wday/cxs/{token}/{self.site}/jobs"
            )
        return f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"

    @property
    def post_body(self) -> dict | None:
        """The request body, for a board that answers a POST rather than a GET.

        Workday's careers API is a search endpoint: it takes facets, an offset
        and a limit, and returns nothing at all to a GET. The three
        startup-oriented boards are plain GETs, so this is None for them and
        the caller branches on it.
        """
        if self.provider != "workday":
            return None
        return {"appliedFacets": {}, "limit": MAX_JOBS, "offset": 0, "searchText": ""}


@dataclass(frozen=True)
class Role:
    """An open role, the same shape whichever system listed it."""

    title: str
    teams: str
    location: str
    opened: datetime | None
    url: str
    body: str


def boards_named(page: str | None) -> list[Board]:
    """Every job board a page names, in the order it names them."""
    hits: list[tuple[int, Board]] = []
    for provider, eu, pattern in _PATTERNS:
        for match in pattern.finditer(page or ""):
            # A sentence ending in a link leaves its full stop on the token.
            token = match.group(1).rstrip(".-")
            if not token:
                continue
            if provider == "workday":
                # Three parts, not one: the API is on the tenant's own host and
                # needs the site name as well, so a Workday board cannot be
                # reconstructed from a token alone the way the others can.
                cluster, site = match.group(2).lower(), match.group(3).rstrip(".-")
                if not site:
                    continue
                hits.append(
                    (match.start(), Board(provider, token, eu, cluster, site))
                )
            else:
                hits.append((match.start(), Board(provider, token, eu)))
    seen: set[tuple[str, str, str]] = set()
    out: list[Board] = []
    for _, board in sorted(hits, key=lambda h: h[0]):
        # The site is part of the identity: a company with "External" and
        # "Internal" boards on one tenant has two, and only the first is ours
        # to read — but they must not dedupe into one.
        key = (board.provider, board.token.lower(), board.site.lower())
        if key not in seen:
            seen.add(key)
            out.append(board)
    return out


def greenhouse_tokens(page: str | None) -> list[str]:
    """Greenhouse board tokens a page names, in order."""
    return [b.token for b in boards_named(page) if b.provider == "greenhouse"]


def career_links(page: str | None, base: str) -> list[str]:
    """Links on the site that look like its careers page. Same host only."""
    host = urlparse(base).netloc.lower()
    out: list[str] = []
    for href in _HREF.findall(page or ""):
        url = urljoin(base, href.strip()).split("#", 1)[0]
        if urlparse(url).netloc.lower() == host and _CAREER_WORDS.search(urlparse(url).path):
            out.append(url)
    return list(dict.fromkeys(out))


def _plain(markup: str | None) -> str:
    """Greenhouse escapes a description's HTML; unescape, then strip the tags."""
    return _WS.sub(" ", _TAGS.sub(" ", unescape(unescape(markup or "")))).strip()


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _teams(*names: str | None) -> str:
    return ", ".join(dict.fromkeys(n.strip() for n in names if n and n.strip()))


async def _post(http, url: str, body: dict) -> str | None:
    """POST and return the response text, or None.

    `site_sweep._get`'s sibling, kept here because Workday is the only board
    that needs it and the sweep has no other reason to write. Same contract: an
    unreachable or unhappy endpoint is a finding, not a fault, and costs one
    source rather than the run.
    """
    try:
        response = await http.post(url, json=body)
    except Exception as exc:  # noqa: BLE001 — one board must not cost the run
        log.info("job_boards.unreachable url=%s err=%s", url, type(exc).__name__)
        return None
    if response.status_code != 200:
        return None
    return response.text


# --------------------------------------------------------------- parsers ---
def _greenhouse_roles(data, token: str) -> list[Role]:
    roles = []
    for job in (data or {}).get("jobs") or []:
        roles.append(
            Role(
                title=(job.get("title") or "").strip(),
                teams=_teams(*(d.get("name") for d in job.get("departments") or [])),
                location=((job.get("location") or {}).get("name") or "").strip(),
                # `first_published`, not `updated_at`: an edit moves the second,
                # and a role opened in January and touched in September is not a
                # September hire.
                opened=_iso(job.get("first_published")) or _iso(job.get("updated_at")),
                url=job.get("absolute_url") or f"https://boards.greenhouse.io/{token}/jobs/{job.get('id')}",
                body=_plain(job.get("content")),
            )
        )
    return roles


def _lever_roles(data) -> list[Role]:
    roles = []
    for posting in data if isinstance(data, list) else []:
        categories = posting.get("categories") or {}
        created = posting.get("createdAt")
        roles.append(
            Role(
                title=(posting.get("text") or "").strip(),
                teams=_teams(categories.get("department"), categories.get("team")),
                location=(categories.get("location") or "").strip(),
                # Milliseconds since the epoch. Lever keeps no "updated" date,
                # so this is when the posting was created.
                opened=datetime.fromtimestamp(created / 1000, tz=UTC) if isinstance(created, (int, float)) else None,
                url=posting.get("hostedUrl") or posting.get("applyUrl") or "",
                body=_plain(posting.get("descriptionPlain") or posting.get("openingPlain")),
            )
        )
    return roles


def _ashby_roles(data) -> list[Role]:
    roles = []
    for job in (data or {}).get("jobs") or []:
        # An unlisted job is reachable by link but not advertised: the company
        # has not said it is hiring for it, so neither do we.
        if job.get("isListed") is False:
            continue
        roles.append(
            Role(
                title=(job.get("title") or "").strip(),
                teams=_teams(job.get("department"), job.get("team")),
                location=(job.get("location") or "").strip(),
                opened=_iso(job.get("publishedAt")),
                url=job.get("jobUrl") or job.get("applyUrl") or "",
                body=_plain(job.get("descriptionPlain")),
            )
        )
    return roles


def _workday_roles(data, board: Board) -> list[Role]:
    """Workday's search results.

    Two things are different enough from the other three to be worth stating.

    **`postedOn` is prose, not a date** — "Posted Today", "Posted 30+ Days
    Ago". It is deliberately *not* parsed into `opened`: inventing a date from
    "30+" would put a guess in a field every downstream expiry calculation
    trusts. It is kept in the excerpt instead, where it is the most useful
    sentence on the posting — a role advertised for thirty days is the
    `hiring_bottleneck` signal stated by the employer.

    `startDate` is a real date when a tenant sends one, and only then.

    **The body is one line.** The search endpoint returns titles and facets,
    not descriptions; the full text is behind a second request per role, which
    would be twenty-five more requests per account for prose extraction mostly
    ignores. The title, team, location and how long it has been open are the
    parts that carry the signal.
    """
    roles = []
    for job in (data or {}).get("jobPostings") or []:
        path = (job.get("externalPath") or "").lstrip("/")
        posted = (job.get("postedOn") or "").strip()
        roles.append(
            Role(
                title=(job.get("title") or "").strip(),
                # Workday's facets vary by tenant; `bulletFields` is where the
                # requisition id and sometimes the department land.
                teams=_teams(*(job.get("bulletFields") or [])),
                location=(job.get("locationsText") or "").strip(),
                opened=_iso(job.get("startDate")),
                url=(
                    f"https://{board.token}.{board.cluster}.myworkdayjobs.com"
                    f"/en-US/{board.site}/{path}"
                    if path
                    else f"https://{board.token}.{board.cluster}.myworkdayjobs.com/{board.site}"
                ),
                body=posted,
            )
        )
    return roles


def roles_from(board: Board, data) -> list[Role]:
    if board.provider == "greenhouse":
        return _greenhouse_roles(data, board.token)
    if board.provider == "lever":
        return _lever_roles(data)
    if board.provider == "workday":
        return _workday_roles(data, board)
    return _ashby_roles(data)


def to_evidence(role: Role, *, source_name: str) -> FoundEvidence | None:
    """One open role as evidence: its own title, team, place and words."""
    head = " — ".join(part for part in (role.title, role.teams, role.location) if part)
    excerpt = f"{head}. {role.body}" if head and role.body else (head or role.body)
    if not excerpt or not role.url:
        return None
    if len(excerpt) > EXCERPT_CHARS:
        excerpt = excerpt[: EXCERPT_CHARS - 3].rsplit(" ", 1)[0] + "…"
    return FoundEvidence(
        source_type="jobs",
        source_url=role.url,
        source_name=source_name,
        title=role.title or None,
        excerpt=excerpt,
        observed_at=role.opened.date() if role.opened else None,
        # The company's own list of what it is hiring for: first-hand and
        # current. Not 1.0 — a posting says a role is open, not that it is
        # funded or will be filled.
        reliability=0.9,
        relevance="an open role on the company's own job board",
    )


# ----------------------------------------------------------------- sweep ---
async def _find_board(own, domain: str, robots: dict) -> tuple[Board | None, int]:
    home = f"https://{domain}/"
    candidates = [home, *(urljoin(home, path) for path in CAREER_PATHS)]
    visited: set[str] = set()
    fetched = 0
    i = 0
    while i < len(candidates) and fetched < MAX_PAGES:
        url = candidates[i]
        i += 1
        if url in visited:
            continue
        visited.add(url)
        if not await allowed(own, url, robots):
            continue
        fetched += 1
        page = await _get(own, url)
        if not page:
            continue
        boards = boards_named(page)
        if boards:
            return boards[0], fetched
        if url == home:
            # The pages the site itself calls careers come before guesses.
            candidates[i:i] = [link for link in career_links(page, home) if link not in visited]
    return None, fetched


async def sweep_account(account, *, http=None, max_jobs: int = MAX_JOBS) -> SweepResult:
    """Find the job board the company's site names, and read its open roles."""
    domain = (getattr(account, "domain", None) or "").strip().lower()
    if not domain:
        note = "no domain on the account — no careers page to read"
        return SweepResult(EvidenceBatch(not_found=[note]), (note,))

    own = http or client()
    owned = http is None
    try:
        robots: dict = {}
        if not await answers(own, domain, robots):
            note = f"{domain} did not answer — no careers page could be read"
            return SweepResult(EvidenceBatch(not_found=[note]), (note,))
        board, fetched = await _find_board(own, domain, robots)
        if board is None:
            note = (
                f"no job board found on {domain} — looked for {_LOOKED_FOR} on "
                f"{fetched} page{'s' if fetched != 1 else ''}"
            )
            return SweepResult(EvidenceBatch(not_found=[note]), (note,))

        if not await allowed(own, board.jobs_url(), robots):
            note = f"robots.txt disallows reading {board.label} board {board.token}"
            return SweepResult(EvidenceBatch(not_found=[note]), (note,))

        if board.post_body is not None:
            body = await _post(own, board.jobs_url(), board.post_body)
        else:
            body = await _get(own, board.jobs_url())
        if body is None and board.post_body is None and board.token != board.token.lower():
            # A site may write the board's name as the brand does — Linear links
            # "jobs.ashbyhq.com/Linear/…" — where the API wants it lower-cased.
            body = await _get(own, board.jobs_url(board.token.lower()))
        try:
            data = json.loads(body) if body else None
        except ValueError:
            data = None
        if data is None:
            note = f"{domain} names {board.label} board {board.token!r}, but the board does not answer"
            return SweepResult(EvidenceBatch(not_found=[note]), (note,))

        roles = roles_from(board, data)
        if not roles:
            # Not hiring is a finding about the account, worth recording as one.
            note = f"{board.label} board {board.token} has no open roles"
            return SweepResult(EvidenceBatch(not_found=[note]), (note,))

        name = None
        if board.provider == "greenhouse":
            # Greenhouse names the company behind a board; the others do not.
            named = await _get(own, f"https://boards-api.greenhouse.io/v1/boards/{board.token}")
            try:
                name = (json.loads(named) or {}).get("name") if named else None
            except ValueError:
                name = None
        source_name = f"{name} job board" if name else f"{domain} job board ({board.label})"

        # Newest first. Undated roles sort last rather than being dropped: an
        # open role with no date is still an open role.
        ordered = sorted(
            roles, key=lambda r: r.opened.timestamp() if r.opened else float("-inf"), reverse=True
        )
        kept = [e for e in (to_evidence(r, source_name=source_name) for r in ordered[:max_jobs]) if e]

        # Remarks about what came back, not about what is missing: a board with
        # thirty roles of which two are kept has established plenty.
        notes = [f"{len(roles)} open role{'s' if len(roles) != 1 else ''} on {board.label} board {board.token}"]
        if len(roles) > max_jobs:
            notes.append(f"{len(roles) - max_jobs} older roles not kept")
        log.info(
            "job_boards.done domain=%s provider=%s token=%s roles=%d kept=%d",
            domain, board.provider, board.token, len(roles), len(kept),
        )
        return SweepResult(EvidenceBatch(evidence=kept), (), notes=tuple(notes))
    finally:
        if owned:
            await own.aclose()
