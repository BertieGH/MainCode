"""What to research, and what was actually covered.

The plan is derived rather than written down anywhere, and it is derived from
two places that answer different questions:

* the **ICP** says which sources to read — the plan of record, versioned with
  the ICP so a run in August stays explainable after somebody edits sources in
  October;
* the **signal types** say which conclusions each source was expected to
  support, which is what turns "the news sweep found nothing" into "we could
  not reach funding or leadership here".

When an ICP names no sources the plan falls back to the union of what its
signal types claim, which is how research behaved before sources were
configurable.

One rule holds the design together and is easy to erode: **a source decides
what gets opened, never what gets read out of it.** Extraction reads every
document against every active type, so a leadership change mentioned in a job
posting is still found. `feeds` is for reporting what a gap cost, not for
narrowing what a sweep may return.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import ResearchSource, SignalType
from app.models.research import ResearchCoverage
from app.models.signal import Evidence


#: Marks a search a signal type carries itself, so its coverage rows cannot be
#: confused with a code-backed family's. There is already a `funding` family
#: *and* a `funding` type; without the prefix their coverage would be one row.
TYPE_SEARCH = "type:"
GROUP_SEARCH = "group:"


def merged_instruction(members) -> str:
    """One brief for several types, each labelled so passages can be attributed.

    Written as a list rather than a paragraph: the model is being asked to
    cover several things in one search, and a prose merge quietly drops the
    third one.
    """
    if len(members) == 1:
        return (members[0].search_instruction or "").strip()
    lines = [
        "Cover each of the following. Treat them as separate questions sharing "
        "one search, and say which one a passage answers:"
    ]
    for member in members:
        lines.append(
            f"- {member.key} ({member.label}): {(member.search_instruction or '').strip()}"
        )
    return "\n".join(lines)


#: Cheapest first. A tier buys everything at or below it, so the index of a
#: name in this tuple is the whole comparison.
#:
#: Measured, not guessed. Over the first week the two light paid sources
#: produced 125 signals between them and the two deep ones produced 8 —
#: fifteen times dearer per signal — and light reaches 85% of every signal
#: found for 29% of what a run costs.
TIERS = ("light", "standard", "deep")


def within(tier: str, ceiling: str) -> bool:
    """Is a source at `tier` bought by a run at `ceiling`?

    An unknown name is treated as light rather than refused. A tier is a
    spending limit, and the failure that matters is the one that quietly
    stops buying a source nobody has tiered — not the one that buys it.
    """
    try:
        return TIERS.index(tier) <= TIERS.index(ceiling)
    except ValueError:
        return True


@dataclass(frozen=True)
class PlannedFamily:
    family: str
    #: The signal types that depend on this family. If it comes back empty,
    #: these are the conclusions we could not reach — which is what a rep needs
    #: to be told, rather than the family name on its own.
    feeds: tuple[str, ...]
    scopes: tuple[str, ...]
    support_only: bool
    #: Set when the search came from the types themselves rather than from a
    #: registered source — the words a rep wrote in "what to look for".
    instruction: str | None = None
    #: How the reading happens: `search`, `fetch`, `provider`, `manual`.
    kind: str = "search"
    #: How much an account must be worth before this is bought for it.
    tier: str = "light"
    label: str = ""
    #: True when the ICP asked for this source but no signal type named it.
    #: Its gap costs no named conclusion, and saying so stops a rep reading an
    #: empty extra source as a hole in the qualification.
    extra: bool = False

    @property
    def can_create_signals(self) -> bool:
        return not self.support_only

    @property
    def type_owned(self) -> bool:
        return self.family.startswith((TYPE_SEARCH, GROUP_SEARCH))


@dataclass
class ResearchPlan:
    families: list[PlannedFamily] = field(default_factory=list)
    #: Types nothing in this plan targets. What that costs depends on the rest
    #: of the plan, which is why `targeting_is_fatal` exists rather than a
    #: single scary word: with sources running, an untargeted type is merely
    #: less likely to be found, because extraction reads every document against
    #: every type. With nothing running it can never fire at all.
    orphan_types: list[str] = field(default_factory=list)

    def family(self, key: str) -> PlannedFamily | None:
        return next((f for f in self.families if f.family == key), None)

    @property
    def keys(self) -> list[str]:
        return [f.family for f in self.families]

    @property
    def targeting_is_fatal(self) -> bool:
        """Would an untargeted type never fire, rather than just rarely?"""
        return not any(f.can_create_signals for f in self.families)


async def build_plan(
    session: AsyncSession,
    *,
    scope: str | None = None,
    type_keys: set[str] | frozenset[str] | None = None,
    source_keys: set[str] | frozenset[str] | None = None,
    exclude: set[str] | frozenset[str] = frozenset(),
    #: The spending ceiling. `deep` is the default so that every existing
    #: caller keeps the plan it had — a tier that narrowed a plan by default
    #: would quietly stop buying sources nobody had asked it to drop.
    tier: str = "deep",
) -> ResearchPlan:
    """Derive the plan from the active registry and the chosen signal types.

    **Normally the sources are derived**, as the union of `produced_by` across
    the types in play, minus `exclude`. One list instead of two: a source is
    read because a signal type says its fact lives there, which is the only
    reason there has ever been.

    The second list used to be the ICP's own, and it took precedence. That is
    two gates with nothing reconciling them, and both directions failed within
    one week — `linkedin_serp` was claimed by three types and never ran because
    the ICP omitted it (§77), while `reviews` ran with no type claiming it at
    all. Deriving makes both unrepresentable.

    `exclude` keeps the one thing the second list was good for: cost control
    per ICP. `d1a7e9c45b82` dropped `funding` and `tech_stack` for a book of
    brokerages — sixteen calls for one passage — while keeping the types, so
    they return the day a technology ICP exists. Subtracting says that without
    letting the two lists disagree about what exists.

    `source_keys` still forces an exact set, for callers that want to plan one
    named source rather than an ICP's worth.

    Paused and deprecated types are excluded either way: pausing a type is
    meant to stop it being extracted, and running research for a source nothing
    active consumes spends budget on evidence no signal will ever cite.
    """
    stmt = select(SignalType).where(SignalType.status == "active")
    if scope:
        stmt = stmt.where(SignalType.scope == scope)
    if type_keys is not None:
        # An ICP's "signals that matter". Research looks only for what the list
        # is worked for — anything else is paid for and never counts.
        stmt = stmt.where(SignalType.key.in_(set(type_keys)))
    types = list((await session.execute(stmt)).scalars())

    registry = {s.key: s for s in (await session.execute(select(ResearchSource))).scalars()}

    feeds: dict[str, list[str]] = {}
    owned: dict[str, list] = {}
    plan = ResearchPlan()
    for st in types:
        if st.produced_by:
            for fam in st.produced_by:
                feeds.setdefault(fam, []).append(st.key)
        if (st.search_instruction or "").strip():
            # An exception: something a sweep of the ordinary sources reliably
            # misses, so the type carries the words that find it. An extra
            # search rather than a replacement — claiming a source and writing
            # an instruction are both allowed, and mean both run.
            group = (st.search_group or "").strip()
            key = f"{GROUP_SEARCH}{group}" if group else f"{TYPE_SEARCH}{st.key}"
            owned.setdefault(key, []).append(st)

    # Derived from what the types claim, less anything switched off. An
    # explicit `source_keys` still wins, for callers planning one named source.
    planned_keys = (set(source_keys) if source_keys is not None else set(feeds)) - set(
        exclude
    )

    # Sorted so two runs with the same registry produce the same plan. Set
    # iteration order would make the prompt built from this non-deterministic,
    # and a prompt that differs byte-for-byte between runs never hits cache.
    for fam in sorted(planned_keys):
        known = registry.get(fam)
        if known is not None and known.status != "active":
            continue
        # Scope decides where a family may run. A source the registry does not
        # know is treated as company-scoped rather than as scopeless: the
        # permissive reading let `job_board` run once per *person*, searching
        # for the company's Greenhouse board under each of their names, and
        # three contacts cost 138 model calls for three passages. The registry
        # row was missing at the time, which is exactly the condition this
        # guard has to survive.
        allowed = tuple(known.scopes or ()) if known is not None else ("company",)
        if scope and scope not in allowed:
            continue
        # **The ceiling.** Everything else in this loop decides whether a
        # source *can* answer; this decides whether it is worth asking. The
        # two are kept apart deliberately — a source dropped for its tier is
        # still one that would have worked, and a later run at a higher tier
        # must find it exactly where it left it.
        if known is not None and not within(known.tier, tier):
            continue
        if known is not None and known.kind not in ("search", "fetch"):
            # A provider waterfall or a rep's keyboard. Fanning research out
            # over these would spend Apollo credits as though they were tokens,
            # and would "run" a source whose definition is that a person typed
            # it. Their coverage is reported from where the work actually
            # happens — see `query_families.Runner`. A `fetch` source *is* run
            # here: it costs a couple of HTTP requests and no credits.
            continue
        plan.families.append(
            PlannedFamily(
                family=fam,
                feeds=tuple(sorted(feeds.get(fam, ()))),
                scopes=tuple(known.scopes) if known else (),
                support_only=known.support_only if known else False,
                kind=known.kind if known else "search",
                tier=known.tier if known else "light",
                label=known.label if known else fam,
                extra=not feeds.get(fam),
            )
        )

    for key in sorted(owned):
        members = sorted(owned[key], key=lambda t: t.key)
        plan.families.append(
            PlannedFamily(
                family=key,
                feeds=tuple(m.key for m in members),
                scopes=tuple(sorted({m.scope for m in members})),
                support_only=False,
                instruction=merged_instruction(members),
                label=members[0].label if len(members) == 1 else key.partition(":")[2],
            )
        )

    # Anything no planned source was asked to turn up. Reported rather than
    # refused: with sources running it is "less likely to be found", not
    # "impossible" — see `ResearchPlan.targeting_is_fatal`.
    targeted = {key for planned in plan.families for key in planned.feeds}
    plan.orphan_types = sorted(st.key for st in types if st.key not in targeted)
    return plan


async def search_brief(session: AsyncSession, key: str) -> dict | None:
    """What a type-owned search is looking for, rebuilt from the registry.

    The runner is handed a key and nothing else — the same shape a family
    runner gets — so the brief is read back here rather than carried through
    the pipeline. It also means an instruction edited between planning and
    running is the one that runs, which is the version a rep just typed.
    """
    if not key.startswith((TYPE_SEARCH, GROUP_SEARCH)):
        return None
    kind, _, name = key.partition(":")
    stmt = select(SignalType).where(SignalType.status == "active")
    stmt = (
        stmt.where(SignalType.search_group == name)
        if kind == "group"
        else stmt.where(SignalType.key == name)
    )
    members = sorted((await session.execute(stmt)).scalars(), key=lambda t: t.key)
    members = [m for m in members if (m.search_instruction or "").strip()]
    if not members:
        return None
    label = name.replace("_", " ") if kind == "type" else name
    return {
        "key": key,
        "label": members[0].label if kind == "type" else label,
        "instruction": merged_instruction(members),
        "feeds": [m.key for m in members],
        "scopes": sorted({m.scope for m in members}),
    }


async def record_coverage(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    account_id: uuid.UUID,
    family: str,
    evidence_count: int,
    failed: str | None = None,
    skipped: str | None = None,
    not_found: tuple[str, ...] | list[str] = (),
    notes: tuple[str, ...] | list[str] = (),
    contact_id: uuid.UUID | None = None,
) -> ResearchCoverage:
    """Write what happened to one family.

    Called for every planned family including the ones that found nothing —
    that is the entire point. Omitting the empty ones would leave coverage
    looking complete because only successes were recorded.
    """
    if failed is not None:
        status, count, detail = "failed", 0, failed
    elif skipped is not None:
        status, count, detail = "skipped", 0, skipped
    elif evidence_count > 0:
        status, count, detail = "ran", evidence_count, None
    else:
        status, count, detail = "empty", 0, None

    row = ResearchCoverage(
        run_id=run_id,
        account_id=account_id,
        family=family,
        status=status,
        evidence_count=count,
        detail=detail,
        not_found=list(not_found),
        notes=list(notes),
        contact_id=contact_id,
    )
    session.add(row)
    await session.flush()
    return row


@dataclass(frozen=True)
class Gap:
    family: str
    status: str
    #: Conclusions that are now unreachable for this account.
    unreachable: tuple[str, ...]
    detail: str | None = None

    @property
    def is_failure(self) -> bool:
        """A failure is 'we do not know'. Empty is 'there is nothing there'.

        Shown as the same thing, a rep would read a broken provider as a quiet
        prospect and walk away from a live one.
        """
        return self.status == "failed"


async def gaps_for_run(
    session: AsyncSession, run_id: uuid.UUID, plan: ResearchPlan
) -> list[Gap]:
    """Every planned family that produced nothing, and what it cost us."""
    rows = list(
        (
            await session.execute(
                # The company plan's gaps; people have their own rows.
                select(ResearchCoverage).where(
                    ResearchCoverage.run_id == run_id, ResearchCoverage.contact_id.is_(None)
                )
            )
        ).scalars()
    )
    seen = {r.family: r for r in rows}

    out: list[Gap] = []
    for planned in plan.families:
        row = seen.get(planned.family)
        if row is None:
            # Planned but never recorded: the run did not get to it. Silence
            # here would read as coverage.
            out.append(
                Gap(planned.family, "skipped", planned.feeds, "not reached by this run")
            )
        elif row.status != "ran":
            out.append(Gap(planned.family, row.status, planned.feeds, row.detail))
    return out


# ==========================================================================
# the reuse window
# ==========================================================================
#: Used until somebody saves a window of their own.
DEFAULT_FRESHNESS_DAYS = 30


async def freshness_days(session: AsyncSession) -> int:
    """How old a family's result may be and still be reused."""
    from app.models.config import ResearchConfig
    from app.services.versioning import get_active

    row = await get_active(session, ResearchConfig)
    return row.freshness_days if row is not None else DEFAULT_FRESHNESS_DAYS


async def fresh_families(
    session: AsyncSession, account_id: uuid.UUID, *, days: int
) -> dict[str, datetime]:
    """Families answered for this account inside the window, with when.

    `ran` and `empty` are answers — "found this" and "there is nothing there"
    — and both are worth reusing. `failed` and `skipped` are not: a family that
    failed last week has told us nothing, so it is looked at again.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await session.execute(
        select(ResearchCoverage.family, func.max(ResearchCoverage.created_at))
        .where(
            ResearchCoverage.account_id == account_id,
            ResearchCoverage.contact_id.is_(None),
            ResearchCoverage.status.in_(("ran", "empty")),
            ResearchCoverage.created_at >= since,
        )
        .group_by(ResearchCoverage.family)
    )
    return {family: when for family, when in rows.all()}


async def fresh_contact_families(
    session: AsyncSession, account_id: uuid.UUID, *, days: int
) -> dict[uuid.UUID, dict[str, datetime]]:
    """Per person: families answered inside the window, with when."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await session.execute(
        select(
            ResearchCoverage.contact_id,
            ResearchCoverage.family,
            func.max(ResearchCoverage.created_at),
        )
        .where(
            ResearchCoverage.account_id == account_id,
            ResearchCoverage.contact_id.is_not(None),
            ResearchCoverage.status.in_(("ran", "empty")),
            ResearchCoverage.created_at >= since,
        )
        .group_by(ResearchCoverage.contact_id, ResearchCoverage.family)
    )
    out: dict[uuid.UUID, dict[str, datetime]] = {}
    for contact_id, family, when in rows.all():
        out.setdefault(contact_id, {})[family] = when
    return out


async def has_unread_evidence(session: AsyncSession, account_id: uuid.UUID) -> bool:
    """Is there evidence nobody has turned into signals yet?

    The reuse window exists to stop paying twice for the same search. It must
    not also skip the *reading*, which costs no search at all — an account
    researched before extraction existed would otherwise sit on a pile of
    evidence for thirty days with an empty Signals tab and no way to catch up.

    True when evidence exists and either no signal has ever been written, or
    the newest passage arrived after the newest signal.
    """
    from app.models.signal import Signal

    newest_evidence = (
        await session.execute(
            select(func.max(Evidence.retrieved_at)).where(Evidence.account_id == account_id)
        )
    ).scalar()
    if newest_evidence is None:
        return False
    newest_signal = (
        await session.execute(
            select(func.max(Signal.created_at)).where(Signal.account_id == account_id)
        )
    ).scalar()
    return newest_signal is None or newest_signal < newest_evidence


# ==========================================================================
# what a list is worked for, and who at each account
# ==========================================================================
#: How many people per account the contact pass looks into.
CONTACTS_PER_ACCOUNT = 3


@dataclass
class ListPlan:
    """What research looks for on one list, from the ICPs it is worked for."""

    #: Families behind the ICPs' company signals — run once per account.
    company: ResearchPlan
    #: Families behind the ICPs' contact signals — run for the chosen people.
    contact: ResearchPlan
    #: The ICPs' buyer personas, as persona-matching targets.
    targets: tuple[str, ...] = ()
    #: Stamped on each run, so a later ICP edit cannot rewrite what it looked for.
    icp_version_ids: list[str] = field(default_factory=list)
    #: Every signal type the ICPs care about — what extraction may return.
    wanted_types: tuple[str, ...] = ()
    #: Every source this list will actually read, across both scopes — derived
    #: from the chosen signal types and then filtered by status, kind and
    #: scope. Kept whole so a rep can be told what the list is set up to read,
    #: and it is now the planned set rather than a wish list somebody ticked.
    source_keys: tuple[str, ...] = ()
    #: (name, definition) per ICP — what fit is computed against.
    icps: tuple[tuple[str, dict], ...] = ()

    @property
    def type_keys(self) -> tuple[str, ...]:
        """What extraction may return: every type the ICPs asked for.

        Deliberately *not* narrowed to the types each source was expected to
        feed. Reading a document costs the same whether one conclusion is drawn
        from it or twenty, so a leadership change mentioned in a job posting is
        a leadership change. Narrowing here is what made research cost one
        search per signal type, and it threw away most of what it paid for.

        Falls back to the plan's own feeds when the ICPs name no signals, which
        is the only case where "what was looked for" is all we know.
        """
        if self.wanted_types:
            return self.wanted_types
        return tuple(
            sorted(
                {
                    key
                    for planned in (*self.company.families, *self.contact.families)
                    for key in planned.feeds
                }
            )
        )


async def plan_for_list(
    session: AsyncSession, list_id: uuid.UUID, *, tier: str = "deep"
) -> ListPlan:
    """Plan research from the list's ICPs rather than the whole registry.

    Two things come from the ICP and they are not the same thing. Its
    **sources** are where to look — the plan of record, and the reason two
    accounts on one list are comparable, because the same places were read for
    both. Its **signals that matter** are what to conclude, split by the scope
    each type carries.

    An ICP naming no sources falls back to the union of what its signal types
    claim, which is how research behaved before sources were configurable. An
    ICP naming no signals falls back to every active type of that scope.
    """
    from app.models.account import account_list_icp
    from app.models.config import IcpProfile, IcpProfileVersion
    from app.services.verification import target_personas

    versions = list(
        (
            await session.execute(
                select(IcpProfileVersion)
                .join(
                    account_list_icp,
                    account_list_icp.c.icp_profile_id == IcpProfileVersion.icp_profile_id,
                )
                .where(
                    account_list_icp.c.list_id == list_id,
                    IcpProfileVersion.is_active.is_(True),
                )
                .order_by(IcpProfileVersion.id)
            )
        ).scalars()
    )
    definitions = [v.definition or {} for v in versions]
    names = (
        dict(
            (
                await session.execute(
                    select(IcpProfile.id, IcpProfile.name).where(
                        IcpProfile.id.in_({v.icp_profile_id for v in versions})
                    )
                )
            ).all()
        )
        if versions
        else {}
    )
    wanted = {
        key
        for d in definitions
        for key in (d.get("signals_that_matter") or [])
        if isinstance(key, str)
    }
    # Switched off for this ICP, not removed from the registry. The old
    # `sources` key was an independent *inclusion* list that overrode what the
    # types claimed; it is no longer read, because two lists with nothing
    # reconciling them failed in both directions inside a week (§77, §81).
    excluded = {
        key
        for d in definitions
        for key in (d.get("sources_excluded") or [])
        if isinstance(key, str)
    }
    keys = wanted or None
    company = await build_plan(
        session, scope="company", type_keys=keys, exclude=excluded, tier=tier
    )
    # Contacts are deep-only. The whole per-person programme has produced
    # five signals, so it is not something a light run should reach for; a
    # rep who wants it asks for the tier that says so.
    contact = await build_plan(
        session, scope="contact", type_keys=keys, exclude=excluded, tier=tier
    )
    return ListPlan(
        company=company,
        contact=contact,
        targets=target_personas(*definitions),
        icp_version_ids=[str(v.id) for v in versions],
        wanted_types=tuple(sorted(wanted)),
        # What will actually be read, derived — rather than what somebody once
        # ticked. Previously set from the ICP's own list and never read back.
        source_keys=tuple(
            sorted({f.family for f in (*company.families, *contact.families)})
        ),
        icps=tuple(
            (names.get(v.icp_profile_id, "ICP"), v.definition or {}) for v in versions
        ),
    )


async def contacts_to_research(
    session: AsyncSession,
    account_id: uuid.UUID,
    *,
    targets: tuple[str, ...],
    limit: int = CONTACTS_PER_ACCOUNT,
) -> list:
    """The people at one account worth researching for this list.

    Three conditions, in the order they are cheapest to check:

    * a **verified** email — the reason to research someone is to write to
      them, and only `verified` may be written to;
    * they match the ICP's **buyer personas** — nobody else would be pursued;
    * the best `limit` of those: a LinkedIn profile first (it is how the search
      tells this person from a namesake), then seniority, then name.

    An ICP naming no personas selects nobody, the same answer enrichment gives.
    """
    from app.models.account import Contact
    from app.services import personas
    from app.services.verification import matches_persona

    if not targets:
        return []
    rows = list(
        (
            await session.execute(
                select(Contact).where(
                    Contact.account_id == account_id,
                    Contact.do_not_contact.is_(False),
                    Contact.email_status == "verified",
                    Contact.email.is_not(None),
                )
            )
        ).scalars()
    )
    picked = [c for c in rows if matches_persona(c, targets)]
    picked.sort(
        key=lambda c: (
            c.linkedin_url is None,
            -personas.rank(personas.tokens(c.title)),
            c.full_name.casefold(),
        )
    )
    return picked[:limit]
