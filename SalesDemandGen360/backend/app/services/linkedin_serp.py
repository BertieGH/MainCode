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
from app.services import crypto, linkedin, post_ranking
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

#: Posts kept per account, after ranking. Six, not ten: strategy already reads
#: the signals, the company profile and the proof points, and the tenth snippet
#: buys little against what it costs in extraction tokens. Measured first — four
#: companies in six return a full page of ten, so this is a real cut and not a
#: cap that never binds.
MAX_POSTS = 6
#: Taken from the top of each axis — technology, and fit to what we sell —
#: before the overall cap. Two threes rather than one six, because the two
#: scores answer different questions.
PER_BUCKET = 3
#: How recent a post must be to reach a cadence — **applied by the reader, not
#: by the sweep.**
#:
#: Separate from the source's `max_age_days`, which governs the fetch: a SERP
#: page returns ten results whatever window is asked for, so narrowing the
#: query buys no credits and only changes which ten arrive — on a company that
#: posts quarterly it wastes the call. Fetch wide, select narrow.
#:
#: The first version applied this *during* the sweep, which quietly undid the
#: design — a stored post outside the window was gone, so changing the window
#: would have meant re-fetching, the one thing this is meant to avoid. It is
#: now what `strategy` passes to `post_ranking.pick` at read time, where
#: changing it is free.
PAYLOAD_DAYS = 90

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
    #: What the provider charged, and how many searches it charged for.
    #:
    #: Returned rather than only logged. It used to go into a note string and
    #: nowhere else, which left the account balance as the only signal — and a
    #: balance cannot say which run spent it, so a run costing ten times its
    #: neighbours stayed invisible until the credits ran out.
    credits: int = 0
    queries: int = 0


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


def _rank_posts(
    posts: list[FoundEvidence],
    *,
    fit: tuple[str, ...] = (),
    signals: tuple[str, ...] = (),
    window_days: int | None = None,
) -> tuple[list[FoundEvidence], list[post_ranking.Scored]]:
    """The posts worth keeping, and the scores that say why.

    Both are returned together because the note needs the scores and the batch
    needs the evidence; computing them in two places would let the stored rows
    and the explanation of them disagree.
    """
    scored = post_ranking.score(
        [p.excerpt or "" for p in posts],
        fit=fit,
        signals=signals,
        dates=[p.observed_at for p in posts],
    )
    chosen = post_ranking.pick(
        scored, per_bucket=PER_BUCKET, limit=MAX_POSTS, window_days=window_days
    )
    kept = []
    for s in chosen:
        post = posts[s.index]
        # The reason travels with the passage. `relevance` is what a rep reads
        # when asking why this post is in their draft, and a lexical score can
        # answer that where an embedding could not.
        post.relevance = f"indexed LinkedIn post · {s.why}"
        # **Third-party coverage, not the company's own voice.** Measured across
        # seven accounts: 45 post authors held one employee. These are trade
        # media and analysts talking *about* the company, so the reliability
        # sits below `company_site`'s first-hand 0.85 — a podcast host's take on
        # a launch is not the launch being announced.
        post.reliability = 0.6
        kept.append(post)
    return kept, chosen


async def sweep_account(account: Any, *, key: str | None = None, http=None,
                        max_age_days: int | None = 365,
                        fit: tuple[str, ...] = (),
                        signals: tuple[str, ...] = ()) -> SweepResult:
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
            # **Ranked before stored.** A page returns ten posts whatever we
            # ask, and on this book four companies in six return a full ten —
            # so the question is which to keep. Each kept one is an extraction
            # input token later, and the dropped ones leave no row because
            # evidence is immutable: what is stored is stored for good.
            # **No recency window here.** "Fetch wide, select narrow" means
            # the narrowing happens when strategy builds a payload, not when
            # the sweep stores — otherwise changing the window costs a
            # re-fetch, which is the thing that design exists to avoid.
            # Storage is bounded by the cap; `PAYLOAD_DAYS` is for the reader.
            kept, why = _rank_posts(posts.found, fit=fit, signals=signals)
            found.extend(kept)
            notes.append(post_ranking.note(len(posts.found), why))
            if not posts.found:
                misses.append(
                    f"no posts in the last {max_age_days} days" if max_age_days
                    else "no posts indexed"
                )
            elif not kept:
                # Seen and rejected is not the same as nothing indexed, and a
                # coverage screen that showed them alike would send a rep
                # looking for a source that is working fine.
                misses.append(
                    f"{len(posts.found)} post(s) indexed, none about technology "
                    "or what we sell"
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
        credits=profiles.credits + posts.credits,
        queries=2,
    )


#: The provider key under which the credential is stored. One name, used by the
#: catalogue entry, the probe and this reader, so a rename cannot leave the
#: reader looking for a row the settings screen never writes.
PROVIDER = "searlo"


@dataclass
class PersonSweep:
    """What the index holds about the people named, per person."""

    #: `{contact_id: [evidence]}`. A person with nothing gets no key.
    by_contact: dict = field(default_factory=dict)
    misses: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    credits: int = 0
    queries: int = 0
    error: str | None = None


async def sweep_people(
    account: Any,
    people: list,
    *,
    key: str | None = None,
    http=None,
    max_age_days: int | None = 365,
) -> PersonSweep:
    """One X-Ray query per person, read from the index rather than the model.

    **Why this exists.** The same search was being made by a grounded model
    call: `contact_content_activity` is a signal type whose instruction is
    literally `site:linkedin.com/posts "{person}" "{company}"`. That is a
    lookup, not a judgement — a fixed query whose results are parsed, with
    nothing for a model to decide — and it was costing a grounded search at
    $0.035 where a credit here is between $0.0003 and $0.01.

    **One query per person, not one per family.** The model call was batched
    across everybody, which was its one advantage; a query naming two people
    returns results for neither. The arithmetic still favours this below
    roughly three or thirty-five people depending on the credit price, and
    the waterfall gate in `pipeline` is what keeps the count low: these
    queries are only reached for a company the index already showed posting.

    Both operators in one query per person, which is the saving the separate
    profile and post queries in `sweep_account` do not take: a profile and a
    recent post for the same named person come back on one page often enough
    to be worth one credit instead of two.
    """
    company = (getattr(account, "name", None) or "").strip()
    if not company:
        return PersonSweep(misses=("no company name — nothing to search the index for",))
    if not key:
        # A missing credential is not a coverage gap. Saying "found nothing"
        # would be indistinguishable from a person with no public footprint.
        return PersonSweep(
            misses=("no SERP credential configured",),
            notes=("contact LinkedIn needs a Searlo key before it can read anything",),
        )

    after = window_from(max_age_days)
    own = http or _client(TIMEOUT)
    owned = http is None
    out = PersonSweep()
    misses: list[str] = []
    try:
        for person in people:
            name = (getattr(person, "full_name", None) or "").strip()
            if not name:
                misses.append("a contact with no name was not searched for")
                continue
            query = (
                f'(site:linkedin.com/posts OR site:linkedin.com/in) '
                f'"{name}" "{company}" {after}'.strip()
            )
            result = await _ask(own, key, query)
            out.queries += 1
            out.credits += result.credits
            if result.error:
                # Per person, so one refusal does not lose the others.
                misses.append(f"{name}: {result.error}")
                continue
            if result.found:
                out.by_contact[person.id] = result.found
            else:
                misses.append(f"nothing indexed for {name} at {company}")
    finally:
        if owned:
            await own.aclose()
    out.misses = tuple(misses)
    log.info(
        "linkedin_serp.people account=%s queries=%d credits=%d with_evidence=%d",
        getattr(account, "id", None), out.queries, out.credits, len(out.by_contact),
    )
    return out


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
            account,
            key=await api_key(session),
            max_age_days=max_age,
            fit=await fit_lexicon(session),
            signals=await signal_lexicon(session),
        )

    return read


async def signal_lexicon(session: AsyncSession) -> tuple[str, ...]:
    """The words the **active signal types** are looking for.

    This is what stops the ranking from undoing extraction's work. Scoring on
    technology and fit alone dropped a real post reading "After three
    remarkable years at WeaveGrid, it's time to…" — a departure, which
    `leadership_change_executive` exists to catch and which names no
    technology. A filter that runs before extraction has to know what
    extraction wants, and the registry is where that is written down.

    Taken from the type keys and labels rather than their full instructions: a
    key like `leadership_change_executive` is already a list of the right
    words, where a paragraph of instruction is mostly prose about how to judge.
    """
    from sqlalchemy import select

    from app.models.config import SignalType

    rows = (
        await session.execute(
            select(SignalType.key, SignalType.label).where(SignalType.status == "active")
        )
    ).all()
    return post_ranking.fit_terms(
        [k for k, _ in rows], [lbl for _, lbl in rows]
    )


async def fit_lexicon(session: AsyncSession) -> tuple[str, ...]:
    """The words that mean "relevant to what we sell", from what we sell.

    Read from the active services and the org's positioning rather than written
    into `post_ranking`: those are already maintained on the Services screen,
    and a second hand-kept list is the one that would go stale. An installation
    that sells something else gets a different lexicon for free.

    An empty tuple is a real answer — with no services configured, posts are
    ranked on the technology axis alone rather than on a lexicon invented here.
    """
    from sqlalchemy import select

    from app.models.config import OrgProfile, ServiceCatalog

    rows = (
        await session.execute(
            select(
                ServiceCatalog.name,
                ServiceCatalog.description,
                ServiceCatalog.positioning_angles,
            ).where(ServiceCatalog.is_active)
        )
    ).all()
    org = (
        await session.execute(select(OrgProfile).where(OrgProfile.is_active))
    ).scalars().first()
    return post_ranking.fit_terms(
        [name for name, _, _ in rows],
        [desc for _, desc, _ in rows],
        [a for _, _, angles in rows for a in (angles or [])],
        getattr(org, "positioning_angles", None) or [],
    )
