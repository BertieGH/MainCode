"""Running imported contacts through the enrichment waterfall.

A contact that arrives in a CSV is a claim, not a route. The spreadsheet says
`dana@northwind.example`; nobody has established that the address exists, that
it is still hers, or that sending to it will not bounce a domain's reputation.
So an import is only the first half of getting a list ready — this is the
second, and it sits between them deliberately.

Three rules the rest of the system depends on:

**Only unverified contacts are asked about.** Every provider call is metered.
Re-checking a contact ContactOut already verified spends money to learn what is
already on the row, and on a re-imported list that is most of the file.

**The waterfall order is configuration, not code.** It comes from
`enrichment_config`, and the first provider to satisfy every required field
ends the run for that contact — a waterfall, not a race. Asking everyone and
keeping the best answer multiplies the bill on every contact the first provider
already resolved.

**A provider that says nothing is not a provider that failed.** "We asked and
they have no address for her" and "the API was down" lead to different
decisions, and collapsing them into one is how a reachable contact gets written
off — or an unreachable one keeps getting retried.

**A returned address is not automatically a verified one.** Apollo hands back
*guessed* addresses next to confirmed ones and grades them itself. Writing a
guess in as `verified` would satisfy the gate that exists to stop exactly that
send, and the first thing to notice would be a bounce against a sending
domain — so the provider's own verdict is what gets stored.

**A pass is always for a service.** Without one this ran alphabetically over
every unverified contact on the list, which spends a metered provider finding a
junior developer's address when the service needed the CTO — and the list then
*looks* enriched. The service names the ICP, the ICP names who is worth
reaching, and the run records which was used so "why these contacts?" stays
answerable. See `docs/10`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import AccountListMember, Contact
from app.models.config import (
    service_icp_link,
    EnrichmentConfig,
    IntegrationCredential,
    ServiceCatalog,
    IcpProfile,
    IcpProfileVersion,
)
from app.services import personas
from app.services import provider_catalogue as catalogue
from app.services.providers import ContactProvider, enrich
from app.services.versioning import get_active

log = logging.getLogger(__name__)

#: What makes a contact *sendable*, and therefore what `verified` means.
#:
#: Email only, and this is not the same list as what the waterfall chases. Every
#: channel this system sends on needs an address; a missing phone number is a
#: gap in a record, not a reason to call the contact unreachable. Conflating the
#: two would mark a perfectly contactable person `not_found` because nobody
#: published their mobile.
GATING_FIELDS: tuple[str, ...] = ("email",)

#: The fallback for what the waterfall chases when no config row says.
#: `enrichment_config.required_fields` is the real answer — see `wanted_fields`.
DEFAULT_WANTED_FIELDS: tuple[str, ...] = ("email",)


async def wanted_fields(session: AsyncSession) -> tuple[str, ...]:
    """What the waterfall keeps asking for, from configuration.

    Adding `phone` here means a contact whose email the first provider already
    resolved still costs a call to the next one that can supply a number. That
    is a real increase in the bill and a deliberate choice, which is why it
    lives in a versioned config row rather than in this file.
    """
    row = await get_active(session, EnrichmentConfig)
    fields = tuple(row.required_fields) if row and row.required_fields else ()
    return fields or DEFAULT_WANTED_FIELDS


class NoServiceIcpError(RuntimeError):
    """The service has no active ICP, so there is nothing to target on.

    Distinct from a missing credential. Both stop the pass, but one is fixed by
    connecting a provider and the other by writing down who the service is for.
    """


def target_personas(*icps: dict | None) -> tuple[str, ...]:
    """Who this run is trying to reach — from the ICPs, and only the ICPs.

    Takes **several** ICP definitions because a list may target more than one
    profile at once — a service can sell to two kinds of buyer, and enriching
    for both in one pass is cheaper than two passes over the same list. The
    union is correct here: a contact worth reaching for either profile is worth
    reaching.

    The service row used to contribute its own `target_personas`. It no longer
    does: a service now says only who signs off, broadly (`economic_buyer`),
    and the people to reach are the ICP's buyer personas. Two sources for one
    idea meant an ICP could never narrow what a service had already widened.

    A persona is normally the `{"buying_role": ..., "titles": [...]}` form the
    ICP editor writes, and both halves become targets: the titles are what a
    CSV can be matched on, and the buying role is what a contact already
    classified can be matched on. A bare string, which older definitions
    carry, is read as a target on its own.
    """
    listed: list[str] = []
    for icp in icps:
        if not icp:
            continue
        for key in ("target_personas", "personas", "buying_roles"):
            value = icp.get(key)
            if not isinstance(value, list):
                continue
            for entry in value:
                if isinstance(entry, str):
                    listed.append(entry)
                elif isinstance(entry, dict):
                    role = entry.get("buying_role")
                    if isinstance(role, str):
                        listed.append(role)
                    titles = entry.get("titles")
                    if isinstance(titles, list):
                        listed.extend(t for t in titles if isinstance(t, str))
    seen: dict[str, None] = {}
    for item in listed:
        cleaned = " ".join(str(item).split()).casefold()
        if cleaned:
            seen.setdefault(cleaned, None)
    return tuple(seen)


def matches_persona(contact: Contact, targets: tuple[str, ...]) -> bool | None:
    """Does this contact look like somebody the service wants?

    Returns `None` — *cannot tell* — when the contact carries nothing to judge
    on. That third answer is the point: a contact with no title is not a bad
    match, they are an unknown one, and the two deserve different treatment.
    Collapsing them would either drop real buyers whose title was never
    imported, or spend the whole budget on people nobody can use.
    """
    if not targets:
        return None

    # A buying role is matched against the contact's buying role, exactly, and
    # never against a title. "technical_buyer" read as words is a tech function
    # with no rank — and every developer on a list would answer it.
    roles = {t for t in targets if t in personas.BUYING_ROLES}
    titles = tuple(t for t in targets if t not in personas.BUYING_ROLES)
    if contact.buying_role and contact.buying_role in roles:
        return True

    known = [
        v
        for v in (
            contact.title,
            contact.persona_role,
            contact.buying_role,
            contact.seniority if contact.seniority != "unknown" else None,
        )
        if v and str(v).strip()
    ]
    if not known:
        return None
    if not titles:
        # Only buying roles were named, and this contact does not carry one of
        # them. Their title cannot answer a role.
        return False

    # Compared by meaning, not spelling — phrases, functions and rank. See
    # `personas` for the two versions this replaced and what each got wrong.
    #
    # Seniority matches only a target that names that seniority exactly
    # ("c_level"). Read fuzzily against job titles, "vp" matched any of them by
    # rank alone, so every VP — of Sales as much as of Engineering — read as in
    # persona. It never fired while seniority was always `unknown`; classifying
    # titles on write (`docs/18`) exposed it. Rank says nothing about function,
    # the same reason a buying role is never read as a title above.
    rank = contact.seniority if contact.seniority != "unknown" else None
    if rank and rank in titles:
        return True
    return any(personas.matches_any(v, titles) for v in known if v != rank)


@dataclass
class ContactOutcome:
    contact_id: uuid.UUID
    full_name: str
    #: `verified`, `risky`, `not_found`, `unavailable`, or `skipped`.
    outcome: str
    detail: str = ""
    providers_called: list[str] = field(default_factory=list)
    #: A LinkedIn profile the provider supplied and the contact did not have.
    linkedin_filled: bool = False
    #: The account's LinkedIn company page, when this contact's provider record
    #: supplied it and the account had none.
    company_linkedin: str | None = None


@dataclass
class VerificationReport:
    """What the pass did, and what it could not do."""

    checked: int = 0
    verified: int = 0
    #: Verified contacts that also came away with a phone number, and with a
    #: LinkedIn URL. Reported rather than gated on: both are contact data worth
    #: collecting, and neither is a condition of being reachable — requiring
    #: one would strand people who are perfectly contactable by email.
    #: Aged verified addresses re-confirmed from saved Apollo contacts, free.
    reconfirmed_free: int = 0
    #: Contacts Apollo enriched on this pass, saved to the Apollo account.
    saved_to_apollo: int = 0
    #: Apollo's refusal to save them, if any.
    apollo_note: str | None = None
    with_phone: int = 0
    with_linkedin: int = 0
    #: Found, and graded below sendable by the provider that found it — an
    #: Apollo guess, typically. Counted apart from `not_found` because the two
    #: need different work: a guess needs confirming, a miss needs a better
    #: identifier. Folding them together would hide a list that is one
    #: verification pass away from being usable.
    risky: int = 0
    not_found: int = 0
    unavailable: int = 0
    skipped: int = 0
    outcomes: list[ContactOutcome] = field(default_factory=list)
    #: The order actually used, so a surprising result can be traced to it.
    waterfall: list[str] = field(default_factory=list)
    #: The fields the waterfall chased, from `enrichment_config`. Reported
    #: because it is what decides how many providers each contact costs.
    wanted: list[str] = field(default_factory=list)
    #: The service this pass was run for, and the ICP version that targeted it.
    #: Recorded so "why were these contacts enriched?" stays answerable after
    #: the ICP has moved on.
    service_code: str | None = None
    #: Which ICP versions this run read, as (profile name, version). Plural
    #: because a run may target several profiles, and recorded rather than
    #: derived so a later edit cannot change what this run says it did.
    icp_versions: list[tuple[str, int]] = field(default_factory=list)
    #: Contacts left alone because they do not look like anyone this service
    #: wants. Reported rather than hidden: a list that is mostly out of persona
    #: is a list problem, not an enrichment problem.
    out_of_persona: int = 0
    #: Contacts carrying nothing to judge on — no title, no role. Neither
    #: matched nor rejected, because guessing either way is wrong.
    unknown_persona: int = 0
    #: Where missing LinkedIn links came from on this pass. Apollo first; the
    #: company's own website when Apollo had nothing. Counted apart, because a
    #: link a company publishes and a link a vendor holds are different claims.
    contact_linkedin_from_provider: int = 0
    contact_linkedin_from_site: int = 0
    company_linkedin_from_provider: int = 0
    company_linkedin_from_site: int = 0
    #: What the website pass could not settle — a site that did not answer, a
    #: homepage linking two company pages.
    linkedin_notes: list[str] = field(default_factory=list)
    #: Set when no provider could be called at all. The pass did nothing, and
    #: says so rather than reporting zero failures.
    blocked: str | None = None

    @property
    def ran(self) -> bool:
        return self.blocked is None


class NoEnrichmentProviderError(RuntimeError):
    """No configured provider can be called.

    Distinct from "nobody was found". A pass that could not run must not look
    like a pass that ran and found nothing — the first needs a credential, the
    second needs a different list.
    """


async def waterfall_order(session: AsyncSession) -> list[str]:
    """The configured order, best first."""
    row = await get_active(session, EnrichmentConfig)
    return list(row.provider_order) if row else []


#: Providers this build has a client for.
#:
#: Both, now. They are not equally trusted: Apollo's response shape was read
#: off a live call, ContactOut's was inferred from its routes and is still
#: unconfirmed — see `enrichment_clients`. A name here means a client exists,
#: not that it has been proven against the vendor.
BUILT_IN_PROVIDERS: tuple[str, ...] = ("apollo", "contactout")


async def build_clients(
    session: AsyncSession, providers: list[str]
) -> dict[str, ContactProvider]:
    """Construct a client per provider, from its stored credential.

    The key is decrypted here and handed straight to the client. It is never
    logged, never returned by an endpoint, and never held longer than the pass
    — `docs/01` invariant 9.
    """
    from app.models.config import IntegrationCredential
    from app.services import crypto, enrichment_clients

    built: dict[str, ContactProvider] = {}
    for provider in providers:
        if provider not in BUILT_IN_PROVIDERS:
            continue
        row = (
            await session.execute(
                select(IntegrationCredential).where(
                    IntegrationCredential.provider == provider,
                    IntegrationCredential.credential_type == "api_key",
                )
            )
        ).scalar_one_or_none()
        if row is None:
            continue
        try:
            key = crypto.decrypt(row.value_encrypted).reveal()
        except crypto.CredentialError:
            log.warning("verification.undecryptable provider=%s", provider)
            continue
        client = enrichment_clients.build(provider, key)
        if client is not None:
            built[provider] = client
    return built


async def credentialled_providers(session: AsyncSession) -> tuple[list[str], list[str]]:
    """The configured waterfall, minus anything without a verified key.

    Returns `(providers, reasons)` in waterfall order. Only the *credential* is
    judged here; whether a client exists is decided by the caller, because an
    injected client is a client — the same rule `llm.call_structured` follows.
    Folding both checks in here made a supplied client unusable, which is how
    this function was wrong the first time.
    """
    order = await waterfall_order(session)
    credentials = {
        row.provider: row.status
        for row in (
            await session.execute(
                select(IntegrationCredential).where(
                    IntegrationCredential.credential_type == "api_key"
                )
            )
        ).scalars()
    }

    usable: list[str] = []
    reasons: list[str] = []
    for provider in order:
        label = _label(provider)
        if credentials.get(provider) != "valid":
            reasons.append(f"{label}: no verified credential")
            continue
        usable.append(provider)
    return usable, reasons


def _label(provider: str) -> str:
    known = catalogue.BY_KEY.get(provider)
    return known.label if known else provider


#: How long a verified address is trusted before it is checked again. People
#: move on, and an account revived after a year would otherwise carry
#: "verified" from a check nobody remembers.
EMAIL_RECHECK_DAYS = 90


def needs_recheck(contact, now: datetime | None = None) -> bool:
    """Whether a verified address was verified long enough ago to check again."""
    verified_at = getattr(contact, "email_verified_at", None)
    if contact.email_status != "verified" or verified_at is None:
        return False
    return (now or datetime.now(UTC)) - verified_at > timedelta(days=EMAIL_RECHECK_DAYS)


async def unverified_contacts(
    session: AsyncSession,
    *,
    list_id: uuid.UUID,
    account_ids: list[uuid.UUID] | None = None,
    contact_ids: list[uuid.UUID] | None = None,
) -> list[Contact]:
    """Contacts on this list that still have no verified route.

    Scoped to the list rather than to the whole book: verification is a step in
    getting *this* import ready, and sweeping every account would bill for
    contacts nobody is about to write to.

    Not filtered by persona here — that decision needs the service, and doing
    it in SQL would hide *why* somebody was skipped. `verify_list` sorts them
    into buckets and reports the counts.
    """
    rows = await session.execute(
        select(Contact)
        .join(AccountListMember, AccountListMember.account_id == Contact.account_id)
        .where(
            AccountListMember.list_id == list_id,
            # Unverified, or verified long enough ago to be due a re-check.
            or_(
                func.coalesce(Contact.email_status, "unverified") != "verified",
                Contact.email_verified_at
                < datetime.now(UTC) - timedelta(days=EMAIL_RECHECK_DAYS),
            ),
            # Only the selected accounts' people, when a selection is given.
            *([Contact.account_id.in_(account_ids)] if account_ids else []),
            # Or exactly the people picked on the Contacts tab.
            *([Contact.id.in_(contact_ids)] if contact_ids else []),
            # Nobody spends a provider call on a person nobody may write to.
            Contact.do_not_contact.is_(False),
        )
        .order_by(Contact.full_name)
    )
    return list(rows.scalars())


async def resolve_targeting(
    session: AsyncSession,
    *,
    service_id: uuid.UUID,
    icp_profile_ids: list[uuid.UUID] | None = None,
) -> tuple[ServiceCatalog, list[IcpProfileVersion]]:
    """The service and the ICP versions this run will target.

    Both are required before a metered call is made. Without the service there
    is nothing to target on; without an ICP the service has not been described
    well enough to say who is worth reaching, and enriching anyway is how a
    list of the wrong people ends up looking finished.

    `icp_profile_ids` narrows to a subset — a service may sell to several kinds
    of buyer and a run need not chase all of them. Omitted, every ICP linked to
    the service is used. An id that is not linked is refused rather than
    ignored: silently dropping it would enrich for a profile nobody chose.

    Returns **versions**, not profiles. A run pins the version it read so that
    "why were these contacts chosen?" survives a later edit; a new run resolves
    whatever is active at the time.
    """
    service = await session.get(ServiceCatalog, service_id)
    if service is None:
        raise NoServiceIcpError("that service does not exist")
    if not service.is_active:
        raise NoServiceIcpError(
            f"{service.code} is not an active service, so nothing will be pitched to "
            "the contacts it would find"
        )

    linked = (
        await session.execute(
            select(IcpProfile)
            .join(
                service_icp_link,
                service_icp_link.c.icp_profile_id == IcpProfile.id,
            )
            .where(service_icp_link.c.service_id == service.id)
            .order_by(IcpProfile.name)
        )
    ).scalars().all()
    if not linked:
        raise NoServiceIcpError(
            f"{service.code} has no ICP yet — describe who it is for before "
            "spending provider credits looking for them"
        )

    chosen = list(linked)
    if icp_profile_ids:
        wanted = set(icp_profile_ids)
        chosen = [p for p in linked if p.id in wanted]
        unknown = wanted - {p.id for p in linked}
        if unknown:
            raise NoServiceIcpError(
                f"{len(unknown)} of the chosen ICPs are not linked to "
                f"{service.code}"
            )
        if not chosen:
            raise NoServiceIcpError("no ICP was chosen for this run")

    versions: list[IcpProfileVersion] = []
    for profile in chosen:
        active = (
            await session.execute(
                # `profile` eagerly, because the report names it. Left lazy it
                # loads on attribute access outside the async context and
                # raises MissingGreenlet — which crashed every enrichment run
                # rather than failing on any particular list.
                select(IcpProfileVersion)
                .options(selectinload(IcpProfileVersion.profile))
                .where(
                    IcpProfileVersion.icp_profile_id == profile.id,
                    IcpProfileVersion.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if active is None:
            # A named profile nobody has written yet. Reported rather than
            # skipped: a run that quietly drops one of the profiles it was
            # asked to target would enrich the wrong half of a list.
            raise NoServiceIcpError(
                f"ICP {profile.name!r} has no active version yet"
            )
        versions.append(active)
    return service, versions


async def verify_list(
    session: AsyncSession,
    *,
    list_id: uuid.UUID,
    service_id: uuid.UUID,
    icp_profile_ids: list[uuid.UUID] | None = None,
    clients: dict[str, ContactProvider] | None = None,
    account_ids: list[uuid.UUID] | None = None,
    contact_ids: list[uuid.UUID] | None = None,
) -> VerificationReport:
    """Run this list's unverified contacts through the waterfall, for a service.

    `service_id` is required rather than optional. Made optional it would
    default to "everyone", which is the behaviour this exists to remove — and
    the default would be taken by every caller that had not thought about it.

    `clients` is injected so this is testable without a network and without a
    contract. When it is omitted the providers come from configuration, and a
    provider with no client is reported rather than silently skipped.
    """
    service, icp_versions = await resolve_targeting(
        session, service_id=service_id, icp_profile_ids=icp_profile_ids
    )
    targets = target_personas(*(v.definition for v in icp_versions))
    if not targets:
        # Refused, not "enrich everyone". Buyer personas live on the ICP, and
        # an ICP that names nobody has not said who is worth a credit.
        names = ", ".join(sorted({v.profile.name for v in icp_versions}))
        raise NoServiceIcpError(
            f"{names} {'names' if len(icp_versions) == 1 else 'name'} no buyer "
            "personas — add them under ICP profiles before spending credits on anyone"
        )

    report = VerificationReport()
    report.service_code = service.code
    # The versions this run actually read, so a later edit to an ICP cannot
    # change the answer to "why were these contacts chosen?".
    report.icp_versions = [(v.profile.name, v.version) for v in icp_versions]
    credentialled, reasons = await credentialled_providers(session)

    # An injected client is the caller taking responsibility for where the call
    # goes; otherwise clients are built from the stored credentials.
    available = (
        clients if clients is not None
        else await build_clients(session, credentialled)
    )
    runnable = [p for p in credentialled if p in available]
    report.waterfall = runnable

    reasons.extend(
        f"{_label(p)}: this build has no client for it yet"
        for p in credentialled
        if p not in available
    )

    if not runnable:
        # Nothing was asked. Saying "0 verified" here would read as a clean
        # pass over a list nobody checked.
        report.blocked = (
            "No enrichment provider could be called. "
            + ("; ".join(reasons) if reasons else "No provider is configured.")
        )
        log.warning("verification.blocked list=%s reason=%s", list_id, report.blocked)
        return report

    ordered = [available[p] for p in runnable]
    wanted = await wanted_fields(session)
    report.wanted = list(wanted)
    contacts = await unverified_contacts(
        session, list_id=list_id, account_ids=account_ids, contact_ids=contact_ids
    )

    if not contacts:
        # Nothing to enrich is not the same as nothing found. Enrichment works
        # on *contacts*, and an account-grain import creates none — so a list
        # of companies reports "0 checked", which reads as a broken run rather
        # than a missing step. Say which it is.
        total = await session.scalar(
            select(func.count())
            .select_from(Contact)
            .join(
                AccountListMember,
                AccountListMember.account_id == Contact.account_id,
            )
            .where(AccountListMember.list_id == list_id)
        )
        report.blocked = (
            "The people you selected already have a verified address."
            if contact_ids
            else "Every contact on this list already has a verified address."
            if total
            else (
                "This list has no contacts yet. Enrichment finds addresses for "
                "people already on the list — import a file with contact "
                "columns (name, title, email or LinkedIn), or add them by hand."
            )
        )
        log.info(
            "verification.no_contacts list=%s total_contacts=%s", list_id, total
        )
        return report

    # Before paying to re-check a verified address that has aged, read the
    # saved Apollo contact: if Apollo still grades it verified, that settles it
    # for free. Only on a real run — injected clients never reach Apollo.
    people = None
    reconfirmed: set = set()
    if clients is None:
        stale = [c for c in contacts if needs_recheck(c)]
        if stale:
            from app.services import apollo_contacts, apollo_people

            people = await apollo_people.from_credentials(session)
            if people is not None:
                reconfirmed = await apollo_contacts.reconfirm_stale(stale, people)

    for contact in contacts:
        verdict = matches_persona(contact, targets)
        if verdict is False:
            # Nothing this service can pitch to them. Counted and named rather
            # than quietly enriched: a list that is mostly out of persona is a
            # list problem, and paying to confirm it would hide that.
            report.out_of_persona += 1
            report.outcomes.append(
                ContactOutcome(
                    contact.id, contact.full_name, "out_of_persona",
                    f"{contact.title or 'no title'} does not match what "
                    f"{service.code} targets",
                    [],
                )
            )
            continue
        if verdict is None and targets:
            # Nothing to judge on. Not a rejection — their title was simply
            # never imported — so they are held back rather than written off,
            # and the rep decides whether to spend on finding out.
            report.unknown_persona += 1
            report.outcomes.append(
                ContactOutcome(
                    contact.id, contact.full_name, "unknown_persona",
                    "no title or role to match against; not enriched",
                    [],
                )
            )
            continue

        if contact.id in reconfirmed:
            report.checked += 1
            report.verified += 1
            report.reconfirmed_free += 1
            report.outcomes.append(
                ContactOutcome(
                    contact.id, contact.full_name, "verified",
                    "re-confirmed from the saved Apollo contact — no credit spent",
                    ["apollo_contacts"],
                )
            )
            continue

        report.checked += 1
        outcome = await _verify_one(
            session, contact=contact, providers=ordered, wanted=wanted
        )
        if outcome.outcome == "verified":
            report.with_phone += bool(contact.phone)
            report.with_linkedin += bool(contact.linkedin_url)
        report.contact_linkedin_from_provider += outcome.linkedin_filled
        report.company_linkedin_from_provider += bool(outcome.company_linkedin)
        report.outcomes.append(outcome)
        setattr(report, outcome.outcome, getattr(report, outcome.outcome, 0) + 1)

    # The company's own site, for whatever the providers left without a
    # LinkedIn link — every contact in the pass, persona or not: it costs no
    # credit, and a profile link is contact data worth having either way.
    await fill_linkedin_from_sites(contacts, report, session=session)

    # What Apollo enriched on this pass is saved to the Apollo account, so it
    # is never paid for again.
    if clients is None:
        fresh = [c for c in contacts if c.email_provider == "apollo" and not c.apollo_contact_id]
        if fresh:
            from app.services import apollo_contacts, apollo_people

            people = people or await apollo_people.from_credentials(session)
            if people is not None:
                report.saved_to_apollo, error = await apollo_contacts.save(session, people, fresh)
                if error:
                    report.apollo_note = f"Could not save to Apollo: {error}"

    await session.flush()
    log.info(
        "verification.done list=%s service=%s icp=v%s wanted=%s checked=%d "
        "verified=%d with_phone=%d with_linkedin=%d risky=%d not_found=%d "
        "unavailable=%d out_of_persona=%d unknown_persona=%d",
        list_id, report.service_code, report.icp_versions, list(wanted),
        report.checked, report.verified, report.with_phone, report.with_linkedin,
        report.risky, report.not_found, report.unavailable, report.out_of_persona,
        report.unknown_persona,
    )
    return report


def _company_page_from(record, account) -> str | None:
    """Fill the account's LinkedIn page from a provider record, if it is theirs.

    Only when the organisation the provider placed the person at has the
    account's own domain. A person can be matched at a former employer, or at a
    parent company, and that organisation's page is not this account's.
    """
    from app.services.resolution import normalise_domain, normalise_linkedin

    if account is None or getattr(account, "linkedin_url", None):
        return None
    page = normalise_linkedin(getattr(record, "organization_linkedin_url", None))
    theirs = normalise_domain(getattr(record, "organization_domain", None))
    ours = normalise_domain(getattr(account, "domain", None))
    if not page or not theirs or theirs != ours:
        return None
    account.linkedin_url = page
    return page


async def _account_of(session, contact):
    """The contact's account, loaded explicitly.

    `contact.awaitable_attrs.account` only exists on models that mix in
    SQLAlchemy's `AsyncAttrs`, and these do not. Guarded by `hasattr`, that
    lookup quietly returned None for every real contact — so enrichment sent
    Apollo a name with no company domain, and the Apollo client, rightly
    refusing to match a bare name, never asked. No contact without a LinkedIn
    URL was ever looked up. A plain attribute read is no fix either: it lazy
    loads outside the async context and raises.
    """
    lazy = getattr(contact, "awaitable_attrs", None)
    if lazy is not None:
        return await lazy.account
    account_id = getattr(contact, "account_id", None)
    if session is not None and account_id is not None:
        from app.models.account import Account

        return await session.get(Account, account_id)
    return None


async def fill_linkedin_from_sites(contacts, report, *, session=None, http=None) -> None:
    """Look on each company's own website for LinkedIn links still missing.

    After the providers, and free: one read of the site per account, however
    many of its contacts need a profile. Only an unambiguous link is taken —
    see `services/site_links.py`. What could not be settled is noted on the
    report rather than guessed.
    """
    from app.services import site_links

    by_account: dict = {}
    for contact in contacts:
        account = await _account_of(session, contact)
        if account is None:
            continue
        by_account.setdefault(account.id, (account, []))[1].append(contact)

    for account, people in by_account.values():
        needs_company = not getattr(account, "linkedin_url", None)
        needs_people = [c for c in people if not c.linkedin_url]
        domain = getattr(account, "domain", None)
        if not domain or not (needs_company or needs_people):
            continue
        links = await site_links.read_site(domain, http=http)
        if not links.answered:
            report.linkedin_notes.append(f"{domain} did not answer — no LinkedIn links read")
            continue
        if needs_company:
            page = site_links.company_page(links)
            if page:
                account.linkedin_url = page
                report.company_linkedin_from_site += 1
            elif len(links.company_pages) > 1:
                report.linkedin_notes.append(
                    f"{domain} links {len(links.company_pages)} LinkedIn company pages — none taken"
                )
        for contact in needs_people:
            url = site_links.profile_for(contact.full_name, links.profiles)
            if url:
                contact.linkedin_url = url
                report.contact_linkedin_from_site += 1


async def _verify_one(
    session: AsyncSession,
    *,
    contact: Contact,
    providers: list[ContactProvider],
    wanted: tuple[str, ...] = DEFAULT_WANTED_FIELDS,
) -> ContactOutcome:
    """One contact, through the waterfall, written back with its provenance.

    `wanted` decides how far down the waterfall to go; `GATING_FIELDS` decides
    what the result is called. A contact with an email and no phone is verified
    and was worth the extra call that failed to find the number.
    """
    account = await _account_of(session, contact)
    domain = getattr(account, "domain", None)

    outcome = await enrich(
        full_name=contact.full_name,
        company_domain=domain,
        linkedin_url=contact.linkedin_url,
        providers=providers,
        required=wanted,
    )
    called = [p.value if hasattr(p, "value") else str(p) for p in outcome.called]

    if outcome.errors and outcome.contact is None:
        # Every provider we asked failed. The contact is unchanged and stays
        # unverified, which is what makes a retry correct rather than a
        # duplicate charge.
        return ContactOutcome(
            contact.id, contact.full_name, "unavailable",
            "; ".join(f"{k}: {v}" for k, v in outcome.errors.items()),
            called,
        )

    # Title and LinkedIn are kept whenever the provider recognised the person,
    # whether or not it had an address. They used to be written only after the
    # address gate, so a person Apollo knew — profile and all — but held no
    # usable email for came back "not found" with the profile thrown away.
    linkedin_filled = False
    company_linkedin = None
    if outcome.contact is not None:
        known = outcome.contact
        if known.title and not contact.title:
            contact.title = known.title
        if known.linkedin_url and not contact.linkedin_url:
            contact.linkedin_url = known.linkedin_url
            linkedin_filled = True
        company_linkedin = _company_page_from(known, account)

    # Judged on the gate, not on everything we went looking for. A missing
    # phone number leaves `still_missing` non-empty on a contact who is
    # perfectly reachable, and reading that as "not found" would write off the
    # list.
    if outcome.contact is None or outcome.contact.missing(GATING_FIELDS):
        return ContactOutcome(
            contact.id, contact.full_name, "not_found",
            "no address found for this person",
            called,
            linkedin_filled=linkedin_filled,
            company_linkedin=company_linkedin,
        )

    found = outcome.contact
    source = found.sources.get("email", called[-1] if called else "unknown")

    contact.email = found.email or contact.email
    # The provider's verdict, not ours. A guess stored as `verified` would pass
    # the gate that exists to stop that send.
    contact.email_status = found.email_status
    contact.email_verified_at = datetime.now(UTC) if found.email_status == "verified" else None
    # Provenance, not decoration: a bad source has to be traceable later
    # without distrusting every contact on the list.
    contact.email_provider = source if source in ("apollo", "contactout") else None
    contact.email_provider_record_id = found.provider_record_id

    # Phone and LinkedIn are collected and stored, not gated on. They are
    # contact data — a rep wants the number on the record — and neither is a
    # condition of the person being reachable by the channels this system uses.
    if found.phone and not contact.phone:
        contact.phone = found.phone
        # Whoever supplied the number, not whoever supplied the address.
        phone_source = found.sources.get("phone", source)
        contact.phone_provider = (
            phone_source if phone_source in ("apollo", "contactout") else None
        )
        contact.phone_provider_record_id = found.provider_record_id
        # `unverified` unless a provider actually grades numbers. Neither does
        # today, and calling a published number verified would be a claim
        # nothing behind it supports.
        contact.phone_status = found.phone_status

    if found.email_status != "verified":
        # Found, and not safe to send to. The address is still written above —
        # a rep can see it and decide — but this is not a verified contact and
        # must not be counted as one. A list full of guesses reading as ready
        # is how a sending domain gets burned.
        return ContactOutcome(
            contact.id, contact.full_name, "risky",
            f"{source} returned an address it grades as {found.email_status!r}",
            called,
            linkedin_filled=linkedin_filled,
            company_linkedin=company_linkedin,
        )

    return ContactOutcome(
        contact.id, contact.full_name, "verified", f"verified by {source}", called,
        linkedin_filled=linkedin_filled, company_linkedin=company_linkedin,
    )
