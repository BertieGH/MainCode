"""The research run: resolution → CRM → fan-out → coverage.

`docs/08` sets one ordering condition for this phase: **the CRM is checked
first**. It is first for a commercial reason, not a technical one. Researching a
company that is already a customer, or already owned by another rep, spends
money to produce an approach that should never be made — and the CRM is the
only system that knows. Every later stage is allowed to assume that check has
already happened.

So the order is enforced by structure rather than by comment: `run_research`
cannot reach the fan-out without going through `resolve`, and `resolve` returns
the object the fan-out needs.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Run
from app.services.crm import CrmAdapter, CrmUnavailableError
from app.services.research import (
    Gap,
    ResearchPlan,
    build_plan,
    gaps_for_run,
    record_coverage,
    search_brief,
)

log = logging.getLogger(__name__)


@dataclass
class Resolution:
    """The CRM's verdict, which every later stage may assume was taken."""

    account: Account
    crm_id: str | None = None
    known_to_crm: bool = False
    #: True when the CRM could not be reached. Research is *not* run in this
    #: state: proceeding would mean prospecting blind into a book we cannot
    #: see, which is the failure the CRM-first rule exists to prevent.
    crm_unavailable: bool = False
    owner: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def may_research(self) -> bool:
        return not self.crm_unavailable


@dataclass
class RunResult:
    run_id: uuid.UUID
    resolution: Resolution | None = None
    plan: ResearchPlan | None = None
    evidence_by_family: dict[str, int] = field(default_factory=dict)
    #: Families whose runner raised, with the reason. Kept apart from
    #: `evidence_by_family` because a failure is not a zero.
    failed_families: dict[str, str] = field(default_factory=dict)
    #: Families not run because an earlier run answered them inside the reuse
    #: window. Neither a gap nor a failure: the answer exists, it is just older.
    reused: tuple[str, ...] = ()
    #: The contact pass. Evidence stored per person; the people looked into;
    #: contact families that failed; person-families answered, and reused.
    contact_evidence: dict[uuid.UUID, int] = field(default_factory=dict)
    contacts_researched: tuple[uuid.UUID, ...] = ()
    contact_failed: dict[str, str] = field(default_factory=dict)
    contact_answered: int = 0
    contact_reused: int = 0
    #: Signal extraction, run once the evidence is in. `signals_dropped` are
    #: conclusions whose citations did not resolve — the guard, doing its job.
    signals_stored: int = 0
    signals_dropped: int = 0
    #: Facts we already held, re-read. Not new knowledge, and not a failure.
    signals_duplicate: int = 0
    signals_failed: str | None = None
    #: Qualification, the last step: six dimensions scored in Python.
    qualified: bool = False
    priority_score: float | None = None
    priority_band: str | None = None
    #: Why it was not qualified — no signals yet, usually.
    qualification_note: str | None = None
    unsupported_dimensions: tuple[str, ...] = ()
    qualification_failed: str | None = None
    gaps: list[Gap] = field(default_factory=list)
    halted: str | None = None

    @property
    def status(self) -> str:
        """`halted`, `failed`, `partial` or `complete`.

        The last three are what the account's `research_status` becomes. A run
        where every family raised looked at nothing, so it is `failed` however
        cleanly it finished — counting it as researched is how "1 researched ·
        0 evidence rows" reached a rep.
        """
        if self.halted is not None:
            return "halted"
        answered = (
            bool(self.evidence_by_family) or bool(self.reused)
            or self.contact_answered > 0 or self.contact_reused > 0
        )
        failed = (
            bool(self.failed_families) or bool(self.contact_failed)
            or self.signals_failed is not None or self.qualification_failed is not None
        )
        if failed and not answered:
            return "failed"
        if failed:
            return "partial"
        return "complete"

    @property
    def researched(self) -> bool:
        return self.status in ("complete", "partial")


@dataclass(frozen=True)
class FamilyOutcome:
    """What one family run produced.

    Injected runners may still return a bare count; the pipeline accepts both.
    """

    stored: int
    #: What it searched for and could not establish. Kept on the coverage row,
    #: so an `empty` family can say what was looked for.
    not_found: tuple[str, ...] = ()
    #: Remarks about the shape of what came back — how much was kept, how much
    #: fell outside the window. Not misses, and shown apart from them.
    notes: tuple[str, ...] = ()


def _stale_note(count: int) -> tuple[str, ...]:
    """Say so when a family's finds were refused for being too old.

    A note, not a miss. The family looked and found something; it was dated
    past the point any live signal type could use it. Silence here would make a
    search that returned ten dead pages look identical to one that returned
    nothing at all, and the two call for opposite fixes — the first wants a
    narrower source, the second a different one.
    """
    if count < 1:
        return ()
    return (
        f"{count} passage{'' if count == 1 else 's'} refused as older than any "
        f"signal type's durability",
    )


async def resolve(
    session: AsyncSession, *, account: Account, crm: CrmAdapter
) -> Resolution:
    """Step one, always. Ask the CRM what it already knows."""
    try:
        found = await crm.find_account(domain=account.domain, name=account.name)
    except CrmUnavailableError as exc:
        log.warning("pipeline.crm_unavailable account=%s err=%s", account.id, exc)
        return Resolution(account=account, crm_unavailable=True)

    if found is None:
        return Resolution(account=account, known_to_crm=False)

    return Resolution(
        account=account,
        crm_id=found.crm_id,
        known_to_crm=True,
        owner=found.owner,
        # CRM notes are rep-written free text. They travel as data — never
        # spliced into instructions — because a note is exactly where a
        # deliberate or accidental prompt injection would sit.
        notes=found.notes,
    )


#: A family runner: given an account and a family, return what it produced — a
#: `FamilyOutcome`, or a bare count of evidence rows. Injected so the pipeline
#: is testable without the network.
FamilyRunner = "Callable[[Account, str], Awaitable[FamilyOutcome | int]]"


async def run_research(
    session: AsyncSession,
    *,
    account: Account,
    crm: CrmAdapter,
    run_family,
    run_id: uuid.UUID | None = None,
    triggered_by: str = "system",
    skip_families: frozenset[str] = frozenset(),
    quarantined: dict[str, str] | None = None,
    company_plan: ResearchPlan | None = None,
    contacts: list | tuple = (),
    contact_plan: ResearchPlan | None = None,
    run_contact_family=None,
    contact_skip: dict[uuid.UUID, set[str]] | None = None,
    icp_version_ids: list[str] | None = None,
    run_extraction=None,
    signal_type_keys: tuple[str, ...] | frozenset[str] | set[str] = (),
    run_qualification=None,
) -> RunResult:
    """Resolve against the CRM, then run every planned family and record it.

    Coverage is written for *every* planned family, including the ones that
    find nothing. Recording only the successes is what turns a gap into
    apparent completeness.

    Two passes in one run, when a list asks for both: the company families
    (`company_plan`, the whole registry if none is given), then the contact
    families for `contacts` — one call per family for all of them, recorded per
    person. `contact_skip` names, per person, families answered inside the
    reuse window.

    `quarantined` names sources that have failed here often enough to stop
    trying, with the reason. They are recorded as skipped rather than dropped:
    a source that quietly stops being read is a hole in coverage that reads as
    a quiet prospect.
    """
    # Stamped at creation, not at the end. Evidence, signals, context,
    # qualification and strategy all carry this run's id, so this one column is
    # what keeps fixture data distinguishable from real data forever. A run
    # that failed halfway still needs it.
    from app.services import demo

    run = Run(
        id=run_id or uuid.uuid4(),
        account_id=account.id,
        stage="resolution",
        status="running",
        triggered_by=triggered_by,
        mode=await demo.current_mode(session),
        started_at=datetime.now(UTC),
        icp_version_ids=list(icp_version_ids) if icp_version_ids else None,
    )
    session.add(run)
    await session.flush()

    result = RunResult(run_id=run.id)

    # --- 0. Identity first. Nothing below is worth spending without it. ---
    #
    # Researching the wrong company *succeeds*: the evidence parses, the
    # signals cite it, the score computes and the draft reads well — about a
    # different business. No later stage can detect that, which is why the
    # refusal has to be here rather than left to whoever calls this.
    #
    # A live run proved it is not theoretical. Three invented companies came
    # back at 1.00 confidence because the fallback model was shown their
    # domains and agreed with them; they would have been researched in full.
    if account.resolution_status != "resolved":
        run.stage, run.status = "resolution", "failed"
        run.error = (
            f"identity is {account.resolution_status!r}, not confirmed — "
            "research would be spent on a company nobody has verified"
        )
        run.finished_at = datetime.now(UTC)
        result.halted = run.error
        log.info(
            "pipeline.unresolved account=%s status=%s",
            account.id, account.resolution_status,
        )
        await session.flush()
        return result

    # --- 1. CRM first. Nothing below runs without this. ---
    result.resolution = await resolve(session, account=account, crm=crm)
    if not result.resolution.may_research:
        run.stage, run.status = "resolution", "failed"
        run.error = "CRM unreachable — research not attempted"
        run.finished_at = datetime.now(UTC)
        result.halted = run.error
        account.research_status = "failed"
        await session.flush()
        return result

    # --- 2. Plan, from the registry ---
    run.stage = "research"
    plan = company_plan if company_plan is not None else await build_plan(session)
    # Families answered inside the reuse window are left out of this run's
    # plan entirely — not run, not recorded, and not reported as a gap, since
    # the answer exists in an earlier run.
    result.reused = tuple(f.family for f in plan.families if f.family in skip_families)
    if result.reused:
        plan = ResearchPlan(
            families=[f for f in plan.families if f.family not in skip_families],
            orphan_types=plan.orphan_types,
        )
    result.plan = plan
    await session.flush()

    # --- 3. Each family, recorded whatever it returns ---
    held = quarantined or {}
    for planned in plan.families:
        reason = held.get(planned.family)
        if reason is not None:
            # Not run, but written down. The rep sees "we stopped trying this
            # here, and why" instead of a family that silently disappeared.
            await record_coverage(
                session,
                run_id=run.id,
                account_id=account.id,
                family=planned.family,
                evidence_count=0,
                skipped=reason,
            )
            continue
        try:
            outcome = await run_family(account, planned.family)
        except Exception as exc:  # noqa: BLE001 — injected runner; any fault must cost one family, not the run
            log.warning(
                "pipeline.family_failed account=%s family=%s err=%s",
                account.id, planned.family, exc,
            )
            reason = f"{type(exc).__name__}: {exc}"
            result.failed_families[planned.family] = reason
            await record_coverage(
                session,
                run_id=run.id,
                account_id=account.id,
                family=planned.family,
                evidence_count=0,
                failed=reason,
            )
            continue

        if isinstance(outcome, FamilyOutcome):
            count, not_found, notes = outcome.stored, outcome.not_found, outcome.notes
        else:
            count, not_found, notes = int(outcome), (), ()
        result.evidence_by_family[planned.family] = count
        await record_coverage(
            session,
            run_id=run.id,
            account_id=account.id,
            family=planned.family,
            evidence_count=count,
            not_found=not_found,
            notes=notes,
        )

    result.gaps = await gaps_for_run(session, run.id, plan)

    # --- 4. The people: the families their signals need, per person ---
    if contacts and contact_plan is not None and run_contact_family is not None:
        await _contact_pass(
            session,
            run_id=run.id,
            account=account,
            contacts=list(contacts),
            plan=contact_plan,
            runner=run_contact_family,
            skip=contact_skip or {},
            result=result,
        )

    # --- 5. What the evidence means, typed against the registry ---
    if run_extraction is not None and signal_type_keys:
        await _extract_signals(
            session,
            account=account,
            type_keys=sorted(signal_type_keys),
            contacts=list(contacts),
            extractor=run_extraction,
            result=result,
        )

    # --- 6. What it all comes to: six dimensions, scored in Python ---
    if run_qualification is not None:
        try:
            outcome = await run_qualification(account)
        except Exception as exc:  # noqa: BLE001 — costs the score, not the research
            result.qualification_failed = f"{type(exc).__name__}: {exc}"
            log.warning("pipeline.qualification_failed account=%s err=%s", account.id, exc)
        else:
            result.qualified = outcome.qualified
            result.priority_score = outcome.priority_score
            result.priority_band = outcome.priority_band
            result.qualification_note = outcome.reason
            result.unsupported_dimensions = outcome.unsupported

    # The account says where its research stands. Without this the list read
    # `not_started` beside a report saying the account had just been researched.
    account.research_status = result.status
    if result.status == "failed":
        run.status = "failed"
        run.error = next(iter(result.failed_families.values()))
    else:
        run.stage = "signals"
        run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    await session.flush()
    return result


#: How much of an account's evidence extraction is shown. Newest first: a
#: signal is about what is true now, and the whole book of a long-worked
#: account would cost more per run than it adds.
EVIDENCE_FOR_EXTRACTION = 80


async def _extract_signals(
    session: AsyncSession,
    *,
    account: Account,
    type_keys: list[str],
    contacts: list,
    extractor,
    result: RunResult,
) -> None:
    """Turn the evidence now held into typed signals.

    Runs on everything held for the account, not only what this run found: a
    signal is a reading of the evidence as a whole, and a funding round found
    last week is part of what this week's hiring means.

    A failure here costs the signals, never the research. The evidence is
    stored and the next run can interpret it again.
    """
    from app.models.signal import Evidence

    rows = list(
        (
            await session.execute(
                select(Evidence)
                .where(Evidence.account_id == account.id)
                .order_by(Evidence.retrieved_at.desc())
                .limit(EVIDENCE_FOR_EXTRACTION)
            )
        ).scalars()
    )
    if not rows:
        return
    try:
        outcome = await extractor(account, rows, type_keys, contacts)
    except Exception as exc:  # noqa: BLE001 — injected; costs the signals, not the run
        result.signals_failed = f"{type(exc).__name__}: {exc}"
        log.warning("pipeline.extraction_failed account=%s err=%s", account.id, exc)
        return
    result.signals_stored = outcome.stored
    result.signals_dropped = len(outcome.dropped)
    result.signals_duplicate = getattr(outcome, "duplicates", 0)


async def extract_only(
    session: AsyncSession,
    *,
    account: Account,
    run_id: uuid.UUID,
    type_keys,
    extractor,
    contacts: list | tuple = (),
) -> RunResult:
    """Re-read evidence already held. No search, no provider call.

    The reuse window stops research paying twice for the same search, and that
    is right — but it also means a signal type added today, or a TTL widened
    today, can never reach evidence found yesterday. This is that path: the
    interpretation on its own, for a few thousand tokens.
    """
    result = RunResult(run_id=run_id)
    if type_keys:
        await _extract_signals(
            session,
            account=account,
            type_keys=sorted(type_keys),
            contacts=list(contacts),
            extractor=extractor,
            result=result,
        )
    return result


def llm_signal_extractor(session: AsyncSession, *, run_id: uuid.UUID | None = None):
    """The real extractor: interpret held evidence, store what cites real rows.

    Injected like the family runners, so the pipeline's ordering is testable
    without a model call. `extraction.store_batch` owns the invariant — a
    signal citing evidence that does not exist is dropped and recorded.
    """

    async def run(account: Account, evidence: list, type_keys: list[str], contacts: list):
        from app.services import extraction, stages

        result = await stages.extract_signals(
            session,
            account=account,
            evidence=evidence,
            type_keys=type_keys,
            contacts=contacts,
        )
        outcome = await extraction.store_batch(
            session, account_id=account.id, batch=result.parsed, run_id=run_id
        )
        log.info(
            "pipeline.signals account=%s evidence=%d stored=%d dropped=%d",
            account.id, len(evidence), outcome.stored, len(outcome.dropped),
        )
        return outcome

    return run


@dataclass(frozen=True)
class ContactFamilyOutcome:
    """What one contact family found, per person."""

    stored_by_contact: dict[uuid.UUID, int] = field(default_factory=dict)
    #: What was searched for each person, including where nothing turned up.
    searched_by_contact: dict[uuid.UUID, tuple[str, ...]] = field(default_factory=dict)
    #: Notes for the whole call — passages dropped, links discarded.
    notes: tuple[str, ...] = ()


async def _contact_pass(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    account: Account,
    contacts: list,
    plan: ResearchPlan,
    runner,
    skip: dict[uuid.UUID, set[str]],
    result: RunResult,
) -> None:
    """One call per family for everyone who still needs it; coverage per person.

    Per person so the reuse window works per person: a colleague added to the
    ICP last week is researched without paying again for the two looked into
    yesterday. One failure costs that family for those people, not the pass.
    """
    looked_into: set[uuid.UUID] = set()
    for planned in plan.families:
        people = [c for c in contacts if planned.family not in skip.get(c.id, set())]
        result.contact_reused += len(contacts) - len(people)
        if not people:
            continue
        looked_into.update(c.id for c in people)
        try:
            outcome = await runner(account, planned.family, people)
        except Exception as exc:  # noqa: BLE001 — injected runner; one family, not the pass
            reason = f"{type(exc).__name__}: {exc}"
            log.warning(
                "pipeline.contact_family_failed account=%s family=%s err=%s",
                account.id, planned.family, exc,
            )
            result.contact_failed[planned.family] = reason
            for c in people:
                await record_coverage(
                    session, run_id=run_id, account_id=account.id, family=planned.family,
                    evidence_count=0, failed=reason, contact_id=c.id,
                )
            continue

        for c in people:
            n = outcome.stored_by_contact.get(c.id, 0)
            result.contact_evidence[c.id] = result.contact_evidence.get(c.id, 0) + n
            result.contact_answered += 1
            await record_coverage(
                session, run_id=run_id, account_id=account.id, family=planned.family,
                evidence_count=n, contact_id=c.id,
                not_found=[*outcome.searched_by_contact.get(c.id, ()), *outcome.notes],
            )
    result.contacts_researched = tuple(c.id for c in contacts if c.id in looked_into)


def keep_own_linkedin(batch, *, company_url: str | None = None, person_url: str | None = None):
    """Drop LinkedIn passages that belong to a different company page or person.

    Only a definite mismatch is dropped — a LinkedIn page that names no owner,
    or an account with no page on record, is kept. The count is said in the
    batch's notes, so a rep can see that something was found and set aside.
    """
    from app.services import linkedin

    kept = [
        e
        for e in batch.evidence
        if linkedin.belongs(e.source_url, company_url=company_url, person_url=person_url)
        is not False
    ]
    dropped = len(batch.evidence) - len(kept)
    if not dropped:
        return batch, 0
    note = (
        f"{dropped} LinkedIn passage(s) from a different company page or person were discarded"
    )
    return batch.model_copy(update={"evidence": kept, "not_found": [*batch.not_found, note]}), dropped


def llm_contact_runner(session: AsyncSession, *, run_id: uuid.UUID | None = None):
    """The real contact runner: one search per family for the chosen people,
    stored per person.

    A passage whose `contact_id` is not one we sent is dropped and counted. It
    cannot be filed under a person, and filing it under the nearest match is
    how a namesake's job change becomes a prospect's.
    """

    async def run(account: Account, family: str, people: list) -> ContactFamilyOutcome:
        from app.schemas.evidence import EvidenceBatch, FoundEvidence
        from app.services import evidence as evidence_service
        from app.services import stages

        result = await stages.research_contacts(
            session, account=account, family=family, people=people
        )
        batch = result.parsed
        known = {str(p.id): p.id for p in people}

        grouped: dict[uuid.UUID, list] = {}
        dropped = 0
        for found in batch.evidence:
            contact_id = known.get(found.contact_id.strip())
            if contact_id is None:
                dropped += 1
                continue
            grouped.setdefault(contact_id, []).append(
                FoundEvidence(**found.model_dump(exclude={"contact_id"}))
            )

        from app.services import linkedin

        profiles = {p.id: p.linkedin_url for p in people}
        foreign = 0
        stored: dict[uuid.UUID, int] = {}
        for contact_id, items in grouped.items():
            # A LinkedIn passage must be this person's profile or post, or the
            # company's own page. A namesake's is dropped, not filed here.
            own = [
                item
                for item in items
                if linkedin.belongs(
                    item.source_url,
                    company_url=getattr(account, "linkedin_url", None),
                    person_url=profiles.get(contact_id),
                )
                is not False
            ]
            foreign += len(items) - len(own)
            if not own:
                stored[contact_id] = 0
                continue
            outcome = await evidence_service.store_found(
                session,
                account_id=account.id,
                batch=EvidenceBatch(evidence=own),
                run_id=run_id,
                family=family,
                contact_id=contact_id,
            )
            stored[contact_id] = outcome.count

        searched: dict[uuid.UUID, list[str]] = {}
        for entry in batch.searched_for:
            contact_id = known.get(entry.contact_id.strip())
            if contact_id is not None:
                searched.setdefault(contact_id, []).extend(entry.searched)

        notes = list(batch.not_found)
        if dropped:
            notes.append(
                f"{dropped} passage(s) named someone not asked about and were discarded"
            )
        if foreign:
            notes.append(
                f"{foreign} LinkedIn passage(s) from a different profile or company page "
                "were discarded"
            )
        log.info(
            "pipeline.contact_family_done account=%s family=%s people=%d stored=%s dropped=%d",
            account.id, family, len(people), sum(stored.values()), dropped,
        )
        return ContactFamilyOutcome(
            stored_by_contact=stored,
            searched_by_contact={k: tuple(v) for k, v in searched.items()},
            notes=tuple(notes),
        )

    return run


def llm_family_runner(session: AsyncSession, *, run_id: uuid.UUID | None = None):
    """The real runner: search a family, then store what it found.

    `run_research` takes this as an argument rather than importing it, and that
    injection is the whole reason the pipeline is testable at all — the
    CRM-first ordering, the per-family failure isolation and the coverage
    recording are all asserted against a fake runner, with no network and no
    spend.

    Returns the count of evidence rows *newly* stored, with what the family
    searched for and could not establish. Duplicates are excluded
    deliberately: a family that returns only passages we already hold has
    covered no new ground, and recording it as `ran` with a healthy count would
    hide a provider that has started returning the same cached page every time.

    Each stored row carries this family, so the coverage tab can open a family
    and show exactly what it found.
    """

    async def run(account: Account, family: str) -> FamilyOutcome:
        # Imported here rather than at module scope: `stages` imports the
        # Anthropic SDK, and the pipeline's own tests must keep importing
        # without it.
        from app.services import evidence as evidence_service
        from app.services import sources as source_service
        from app.services import stages

        # The registry, not the code constant: a source's kind is what decides
        # whether this costs a model call or two HTTP requests, and the registry
        # is where a person can see and change it.
        known = (await source_service.by_key(session)).get(family)
        if known is not None and known.kind == "fetch":
            # Read rather than searched: no model call, and the passage is the
            # company's own words with its own date. Each fetch source has its
            # own reader — the feed is `site_sweep`, open roles are `job_boards`.
            from app.services import job_boards, site_sweep

            readers = {
                "company_site": site_sweep.sweep_account,
                "job_board": job_boards.sweep_account,
            }
            reader = readers.get(family)
            if reader is None:
                # Failed by name rather than handed to the wrong reader: a feed
                # reader pointed at a job board reads a blog and calls it hiring.
                raise RuntimeError(f"no reader for fetch source {family!r}")
            swept = await reader(account)
            notes = list(swept.notes)
            found_page = getattr(swept, "linkedin_company", None)
            if found_page and not getattr(account, "linkedin_url", None):
                # The company's own homepage names its LinkedIn page, so this is
                # the page LinkedIn searches identify it by from now on. Only
                # when nothing is on record: a page a rep or an import set wins.
                account.linkedin_url = found_page
                notes.append(f"LinkedIn company page taken from its own homepage: {found_page}")
            stored = await evidence_service.store_found(
                session,
                account_id=account.id,
                batch=swept.batch,
                run_id=run_id,
                family=family,
            )
            log.info(
                "pipeline.fetched account=%s family=%s stored=%d duplicate=%d stale=%d",
                account.id, family, stored.count, stored.duplicates, stored.stale,
            )
            return FamilyOutcome(
                stored=stored.count,
                not_found=tuple(swept.misses),
                notes=tuple(notes) + _stale_note(stored.stale),
            )

        brief = await search_brief(session, family)
        if brief is not None:
            result = await stages.research_topic(session, account=account, brief=brief)
        else:
            result = await stages.research_family(session, account=account, family=family)
        batch, _ = keep_own_linkedin(
            result.parsed, company_url=getattr(account, "linkedin_url", None)
        )
        outcome = await evidence_service.store_found(
            session,
            account_id=account.id,
            batch=batch,
            run_id=run_id,
            family=family,
        )
        log.info(
            "pipeline.family_done account=%s family=%s stored=%d duplicate=%d stale=%d "
            "cache_read=%d",
            account.id, family, outcome.count, outcome.duplicates, outcome.stale,
            result.cache_read_tokens,
        )
        return FamilyOutcome(
            stored=outcome.count,
            not_found=tuple(batch.not_found),
            notes=_stale_note(outcome.stale),
        )

    return run
