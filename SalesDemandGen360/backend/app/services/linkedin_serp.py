"""Public LinkedIn content, read from a search engine's index.

The one rule this module exists to honour: **it never opens linkedin.com.** It
asks a SERP API what Google has indexed and reads the titles, snippets and URLs
that come back. That is the distinction the registry is built on — `linkedin`
is deprecated because Gemini grounding cannot reach these pages at all, and
`linkedin_index` is not because this route can.

Measured before it was written, against ten companies of fifteen to thirty-eight
people:

* `site:linkedin.com/in "{company}"` returns **nine or ten real employees per
  page**, with their role in the snippet — "CFO of Vantreo Insurance Brokerage",
  "General Adjuster … Sep 2013 - Present".
* `site:linkedin.com/posts "{company}"` is **thin**: eighteen posts across ten
  companies, six of which had none at all.
* Every post URL carried a decodable date — **eighteen of eighteen** — which is
  the first live confirmation of `linkedin.post_date`'s activity-id arithmetic.

**`totalResults` is not a headcount.** It ran from 0.52× to 7.42× Apollo's
figure, and the high ones are not noise: they are real *former* employees. The
count tracks how long a company has existed, not how many people work there, so
nothing here writes a headcount.

The recency window travels **in the query** as `after:YYYY-MM-DD`, because this
provider ignores `tbs=qdr:`. That is worth more than filtering afterwards: one
company's thirty-eight indexed posts became six inside ninety days, and the
`totalResults` of the restricted query says whether anything recent exists
before a single result is read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import IntegrationCredential
from app.schemas.evidence import EvidenceBatch, FoundEvidence
from app.services import crypto, linkedin
from app.services.enrichment_clients import _client

log = logging.getLogger(__name__)

SEARLO_URL = "https://api.searlo.tech/api/v1/search/web"

#: One page. Pagination is deliberately not used: a company's profiles run to
#: hundreds because they include alumni, we need three contacts, and page one
#: carries ten. Paging further buys former employees at a credit a page.
PER_PAGE = 10

#: A snippet is the evidence. Below this it is a fragment — "… - LinkedIn" —
#: that reads as a passage and says nothing.
MIN_SNIPPET = 40

TIMEOUT = 30.0


@dataclass
class SerpResult:
    """What one query returned, with the count the query itself reported."""

    found: list[FoundEvidence] = field(default_factory=list)
    #: What the provider says exists for this query, restricted window and all.
    #: Used as a gate, never as a quantity of anything real.
    total: int = 0
    credits: int = 0
    error: str | None = None


@dataclass
class SweepResult:
    """The shape `pipeline` expects from every fetch reader."""

    batch: EvidenceBatch
    misses: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    #: Posts within the window, across the whole sweep. Zero is the gate: a
    #: company silent for a year has nothing for a per-person post query to
    #: find either, and that is eight accounts in ten.
    recent_posts: int = 0


def window_from(max_age_days: int | None, *, today: date | None = None) -> str:
    """The `after:` operator for a window, or an empty string for none.

    Returned as a query fragment rather than a parameter because this provider
    ignores `tbs=qdr:` — measured, not assumed.
    """
    if not max_age_days:
        return ""
    day = (today or datetime.now(UTC).date()) - timedelta(days=max_age_days)
    return f" after:{day.isoformat()}"


async def _ask(client, key: str, query: str) -> SerpResult:
    try:
        response = await client.get(
            SEARLO_URL,
            params={"q": query, "num": PER_PAGE},
            headers={"x-api-key": key},
            timeout=TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — one query must not cost the sweep
        return SerpResult(error=f"{type(exc).__name__}: {exc}")
    if response.status_code >= 400:
        # The key is never echoed: the body can repeat the request, so only the
        # status and a trimmed message travel into a log (invariant 9).
        return SerpResult(error=f"HTTP {response.status_code}")

    body = response.json()
    out = SerpResult(total=int(body.get("totalResults") or 0), credits=int(body.get("credits") or 0))
    for item in body.get("organic") or []:
        url = (item.get("link") or "").strip()
        snippet = (item.get("snippet") or item.get("description") or "").strip()
        if not url or not linkedin.is_linkedin(url) or len(snippet) < MIN_SNIPPET:
            continue
        out.found.append(
            FoundEvidence(
                source_type="web",
                source_url=url,
                source_name="linkedin.com (via search index)",
                title=(item.get("title") or "").strip() or None,
                excerpt=snippet,
                # A post's own date, decoded from its activity id. A profile
                # carries none, and inventing one would date a person's whole
                # history to today — the intake gate admits undated evidence
                # precisely so this can stay honest.
                observed_at=linkedin.post_date(url),
            )
        )
    return out


async def sweep_account(account: Any, *, key: str | None = None, http=None,
                        max_age_days: int | None = 365) -> SweepResult:
    """Read what the index holds about one company. Two queries, no pagination.

    Returns the same shape as the other fetch readers so `pipeline` dispatches
    it identically, including `recent_posts` — the gate that decides whether
    per-person post queries are worth making for this account at all.
    """
    name = (getattr(account, "name", None) or "").strip()
    if not name:
        return SweepResult(
            EvidenceBatch(not_found=["no company name — nothing to search the index for"]),
            ("no company name",),
        )
    if not key:
        # A missing credential is **not** a coverage gap. Reporting "found
        # nothing" here would be indistinguishable from a company with no
        # public footprint, which is the confusion `query_families.Runner`
        # exists to prevent.
        return SweepResult(
            EvidenceBatch(not_found=["no SERP credential configured"]),
            ("no SERP credential",),
            ("linkedin_index needs a Searlo key before it can read anything",),
        )

    after = window_from(max_age_days)
    own = http or _client(TIMEOUT)
    owned = http is None
    found: list[FoundEvidence] = []
    misses: list[str] = []
    notes: list[str] = []
    recent = 0
    try:
        profiles = await _ask(own, key, f'site:linkedin.com/in "{name}"')
        if profiles.error:
            misses.append(f"profiles: {profiles.error}")
        else:
            found.extend(profiles.found)
            if not profiles.found:
                misses.append("no public profiles indexed for this company")

        posts = await _ask(own, key, f'site:linkedin.com/posts "{name}"{after}')
        if posts.error:
            misses.append(f"posts: {posts.error}")
        else:
            recent = posts.total
            found.extend(posts.found)
            if not posts.found:
                misses.append(
                    f"no posts in the last {max_age_days} days" if max_age_days
                    else "no posts indexed"
                )
        notes.append(
            f"serp: {profiles.credits + posts.credits} credit(s), "
            f"{len(found)} passage(s), {recent} recent post(s)"
        )
    finally:
        if owned:
            await own.aclose()

    log.info(
        "linkedin_serp.swept account=%s found=%d recent_posts=%d",
        getattr(account, "id", "?"), len(found), recent,
    )
    return SweepResult(
        EvidenceBatch(evidence=found, not_found=misses or ["nothing in the index"]),
        tuple(misses),
        tuple(notes),
        recent_posts=recent,
    )


#: The provider key under which the credential is stored. One name, used by the
#: catalogue entry, the probe and this reader, so a rename cannot leave the
#: reader looking for a row the settings screen never writes.
PROVIDER = "searlo"


async def api_key(session: AsyncSession) -> str | None:
    """The stored SERP key, or None when none is configured.

    None is a first-class answer: `sweep_account` reports "no credential"
    rather than "found nothing", because a coverage gap and an unconfigured
    provider look identical on a screen and mean opposite things.
    """
    row = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.provider == PROVIDER,
                IntegrationCredential.credential_type == "api_key",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        return crypto.decrypt(row.value_encrypted).reveal()
    except crypto.CredentialError:
        # Never the key itself, and never the ciphertext.
        log.warning("linkedin_serp.undecryptable provider=%s", PROVIDER)
        return None


def reader_for(session: AsyncSession, source) -> "object":
    """Bind the credential and the window, so `pipeline` can call `reader(account)`.

    Every other fetch reader takes an account and nothing else. This one needs
    a key and a recency window, and both are *configuration* — the key from the
    credential store, the window from `research_source.max_age_days` — so they
    are resolved here rather than passed down through the pipeline, which would
    make every reader's signature carry this one reader's needs.
    """
    max_age = getattr(source, "max_age_days", None)

    async def read(account):
        return await sweep_account(
            account, key=await api_key(session), max_age_days=max_age
        )

    return read
