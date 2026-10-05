"""The call sites: one function per `llm_config` scenario.

Everything above this module is deterministic and testable without a network.
Everything below it is `llm.py`, which knows about Anthropic and nothing about
sales. This is the only layer that knows both, and it is deliberately thin —
each function assembles a prompt, makes one call, and hands back a validated
contract object. **No function here writes to the database.** Persistence stays
in the service that owns the invariant: `extraction.store_batch` drops signals
citing unknown evidence, `evidence.store_found` dedupes on excerpt,
`drafting.store_arc` bands the touches. Moving any of that here would put a
guard behind a network call and make it untestable.

The cached prefix is built once per stage and is identical across every account
in a batch — that is what makes a book of 200 accounts affordable. Anything
per-account goes in `messages`, which is not cached. `prompt.stable_json`
refuses timestamps and sets outright, so the usual ways of silently destroying
the cache raise instead.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Contact
from app.models.config import (
    IcpProfile,
    IcpProfileVersion,
    OrgProfile,
    ProofPoint,
    ResearchSource,
    ServiceCatalog,
    WritingSample,
    service_icp_link,
)
from app.models.context import AccountContext
from app.models.signal import Evidence, Signal
from app.schemas.contact import ContactBatch
from app.schemas.context import AccountContextPayload
from app.schemas.draft import DraftSet, FreshnessVerdict
from app.schemas.evaluation import EvaluationResult
from app.schemas.evidence import EvidenceBatch
from app.schemas.resolution import CompanyResolution
from app.schemas.prep import SalesPrepPayload
from app.schemas.qualification import DimensionAssessments
from app.schemas.signal import SignalBatch, build_batch_model
from app.schemas.strategy import StrategyProposal
from app.services import durability, instructions, llm, prompts
from app.services.prompt import PromptAssembly, build_research_prefix, stable_json
from app.services.query_families import BY_KEY
from app.services.research import build_plan

log = logging.getLogger(__name__)

#: Server-side search, for the research stages only. Every other stage reasons
#: over evidence we already hold — giving those tools would let a qualification
#: quietly introduce a fact with no evidence row behind it, which is the
#: citation chain's whole failure mode.
WEB_TOOLS: list[dict[str, Any]] = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
]
#: Search without fetch. LinkedIn forbids automated access and has won in court
#: over it, so the LinkedIn source may read what search results show and may
#: not open the page — which a fetch tool would do on the model's say-so.
SEARCH_ONLY_TOOLS: list[dict[str, Any]] = [WEB_TOOLS[0]]
SEARCH_ONLY_SOURCES = frozenset({"linkedin"})


def _tools_for(source: str) -> list[dict[str, Any]]:
    return SEARCH_ONLY_TOOLS if source in SEARCH_ONLY_SOURCES else WEB_TOOLS


# ==========================================================================
# the shared prefix
# ==========================================================================
async def load_prefix(
    session: AsyncSession,
    scenario: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    with_writing_samples: bool = False,
    instructions_key: str | None = None,
) -> PromptAssembly:
    """Build the cached prefix for a stage from active configuration.

    Writing samples are loaded only where voice matters. They are several
    hundred tokens of a very specific register, and putting them in front of a
    qualification would push it to *write* like an outreach email rather than
    assess like an analyst.
    """
    # The admin-editable instruction text. Loaded here rather than baked into
    # the module so an edit made in the UI is what actually runs on the next
    # call — which is the whole point of moving these out of git. `_COMMON` is
    # still prepended inside `instructions.block`, where a stored body cannot
    # displace it.
    stage_key = instructions_key or scenario
    stored_body, stored_version = await prompts.body_and_version(session, stage_key)

    org = (
        await session.execute(select(OrgProfile).where(OrgProfile.is_active.is_(True)))
    ).scalar_one_or_none()

    services = list(
        (
            await session.execute(
                select(ServiceCatalog).where(ServiceCatalog.is_active.is_(True))
            )
        ).scalars()
    )
    # Only approved claims may reach a prompt at all — `docs/01` invariant 8.
    # Filtered in the query as well as in `build_research_prefix`, because a
    # prompt is the one place an unapproved claim becomes unrecallable.
    proofs = list(
        (
            await session.execute(
                select(ProofPoint).where(ProofPoint.is_approved.is_(True))
            )
        ).scalars()
    )

    samples: list[str] = []
    if with_writing_samples:
        rows = list(
            (
                await session.execute(
                    select(WritingSample)
                    .where(WritingSample.is_active.is_(True))
                    .order_by(WritingSample.channel, WritingSample.id)
                )
            ).scalars()
        )
        samples = [
            f"[{s.channel}] {s.subject or ''}\n{s.body}".strip() for s in rows
        ]

    icp_rows = await _active_icps(session)

    return build_research_prefix(
        # Identity only — who is selling. Who we sell *to* now lives on the ICP
        # profiles, which ride in the catalogue block beside the services they
        # are linked to. That placement is deliberate: the catalogue is
        # identical for every account in a batch, so the cached prefix stays
        # byte-identical. Resolving one ICP per account and putting it here
        # would make the prefix vary per account and miss cache on every one.
        org_profile=(
            {"name": org.name, "description": org.description} if org else {}
        ),
        icp_profiles=[
            {
                "name": name,
                "description": desc,
                "definition": definition,
                "services": sorted(codes),
            }
            for name, desc, definition, codes in sorted(icp_rows)
        ],
        service_catalog=[
            {
                "id": str(s.id),
                "code": s.code,
                "name": s.name,
                "description": s.description,
                "positioning_angles": s.positioning_angles or [],
                "economic_buyer": s.economic_buyer,
            }
            for s in services
        ],
        approved_proofs=[
            {
                "id": str(p.id),
                "service_id": str(p.service_id) if p.service_id else None,
                "kind": p.kind,
                "title": p.title,
                "body": p.body,
                "metrics": p.metrics or {},
                "is_approved": p.is_approved,
            }
            for p in proofs
        ],
        # A stage can share a scenario's model config and still need its own
        # instructions — contact research runs on company research's model.
        stage_instructions=instructions.block(stage_key, stored_body),
        writing_samples=samples,
        tools=tools,
        prompt_version=stored_version,
    )


async def _active_icps(
    session: AsyncSession,
) -> list[tuple[str, str | None, dict, list[str]]]:
    """Every ICP that has an active definition, with the services it sells to.

    Profiles with no active version are left out rather than sent as empty:
    an ICP nobody has written describes no one, and putting `{}` in a prompt
    invites the model to invent the missing half.
    """
    rows = (
        await session.execute(
            select(
                IcpProfile.name,
                IcpProfile.description,
                IcpProfileVersion.definition,
                ServiceCatalog.code,
            )
            .join(
                IcpProfileVersion,
                IcpProfileVersion.icp_profile_id == IcpProfile.id,
            )
            .join(
                service_icp_link,
                service_icp_link.c.icp_profile_id == IcpProfile.id,
            )
            .join(
                ServiceCatalog,
                ServiceCatalog.id == service_icp_link.c.service_id,
            )
            .where(
                IcpProfileVersion.is_active.is_(True),
                ServiceCatalog.is_active.is_(True),
            )
        )
    ).all()

    merged: dict[str, tuple[str, str | None, dict, list[str]]] = {}
    for name, description, definition, code in rows:
        if name not in merged:
            merged[name] = (name, description, definition, [])
        merged[name][3].append(code)
    return list(merged.values())


def _account_facts(account: Account) -> dict[str, Any]:
    """The per-account block. Deliberately small and never cached."""
    return {
        "account_id": str(account.id),
        "name": account.name,
        "domain": account.domain,
        "industry": getattr(account, "industry", None),
        "employee_count": getattr(account, "employee_count", None),
        # The columns are hq_country and hq_region. This read `hq_location`,
        # which the model does not have, so every prompt was told nothing
        # about where a company is.
        "hq_country": getattr(account, "hq_country", None),
        "hq_region": getattr(account, "hq_region", None),
        # What LinkedIn searches identify the company by, and what the pipeline
        # checks a LinkedIn passage against.
        "linkedin_url": getattr(account, "linkedin_url", None),
        # What the company actually does: services, who it sells to, what it is
        # pushing. Without this the block was the company's name and its
        # postcode, and `strategy_synthesis` is told — for a thread with no
        # live trigger — to "make the case from the company's situation". It
        # was being asked to do that with nothing, and spent 53 seconds of
        # thinking trying before exhausting its budget.
        #
        # `sources` is dropped: URLs are for a rep checking a claim, and
        # nothing downstream reasons with them. Everything else is a sentence
        # or a short list, so the block stays small enough to deserve its
        # "deliberately small" description.
        "profile": _profile_facts(account),
    }


def _profile_facts(row: Any) -> dict[str, Any] | None:
    """A stored profile, trimmed for a prompt.

    `sources` goes: URLs are for a rep checking a claim, nothing downstream
    reasons with them, and they are the longest field. Empty fields go too — a
    key with nothing behind it invites the model to fill it in.
    """
    profile = getattr(row, "profile", None)
    if not isinstance(profile, dict) or not profile:
        return None
    return {k: v for k, v in profile.items() if k != "sources" and v} or None


def _contact_facts(person: Any) -> dict[str, Any]:
    """Who this person is, for a stage that has to argue to them.

    The four columns were all strategy got, and for a thread with no live
    signal that is a name and a job title to build a case from. What the
    person actually owns, what they write about and what they appear able to
    decide are in the profile, and they are the difference between an argument
    addressed to a role and one addressed to a person.

    Never their email or phone: those are columns on `contact` and they stay
    there. A prompt is the one place a contact detail could leak from.
    """
    return {
        "full_name": person.full_name,
        "title": person.title,
        "seniority": person.seniority,
        "buying_role": person.buying_role,
        "profile": _profile_facts(person),
    }


def _untrusted(label: str, body: str) -> str:
    """Wrap retrieved text so its boundary is explicit.

    Delimiters are not a security control — a determined injection crosses
    them. What they buy is that the model can *tell* where the quoted material
    starts and stops, which turns "ignore previous instructions" from an
    ambiguous string into an obvious feature of the quoted page. The actual
    control is that these stages have no capability worth hijacking: no send
    path, no database write, no credential.
    """
    return f"<{label}>\n{body}\n</{label}>"


async def _run[R](
    session: AsyncSession,
    scenario: str,
    *,
    prefix: PromptAssembly,
    user_content: str,
    output_model: type[R],
    client: Any | None = None,
) -> llm.CallResult[R]:
    config = await llm.stage_config(session, scenario)
    # Both skipped when a client is injected: a supplied client is the caller
    # taking responsibility for where the call goes, which is how tests and
    # fixtures work. Nothing reaches a real vendor through that path.
    if client is None:
        await llm.assert_may_call(session, scenario)
    # The key for *this stage's* provider. Passing the wrong one produces
    # "API key not valid", which reads as a bad credential rather than a
    # misrouted good one.
    api_key = (
        None if client is not None
        else await llm.stored_api_key(session, config.provider)
    )
    # Every stage funnels through here, so this is where spend is counted —
    # including the calls that fail, which are the ones nobody would otherwise
    # count and the ones a runaway budget shows up in first.
    started = time.monotonic()
    try:
        result = await llm.call_structured(
            config=config,
            prefix=prefix,
            user_content=user_content,
            output_model=output_model,  # type: ignore[arg-type]
            client=client,
            api_key=api_key,
        )
    except Exception as exc:
        await _record_call(
            session, config, started,
            error=f"{type(exc).__name__}: {exc}"[:500],
        )
        raise
    await _record_call(session, config, started, result=result)
    return result


async def _record_call(
    session: AsyncSession,
    config,
    started: float,
    *,
    result=None,
    error: str | None = None,
) -> None:
    """Write one row of the spend ledger. Never the reason a call is refused.

    **In its own transaction.** The first version flushed onto the caller's
    session, which meant a failed call wrote a row and then lost it: the
    exception propagated, the route never committed, and the row died with the
    transaction. The calls worth counting most — the ones that burned a budget
    and raised — were precisely the ones not counted. The test missed it by
    asserting inside the same session, before any rollback.

    Bookkeeping must not be able to fail the work it is measuring, so anything
    that goes wrong here is logged and swallowed.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.config import LlmCall

    row = dict(
        scenario=getattr(config, "scenario", "unknown"),
        provider=getattr(config, "provider", "unknown"),
        model=getattr(config, "model", "unknown"),
        effort=getattr(config, "effort", "unknown"),
        input_tokens=getattr(result, "input_tokens", 0) or 0,
        output_tokens=getattr(result, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(result, "cache_read_tokens", 0) or 0,
        cache_write_tokens=getattr(result, "cache_write_tokens", 0) or 0,
        duration_ms=int((time.monotonic() - started) * 1000),
        ok=error is None,
        error=error,
    )
    try:
        # Bound to the caller's own engine rather than the app's global
        # factory: same database, separate transaction. Reaching for the
        # global one sent rows to whatever `DATABASE_URL` pointed at, which
        # under test is not the database the test then looks in.
        # `get_bind()` hands back the sync engine behind the async one; the
        # async session it belongs to knows the async engine itself.
        engine = session.get_bind()
        engine = getattr(engine, "_async_engine", None) or session.bind or engine
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as ledger:
            ledger.add(LlmCall(**row))
            await ledger.commit()
    except Exception:  # noqa: BLE001 - measurement must not break the measured
        # `getattr`, because this runs when something about `config` is already
        # wrong: reading it here is what turned a swallowed failure back into a
        # raised one the first time this guard was tested.
        log.warning(
            "stages.spend_not_recorded scenario=%s",
            getattr(config, "scenario", "unknown"),
            exc_info=True,
        )


# ==========================================================================
# research
# ==========================================================================
async def research_family(
    session: AsyncSession,
    *,
    account: Account,
    family: str,
    client: Any | None = None,
) -> llm.CallResult[EvidenceBatch]:
    """Read one source for one account.

    One source per call, not all of them in one. Three reasons, in order of how
    much they cost when ignored: a failure costs one source rather than the
    account's whole research; coverage can record per source, which is what
    makes a gap nameable; and the sources that matter for an account can be run
    at different efforts.

    The brief comes from the registry row, so a source a rep added reads exactly
    like one that shipped with the product. `of_interest` names the conclusions
    somebody expected here — context for what counts as notable, never a filter.
    Narrowing the sweep to it is what made research cost one search per signal
    type and throw away most of what it paid for.
    """
    known = next(
        (
            row
            for row in (
                await session.execute(
                    select(ResearchSource).where(ResearchSource.key == family)
                )
            ).scalars()
        ),
        None,
    )
    fallback = BY_KEY.get(family)
    prefix = await load_prefix(session, "company_research", tools=_tools_for(family))

    plan = await build_plan(session)
    planned = plan.family(family)

    payload = {
        "account": _account_facts(account),
        "source": {
            "key": family,
            "label": (known.label if known else None)
            or (fallback.label if fallback else family),
            "read_for": (known.description if known else None)
            or (fallback.description if fallback else None),
            "scopes": list(known.scopes if known else (fallback.scopes if fallback else [])),
        },
        "of_interest": list(planned.feeds) if planned else [],
        # The oldest publication date any active signal type could still use.
        # Stated as a month, not a day — see `durability.cutoff_for_prompt`.
        "ignore_published_before": durability.cutoff_for_prompt(
            await durability.research_cutoff(session)
        ),
    }
    return await _run(
        session,
        "company_research",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=EvidenceBatch,
        client=client,
    )


async def suggest_type_sources(
    session: AsyncSession,
    *,
    signal_type: dict,
    registry: list[dict],
    client: Any | None = None,
) -> llm.CallResult[Any]:
    """Propose where one signal type is found, and whether it needs its own words.

    Runs on the extraction model: no web tools, a short input, and an answer a
    person accepts or edits. It never writes — a source claimed without anybody
    agreeing to it becomes a coverage gap reported on every account.
    """
    from app.schemas.config import TypeSourceSuggestion

    prefix = await load_prefix(
        session, "signal_extraction", instructions_key="type_sources"
    )
    return await _run(
        session,
        "signal_extraction",
        prefix=prefix,
        user_content=_untrusted(
            "signal_type",
            stable_json({"signal_type": signal_type, "sources": registry}),
        ),
        output_model=TypeSourceSuggestion,
        client=client,
    )


async def suggest_icp_sources(
    session: AsyncSession,
    *,
    icp: dict,
    types: list[dict],
    registry: list[dict],
    client: Any | None = None,
) -> llm.CallResult[Any]:
    """Assemble the sources an ICP should read, with a reason for each.

    The union of what its signal types name is arithmetic and could be done in
    Python. What cannot is the other half: which source this *industry* rewards
    reading, and which of the named ones this ICP would not benefit from. That
    is the judgement being asked for, and it is why the answer is a proposal a
    rep edits rather than a computed list.
    """
    from app.schemas.config import IcpSourceSuggestions

    prefix = await load_prefix(
        session, "signal_extraction", instructions_key="icp_sources"
    )
    return await _run(
        session,
        "signal_extraction",
        prefix=prefix,
        user_content=_untrusted(
            "icp",
            stable_json({"icp": icp, "signal_types": types, "sources": registry}),
        ),
        output_model=IcpSourceSuggestions,
        client=client,
    )


async def suggest_search_groups(
    session: AsyncSession,
    *,
    candidates: list[dict],
    client: Any | None = None,
) -> llm.CallResult[Any]:
    """Propose which type-owned searches could share one call.

    Runs on the extraction model rather than the research one: no web tools, a
    short input, and a suggestion a person accepts or rejects. It proposes and
    never applies — a grouping is a change to what every later search asks for.
    """
    from app.schemas.config import SearchGroupSuggestions

    prefix = await load_prefix(
        session, "signal_extraction", instructions_key="search_grouping"
    )
    return await _run(
        session,
        "signal_extraction",
        prefix=prefix,
        user_content=_untrusted("signal_types", stable_json({"types": candidates})),
        output_model=SearchGroupSuggestions,
        client=client,
    )


async def research_topic(
    session: AsyncSession,
    *,
    account: Account,
    brief: dict,
    client: Any | None = None,
) -> llm.CallResult[EvidenceBatch]:
    """Run a search a signal type carries itself.

    The same call as `research_family`, with the instruction coming from the
    registry rather than from code. That is the whole point of the type-owned
    path: the person who wants something found writes what to look for, and no
    deploy stands between them and research doing it.
    """
    prefix = await load_prefix(session, "company_research", tools=WEB_TOOLS)
    payload = {
        "account": _account_facts(account),
        "source": {
            "key": brief["key"],
            "label": brief.get("label") or brief["key"],
            # A rep's words, quoted as data: this is an instruction *about what
            # to look for*, not an instruction to the model about how to behave.
            "read_for": brief["instruction"],
            "scopes": list(brief.get("scopes") or []),
        },
        "of_interest": list(brief.get("feeds") or []),
        "ignore_published_before": durability.cutoff_for_prompt(
            await durability.research_cutoff(session)
        ),
    }
    return await _run(
        session,
        "company_research",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=EvidenceBatch,
        client=client,
    )


async def research_contacts(
    session: AsyncSession,
    *,
    account: Account,
    family: str,
    people: list,
    client: Any | None = None,
) -> llm.CallResult[Any]:
    """Run one query family for up to three named people at one account.

    One call for the people rather than one each: the family and the account
    are the same, and three calls would pay three times for the same context.
    Every passage comes back tagged with whose it is, and `pipeline` files it
    under that person — or drops it, if the id is not one it sent.

    Runs on company research's model and web tools, with its own instructions:
    the hard part here is not finding pages but being sure a page is about
    *this* person and not a namesake.

    No email address travels. It is not needed to search for someone, and a
    prompt is the one place a contact detail could leak from.
    """
    from app.schemas.evidence import ContactEvidenceBatch

    known = BY_KEY.get(family)
    prefix = await load_prefix(
        session, "company_research", tools=_tools_for(family), instructions_key="contact_research"
    )
    plan = await build_plan(session, scope="contact")
    planned = plan.family(family)

    payload = {
        "account": _account_facts(account),
        "family": {
            "key": family,
            "label": known.label if known else family,
            "description": known.description if known else None,
        },
        "feeds_signal_types": list(planned.feeds) if planned else [],
        "ignore_published_before": durability.cutoff_for_prompt(
            await durability.research_cutoff(session)
        ),
        # Names and titles are imported data, never instructions.
        "people": [
            {
                "contact_id": str(p.id),
                "full_name": p.full_name,
                "title": p.title,
                "linkedin_url": p.linkedin_url,
            }
            for p in people
        ],
    }
    return await _run(
        session,
        "company_research",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=ContactEvidenceBatch,
        client=client,
    )


async def resolve_company(
    *,
    account: Account,
    session: AsyncSession | None = None,
    client: Any | None = None,
) -> llm.CallResult[CompanyResolution]:
    """Tier 0's fallback: which company is this row actually about?

    Reached only when there is no domain to look up — Apollo answers that case
    from a database, far more cheaply and with a confidence that means
    something. This is for a CSV carrying names alone.

    Shares the `company_research` scenario rather than declaring its own. It is
    the same kind of work with the same web tooling, and one `llm_config` row
    is a smaller thing to maintain than two. Splitting it out later is a
    one-row change, and worth doing the moment somebody wants to tune effort
    for a call that runs on every account.

    The prompt asks what the row *could* mean, never what it does mean. A model
    asked for one company always produces one; asked which companies match and
    how sure it is, it can report genuine ambiguity — which is the whole
    purpose of the step.
    """
    own = session is None
    if own:
        from app.database import SessionLocal

        session = SessionLocal()
    try:
        prefix = await load_prefix(session, "company_research", tools=WEB_TOOLS)
        payload = {
            "row": {
                "name": account.name,
                "domain": account.domain,
                "linkedin_url": account.linkedin_url,
                "industry": account.industry,
                "hq_country": getattr(account, "hq_country", None),
                "hq_region": getattr(account, "hq_region", None),
            },
            "task": (
                "Identify which real company this spreadsheet row refers to. "
                "List every plausible candidate with a confidence, best first. "
                "Report genuine ambiguity rather than choosing: two companies "
                "sharing a name is a finding, not a problem to resolve."
            ),
        }
        return await _run(
            session,
            "company_research",
            prefix=prefix,
            user_content=stable_json(payload),
            output_model=CompanyResolution,
            client=client,
        )
    finally:
        if own:
            await session.close()


async def signal_scan(
    session: AsyncSession, *, account: Account, client: Any | None = None
) -> llm.CallResult[EvidenceBatch]:
    """The cheap sweep that decides whether a full run is worth buying."""
    prefix = await load_prefix(session, "signal_scan", tools=WEB_TOOLS)
    plan = await build_plan(session)
    payload = {
        "account": _account_facts(account),
        "families_available": plan.keys,
    }
    return await _run(
        session,
        "signal_scan",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=EvidenceBatch,
        client=client,
    )


async def company_profile(
    session: AsyncSession, *, account: Account, client: Any | None = None
) -> llm.CallResult[Any]:
    """What the company is — firmographics, not a trigger.

    Runs on company research's model and web tools with its own instructions,
    the same arrangement contact research uses: the hard part is not finding
    pages but knowing which questions this stage answers and which belong to
    signal research.

    Deliberately **not** gated on recency. Everything else research stores is
    checked against a durability window; a description of a business has no
    date to check, and applying one would discard a standing fact for being old
    when it is simply true.
    """
    from app.schemas.profile import CompanyProfile

    prefix = await load_prefix(
        session, "company_research", tools=WEB_TOOLS,
        instructions_key="company_profile",
    )
    return await _run(
        session,
        "company_research",
        prefix=prefix,
        user_content=stable_json({"account": _account_facts(account)}),
        output_model=CompanyProfile,
        client=client,
    )


async def contact_profile(
    session: AsyncSession,
    *,
    account: Account,
    person: Any,
    client: Any | None = None,
) -> llm.CallResult[Any]:
    """Who one person is at this company, as standing description.

    One person per call rather than three together. Company research can share
    a call across people because the question is the same; here each answer is
    a different person's role, and a single response covering three invites the
    model to blur them — which is the wrong-person failure contact research
    already guards against, arriving by a different route.

    Undated and ungated, like the company profile: a profile page carries no
    publication time, and `linkedin.post_date` returns None for a `/in/` URL.
    That is the correct answer, not a gap to fill.

    No email address travels, in or out.
    """
    from app.schemas.profile import ContactProfile

    prefix = await load_prefix(
        session, "company_research", tools=WEB_TOOLS,
        instructions_key="contact_profile",
    )
    payload = {
        "account": _account_facts(account),
        # Names and titles are imported data, never instructions.
        "person": {
            "full_name": getattr(person, "full_name", None),
            "title": getattr(person, "title", None),
            "linkedin_url": getattr(person, "linkedin_url", None),
        },
    }
    return await _run(
        session,
        "company_research",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=ContactProfile,
        client=client,
    )


async def enrich_decision_makers(
    session: AsyncSession,
    *,
    account: Account,
    evidence: list[Evidence],
    client: Any | None = None,
) -> llm.CallResult[ContactBatch]:
    """Who at this account would care. Never how to reach them."""
    prefix = await load_prefix(session, "decision_maker_enrichment", tools=WEB_TOOLS)
    payload = {
        "account": _account_facts(account),
        "evidence": [_evidence_facts(e) for e in evidence],
    }
    return await _run(
        session,
        "decision_maker_enrichment",
        prefix=prefix,
        user_content=_untrusted("retrieved_evidence", stable_json(payload)),
        output_model=ContactBatch,
        client=client,
    )


# ==========================================================================
# structuring
# ==========================================================================
def _evidence_facts(row: Evidence) -> dict[str, Any]:
    return {
        "evidence_id": str(row.id),
        # Contact research files a passage under the person it is about, and a
        # contact-scoped signal has to cite passages about that same person.
        "about_contact_id": str(row.contact_id) if row.contact_id else None,
        "source_type": row.source_type,
        "source_url": row.source_url,
        "source_name": row.source_name,
        "title": row.title,
        "excerpt": row.excerpt,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "reliability": float(row.reliability) if row.reliability is not None else None,
    }


async def extract_signals(
    session: AsyncSession,
    *,
    account: Account,
    evidence: list[Evidence],
    type_keys: list[str],
    contacts: list | None = None,
    client: Any | None = None,
) -> llm.CallResult[SignalBatch]:
    """Interpret held evidence into typed signals.

    The output schema is built from the *active* registry rather than
    hardcoded, so `signal_type` is a `Literal` over exactly the keys that
    exist. That is what stops the model inventing a type no scoring weight and
    no research family knows about — a signal that would be stored, counted,
    and permanently unexplainable.

    No web tools. This stage interprets what we already hold; letting it search
    would let a signal cite evidence that has no row, and the extraction guard
    would then drop it looking exactly like a hallucination.
    """
    prefix = await load_prefix(session, "signal_extraction")
    payload = {
        "account": _account_facts(account),
        "evidence": [_evidence_facts(e) for e in evidence],
        "signal_types_available": sorted(type_keys),
        # A contact-scoped type must name one of these people. Without the list
        # the model can only guess an id, and the guard would drop the signal.
        "people": [
            {"contact_id": str(c.id), "full_name": c.full_name, "title": c.title}
            for c in (contacts or [])
        ],
    }
    return await _run(
        session,
        "signal_extraction",
        prefix=prefix,
        user_content=_untrusted("retrieved_evidence", stable_json(payload)),
        output_model=build_batch_model(sorted(type_keys)),
        client=client,
    )


async def structure_manual_intel(
    session: AsyncSession,
    *,
    account: Account,
    note: str,
    evidence: list[Evidence],
    type_keys: list[str],
    client: Any | None = None,
) -> llm.CallResult[SignalBatch]:
    """Turn a rep's note into typed signals against its own evidence row.

    The note must already have been written as `source_type='manual'` evidence
    before this is called — that row is what the resulting signals cite. A
    signal citing a note that was never stored is dropped by the guard, which
    is correct but looks like the model failing rather than the caller.
    """
    prefix = await load_prefix(session, "manual_intel_structuring")
    payload = {
        "account": _account_facts(account),
        "evidence": [_evidence_facts(e) for e in evidence],
        "signal_types_available": sorted(type_keys),
    }
    content = (
        _untrusted("rep_note", note) + "\n\n" + _untrusted("stored_evidence", stable_json(payload))
    )
    return await _run(
        session,
        "manual_intel_structuring",
        prefix=prefix,
        user_content=content,
        output_model=build_batch_model(sorted(type_keys)),
        client=client,
    )


async def read_context(
    session: AsyncSession,
    *,
    account: Account,
    signals: list[Signal],
    previous: AccountContext | None = None,
    client: Any | None = None,
) -> llm.CallResult[AccountContextPayload]:
    """The narrative overlay on the deterministic signal list."""
    prefix = await load_prefix(session, "context_builder")
    payload = {
        "account": _account_facts(account),
        "signals": [
            {
                "signal_id": str(s.id),
                "type": s.signal_type,
                "scope": s.scope,
                "summary": s.summary,
                "business_implication": s.business_implication,
                "strength": s.strength,
                "confidence": float(s.confidence),
                "observed_at": s.observed_at.isoformat(),
                "is_hypothesis": s.is_hypothesis,
            }
            for s in signals
        ],
        "previous_summary": (
            (previous.payload or {}).get("narrative", {}).get("summary")
            if previous
            else None
        ),
    }
    return await _run(
        session,
        "context_builder",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=AccountContextPayload,
        client=client,
    )


# ==========================================================================
# qualification
# ==========================================================================
async def assess_dimensions(
    session: AsyncSession,
    *,
    account: Account,
    context: AccountContext,
    evidence: list[Evidence],
    client: Any | None = None,
) -> llm.CallResult[DimensionAssessments]:
    """Judge the six dimensions. The roll-up is not asked for.

    Only the assessments come back, never a priority score. That separation is
    what makes re-scoring the entire book a batch job over stored reasons
    instead of thousands of calls — change a weight, recompute, done.
    """
    prefix = await load_prefix(session, "qualification_assessment")
    payload = {
        "account": _account_facts(account),
        "context": context.payload,
        "evidence": [_evidence_facts(e) for e in evidence],
    }
    return await _run(
        session,
        "qualification_assessment",
        prefix=prefix,
        user_content=_untrusted("retrieved_evidence", stable_json(payload)),
        output_model=DimensionAssessments,
        client=client,
    )


# ==========================================================================
# strategy
# ==========================================================================
async def synthesise_strategy(
    session: AsyncSession,
    *,
    account: Account,
    context: AccountContext,
    threads: list[dict[str, Any]],
    contacts: list[Contact],
    client: Any | None = None,
) -> llm.CallResult[StrategyProposal]:
    """Argue every active thread at one account, in one call.

    One call for the whole account rather than one per thread, because
    `assert_differentiated` needs the arguments to have been written in sight
    of each other. Per-thread calls cannot differ from threads they never saw,
    and the check would then reject work that had no way to comply.
    """
    prefix = await load_prefix(session, "strategy_synthesis")
    by_id = {c.id: c for c in contacts}
    payload = {
        "account": _account_facts(account),
        "context": context.payload,
        # Stated as a number as well as implied by the list, because the array
        # it governs cannot be bounded in the schema: `maxItems` on
        # `StrategyProposal.threads` reaches Gemini and comes back HTTP 400
        # (§52, measured). The prompt is the only lever left, and a model
        # writing threads until the output budget runs out is what happens
        # without it — 7,986 tokens of answer for a single asked-for thread,
        # with zero tokens of thinking.
        "thread_count": len(threads),
        "threads_to_argue": [
            {
                **t,
                "contact": (
                    _contact_facts(by_id[t["contact_id"]])
                    if uuid.UUID(str(t["contact_id"])) in by_id
                    else None
                ),
            }
            for t in threads
        ],
    }
    return await _run(
        session,
        "strategy_synthesis",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=StrategyProposal,
        client=client,
    )


# ==========================================================================
# drafting
# ==========================================================================
async def draft_arc(
    session: AsyncSession,
    *,
    account: Account,
    contact: Contact,
    thread: dict[str, Any],
    shape: dict[str, Any],
    signals: list[Signal],
    client: Any | None = None,
) -> llm.CallResult[DraftSet]:
    """Write every touch in one call.

    One call per thread, not per touch. The arc has to build rather than
    restate itself, which needs the model to see the whole shape — and a rep
    approves once per thread rather than once per touch. Six approvals across
    24 threads is 144 review actions, at which point the rep stops using the
    system and the approval gate becomes theatre.

    The cadence comes in as `shape`, already selected. Touch count and timing
    belong to LGM; this stage fills a registered shape's variables and never
    authors one.
    """
    prefix = await load_prefix(session, "outreach_drafting", with_writing_samples=True)
    payload = {
        "account": _account_facts(account),
        "contact": {
            "full_name": contact.full_name,
            "title": contact.title,
            "seniority": contact.seniority,
            "buying_role": contact.buying_role,
        },
        "thread": thread,
        # Fixed by LGM. Not a suggestion, and there is no step editor anywhere.
        "cadence": shape,
        "signals": [
            {
                "signal_id": str(s.id),
                "type": s.signal_type,
                "summary": s.summary,
                "business_implication": s.business_implication,
                "observed_at": s.observed_at.isoformat(),
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "is_hypothesis": s.is_hypothesis,
            }
            for s in signals
        ],
    }
    return await _run(
        session,
        "outreach_drafting",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=DraftSet,
        client=client,
    )


async def revalidate_before_send(
    session: AsyncSession,
    *,
    account: Account,
    touch: dict[str, Any],
    signals: list[Signal],
    recent_events: list[str] | None = None,
    client: Any | None = None,
) -> llm.CallResult[FreshnessVerdict]:
    """Proceed or stop. There is no third answer.

    Low effort by configuration and by design: the content is frozen on the LGM
    lead, so this call has no power to rewrite anything. Giving it one would
    produce copy that differs from what LGM will actually send.
    """
    prefix = await load_prefix(session, "pre_send_revalidation")
    payload = {
        "account": _account_facts(account),
        "touch": touch,
        "cited_signals": [
            {
                "signal_id": str(s.id),
                "summary": s.summary,
                "observed_at": s.observed_at.isoformat(),
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "superseded": s.superseded_by is not None,
            }
            for s in signals
        ],
        "recent_events": recent_events or [],
    }
    return await _run(
        session,
        "pre_send_revalidation",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=FreshnessVerdict,
        client=client,
    )


# ==========================================================================
# governance
# ==========================================================================
async def evaluate(
    session: AsyncSession,
    *,
    subject_type: str,
    subject: dict[str, Any],
    criteria: list[str],
    client: Any | None = None,
) -> llm.CallResult[EvaluationResult]:
    """Check one artefact and say specifically what is wrong with it."""
    prefix = await load_prefix(session, "evaluation")
    payload = {
        "subject_type": subject_type,
        "subject": subject,
        "criteria": criteria,
    }
    return await _run(
        session,
        "evaluation",
        prefix=prefix,
        user_content=stable_json(payload),
        output_model=EvaluationResult,
        client=client,
    )


# ==========================================================================
# prep — Phase 12, held. The contract and call site exist; nothing calls them.
# ==========================================================================
async def generate_prep(
    session: AsyncSession,
    *,
    account: Account,
    contact: Contact,
    thread: dict[str, Any],
    already_sent: list[dict[str, Any]],
    replies: list[str],
    client: Any | None = None,
) -> llm.CallResult[SalesPrepPayload]:
    """One brief, one contact, on demand.

    Never in batch and never in advance: at 24 threads and roughly 3 meetings
    it is about 8x waste, and a brief written on day 0 for a call on day 18
    argues from a picture predating the entire conversation.
    """
    prefix = await load_prefix(session, "sales_prep", with_writing_samples=True)
    payload = {
        "account": _account_facts(account),
        "contact": {
            "full_name": contact.full_name,
            "title": contact.title,
            "seniority": contact.seniority,
            "buying_role": contact.buying_role,
        },
        "thread": thread,
        "already_sent": already_sent,
    }
    content = stable_json(payload)
    if replies:
        # Their words, quoted. A reply is the most valuable text in the system
        # and the most obvious place for an injection to arrive.
        content += "\n\n" + _untrusted("prospect_replies", "\n---\n".join(replies))
    return await _run(
        session,
        "sales_prep",
        prefix=prefix,
        user_content=content,
        output_model=SalesPrepPayload,
        client=client,
    )
