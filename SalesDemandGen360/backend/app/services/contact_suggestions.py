"""Suggested contacts: Apollo's free search, a rep's decision, then a paid reveal.

Enrichment used to start from the people a spreadsheet named, and on the Test
Data list Apollo recognised none of them. This starts from the other end:

1. **Find** (free). For each resolved account, one `mixed_people/api_search`
   per ICP persona — the persona's titles, or its buying role's seniorities
   when it names no titles. Apollo's "similar titles" is generous, so every
   result is read again through `personas.matches_any`, the same matcher the
   Buyer dimension uses, and at most `suggestions_per_persona` are kept per
   persona per account.
2. **Match.** A result is recognised as a contact already on the account by
   Apollo id, or by first name plus the visible letters of Apollo's obfuscated
   surname (`Pe***d` fits Penland) — exactly one, or none. A known contact who
   already has a verified address and a LinkedIn profile is marked `known`:
   there is nothing left to buy.
3. **Decide.** A rep accepts or rejects each suggestion. Nothing is revealed
   without that.
4. **Reveal** (paid). Accepted suggestions go to `people/bulk_match` by Apollo
   id — never personal emails, never phones. The contact is created, or the
   matched one filled in: name, title, email with Apollo's own grade,
   LinkedIn profile, city and country. The account's country and LinkedIn page
   are filled only when Apollo places the person at the account's own domain.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountListMember, Contact, ContactSuggestion
from app.services import apollo_contacts, linkedin, personas
from app.services import persona as title_classes
from app.services.apollo_people import MAX_PER_PAGE, ROLE_SENIORITIES, Found, OutOfCredits
from app.services.dimensions import personas_of
from app.services.enrichment_clients import (
    APOLLO_EMAIL_STATUS,
    APOLLO_LOCKED_EMAIL,
    _apollo_recognised,
)
from app.services.providers import ProviderError
from app.services.resolution import normalise_domain, normalise_linkedin

log = logging.getLogger(__name__)

#: Results asked for per suggestion wanted. The title re-check drops people
#: Apollo's similar-titles matching let in, so the page is wider than the cap.
OVERSEARCH = 5
#: A rep or a reveal has already settled these; a new search leaves them alone.
DECIDED = ("rejected", "revealed", "not_found")
#: Which statuses a rep may move a suggestion between.
DECIDABLE = ("proposed", "accepted", "rejected")


@dataclass(frozen=True)
class PersonaQuery:
    #: The buying role in words, else the persona's first title.
    persona: str
    buying_role: str | None
    titles: tuple[str, ...]
    seniorities: tuple[str, ...]


def persona_queries(*definitions: dict | None) -> tuple[list[PersonaQuery], list[str]]:
    """One search per ICP persona, and the personas that name nothing searchable."""
    queries: list[PersonaQuery] = []
    skipped: list[str] = []
    seen: set[tuple] = set()
    for definition in definitions:
        for role, titles in personas_of(definition or {}):
            role_ = role if role in personas.BUYING_ROLES else None
            if role_ is None:
                # An older definition lists a bare buying role as a string.
                role_ = next((t for t in titles if t in personas.BUYING_ROLES), None)
            wanted = tuple(t for t in titles if t not in personas.BUYING_ROLES)
            seniorities = () if wanted else ROLE_SENIORITIES.get(role_ or "", ())
            label = (role_ or "").replace("_", " ") or (wanted[0] if wanted else "")
            if not wanted and not seniorities:
                skipped.append(label or "a persona")
                continue
            key = (role_, tuple(t.casefold() for t in wanted))
            if key in seen:
                continue
            seen.add(key)
            queries.append(PersonaQuery(label, role_, wanted, seniorities))
    return queries, skipped


def _fold(text: str | None) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().casefold()


def _letters(text: str | None) -> str:
    return re.sub(r"[^a-z]", "", _fold(text))


def last_name_fits(last_name: str | None, hint: str | None) -> bool:
    """Whether a surname is consistent with Apollo's obfuscated one (`Pe***d`)."""
    last = _letters(last_name)
    if not last or not hint:
        return False
    parts = [_letters(p) for p in re.split(r"\*+", hint)]
    if len(parts) == 1:
        return last == parts[0]
    prefix, suffix = parts[0], parts[-1]
    if not prefix and not suffix:
        return False
    return (
        last.startswith(prefix)
        and last.endswith(suffix)
        and len(last) >= len(prefix) + len(suffix)
    )


def match_contact(found: Found, contacts: list[Contact]) -> Contact | None:
    """The one contact on the account this person already is, or None."""
    for contact in contacts:
        if contact.apollo_person_id and contact.apollo_person_id == found.apollo_id:
            return contact
    first = _letters(found.first_name)
    if not first:
        return None
    hits = []
    for contact in contacts:
        parts = (contact.full_name or "").split()
        if len(parts) >= 2 and _letters(parts[0]) == first and last_name_fits(parts[-1], found.last_name_hint):
            hits.append(contact)
    return hits[0] if len(hits) == 1 else None


#: Titles that name a role only to say whom they support. Apollo's similar
#: titles returns "Chief of Staff to the CEO" for a CEO search, and the title
#: matcher, reading `ceo` in it, agrees — live, on apollo.io.
SUPPORTS_THE_ROLE = re.compile(
    r"\b(chief of staff|assistant|secretary|ea to|pa to|office of the)\b", re.I
)


def fits(found: Found, query: PersonaQuery, *, strict: bool = False) -> bool:
    """Whether a result really is this persona — Apollo's similar titles are generous.

    `strict` is for results found by seniority rather than by title. There the
    title has to name the persona's job, not merely its rank: the matcher reads
    a title with no function it knows on rank alone, which is right for a CSV's
    bare "VP" and wrong for a search of every senior person — live, it offered
    BlueWave's Chief Legal Officer as a CEO and its FP&A Director as an IT head.
    """
    if found.title and SUPPORTS_THE_ROLE.search(found.title):
        return False
    if not query.titles:
        return True
    if not found.title or not personas.matches_any(found.title, query.titles):
        return False
    if not strict:
        return True
    wanted = set().union(*(personas.functions(personas.tokens(t)) for t in query.titles))
    return not wanted or bool(personas.functions(personas.tokens(found.title)) & wanted)


def _complete(contact: Contact) -> bool:
    return contact.email_status == "verified" and bool(contact.linkedin_url)


@dataclass
class FindOutcome:
    account_id: uuid.UUID
    name: str
    #: Searches made — one per persona. Free.
    requests: int = 0
    #: New suggestions waiting for a decision.
    proposed: int = 0
    #: Suggestions already waiting, seen again and refreshed.
    refreshed: int = 0
    #: Of those, people already on the account who a reveal would fill in.
    on_list: int = 0
    #: People already on the account with a verified address and a profile.
    known: int = 0
    #: Rejected or revealed before; left alone.
    already_decided: int = 0
    #: Results whose title did not answer the persona.
    filtered: int = 0
    #: Undecided suggestions from an earlier search that this one no longer keeps.
    dropped: int = 0
    note: str = ""


async def find_for_account(
    session: AsyncSession,
    *,
    list_id: uuid.UUID,
    account: Account,
    queries: list[PersonaQuery],
    people,
    cap: int,
) -> FindOutcome:
    outcome = FindOutcome(account.id, account.name)
    domain = normalise_domain(account.domain)
    if not domain:
        outcome.note = "no domain — confirm the company first"
        return outcome

    contacts = list(
        (await session.execute(select(Contact).where(Contact.account_id == account.id))).scalars()
    )
    held = {
        s.apollo_person_id: s
        for s in (
            await session.execute(
                select(ContactSuggestion).where(ContactSuggestion.account_id == account.id)
            )
        ).scalars()
    }
    taken: set[str] = set()
    for query in queries:
        # Titles first. Apollo's similar titles do not reach every way a company
        # names its head: at apexsoftware.com the senior people are "President"
        # and "Owner", and a search for CEO returned neither. So when titles
        # leave room, the buying role's seniorities are searched as well — still
        # free — and read through the same title matcher, which does know that an
        # owner runs the company.
        searches = [(query.titles, query.seniorities, False)]
        fallback = ROLE_SENIORITIES.get(query.buying_role or "", ())
        if query.titles and fallback:
            searches.append(((), fallback, True))
        kept = 0
        for titles, seniorities, strict in searches:
            if kept >= cap:
                break
            found = await people.search(
                domain=domain,
                titles=titles,
                seniorities=seniorities,
                per_page=min(MAX_PER_PAGE, cap * OVERSEARCH),
            )
            outcome.requests += 1
            for person in found:
                if kept >= cap:
                    break
                if person.apollo_id in taken:
                    continue
                if not fits(person, query, strict=strict):
                    outcome.filtered += 1
                    continue
                taken.add(person.apollo_id)
                kept += 1

                row = held.get(person.apollo_id)
                if row is not None and row.status in DECIDED:
                    outcome.already_decided += 1
                    continue
                contact = match_contact(person, contacts)
                new = row is None
                if new:
                    row = ContactSuggestion(
                        list_id=list_id, account_id=account.id,
                        apollo_person_id=person.apollo_id, status="proposed",
                    )
                    session.add(row)
                    held[person.apollo_id] = row
                row.first_name = person.first_name
                row.last_name_hint = person.last_name_hint
                row.title = person.title
                row.persona = query.persona
                row.buying_role = query.buying_role
                row.has_email = person.has_email
                row.has_location = person.has_location
                row.has_direct_phone = person.has_direct_phone
                row.refreshed_at = person.refreshed_at
                row.contact_id = contact.id if contact is not None else None

                if contact is not None and _complete(contact):
                    row.status = "known"
                    outcome.known += 1
                    continue
                if row.status == "known":
                    row.status = "proposed"
                if new:
                    outcome.proposed += 1
                else:
                    outcome.refreshed += 1
                if contact is not None:
                    outcome.on_list += 1

    # A search replaces what it proposed before. A suggestion nobody decided on
    # that this one no longer keeps — a tighter filter, a smaller cap — has no
    # decision to protect, and leaving it would ask a rep about someone the
    # current rules would not suggest.
    for apollo_id, row in held.items():
        if row.status == "proposed" and apollo_id not in taken:
            await session.delete(row)
            outcome.dropped += 1
    await session.flush()
    return outcome


async def for_list(
    session: AsyncSession, list_id: uuid.UUID, statuses: tuple[str, ...] | None = None
) -> list[tuple[ContactSuggestion, Account, Contact | None]]:
    """Suggestions at this list's accounts, with the contact each one already is."""
    stmt = (
        select(ContactSuggestion, Account)
        .join(Account, Account.id == ContactSuggestion.account_id)
        .join(
            AccountListMember,
            (AccountListMember.account_id == Account.id) & (AccountListMember.list_id == list_id),
        )
        .order_by(Account.name, ContactSuggestion.persona, ContactSuggestion.title)
    )
    if statuses:
        stmt = stmt.where(ContactSuggestion.status.in_(statuses))
    rows = (await session.execute(stmt)).all()
    ids = {s.contact_id for s, _ in rows if s.contact_id}
    contacts = {}
    if ids:
        contacts = {
            c.id: c
            for c in (await session.execute(select(Contact).where(Contact.id.in_(ids)))).scalars()
        }
    return [(s, a, contacts.get(s.contact_id)) for s, a in rows]


async def decide(
    session: AsyncSession, list_id: uuid.UUID, ids: list[uuid.UUID], status: str
) -> int:
    """Accept, reject, or undo. Only suggestions still open to a decision move."""
    if status not in DECIDABLE:
        raise ValueError(f"{status} is not a decision")
    changed = 0
    for suggestion, _, _ in await for_list(session, list_id, DECIDABLE):
        if suggestion.id in ids and suggestion.status != status:
            suggestion.status = status
            changed += 1
    return changed


@dataclass
class Applied:
    contact: Contact
    created: bool
    email_status: str | None = None
    linkedin_added: bool = False
    company_country: bool = False
    company_linkedin: bool = False
    note: str = ""


def _email(person: dict) -> tuple[str | None, str]:
    email = person.get("email")
    if not isinstance(email, str) or not email.strip() or email.strip().lower() == APOLLO_LOCKED_EMAIL:
        return None, "unverified"
    return email.strip(), APOLLO_EMAIL_STATUS.get(person.get("email_status") or "", "unverified")


def _clean(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


async def apply_person(
    session: AsyncSession, suggestion: ContactSuggestion, person: dict, account: Account
) -> Applied:
    """Write a revealed person onto the contact they are, or a new one."""
    contacts = list(
        (await session.execute(select(Contact).where(Contact.account_id == account.id))).scalars()
    )
    apollo_id = _clean(person.get("id")) or suggestion.apollo_person_id
    email, grade = _email(person)

    target = next((c for c in contacts if suggestion.contact_id and c.id == suggestion.contact_id), None)
    if target is None:
        target = next((c for c in contacts if c.apollo_person_id == apollo_id), None)
    if target is None and email:
        target = next((c for c in contacts if (c.email or "").casefold() == email.casefold()), None)

    title = _clean(person.get("title")) or suggestion.title
    classes = title_classes.classify(title)
    created = target is None
    if created:
        name = _clean(person.get("name")) or " ".join(
            p for p in (_clean(person.get("first_name")), _clean(person.get("last_name"))) if p
        )
        target = Contact(
            account_id=account.id,
            full_name=name or suggestion.first_name or "Unknown",
            title=title,
            seniority=classes["seniority"],
            persona_role=classes["persona_role"],
            buying_role=suggestion.buying_role or classes["buying_role"],
        )
        session.add(target)
        contacts.append(target)
    else:
        if not target.title and title:
            target.title = title
        if target.seniority == "unknown" and title:
            target.seniority = classes["seniority"]
        if not target.persona_role:
            target.persona_role = classes["persona_role"]
        if not target.buying_role:
            target.buying_role = suggestion.buying_role or classes["buying_role"]

    applied = Applied(target, created)
    if email and target.email_status != "verified":
        clash = next(
            (c for c in contacts if c is not target and (c.email or "").casefold() == email.casefold()),
            None,
        )
        if clash is None:
            target.email = email
            target.email_status = grade
            target.email_verified_at = datetime.now(UTC) if grade == "verified" else None
            target.email_provider = "apollo"
            target.email_provider_record_id = apollo_id
            applied.email_status = grade
        else:
            applied.note = f"the address Apollo gave already belongs to {clash.full_name}"

    slug = linkedin.person_slug(_clean(person.get("linkedin_url")))
    if slug and not target.linkedin_url:
        target.linkedin_url = f"https://www.linkedin.com/in/{slug}"
        applied.linkedin_added = True
    target.city = target.city or _clean(person.get("city"))
    target.country = target.country or _clean(person.get("country"))
    target.apollo_person_id = apollo_id

    org = person.get("organization") if isinstance(person.get("organization"), dict) else {}
    org_domain = normalise_domain(org.get("primary_domain") or org.get("website_url"))
    if org_domain and org_domain == normalise_domain(account.domain):
        if not account.hq_country and _clean(org.get("country")):
            account.hq_country = _clean(org.get("country"))
            applied.company_country = True
        page = normalise_linkedin(org.get("linkedin_url"))
        if not account.linkedin_url and page:
            account.linkedin_url = page
            applied.company_linkedin = True

    await session.flush()
    return applied


@dataclass
class RevealReport:
    asked: int = 0
    revealed: int = 0
    created: int = 0
    updated: int = 0
    verified: int = 0
    risky: int = 0
    no_email: int = 0
    linkedin: int = 0
    not_found: int = 0
    #: What Apollo reports it charged, or one per person found when it does not say.
    credits: int = 0
    #: Already revealed once — their stored details were used and Apollo was not
    #: asked, so no credit was spent on them again.
    reused: int = 0
    #: Revealed people saved as contacts in the Apollo account on this pass.
    saved_to_apollo: int = 0
    #: Apollo's refusal to save, if any. The reveal stands either way.
    save_error: str | None = None
    #: Set when Apollo ran out of credits part-way. Those not revealed stay accepted.
    stopped: str | None = None
    company_country: int = 0
    company_linkedin: int = 0
    notes: list[str] = field(default_factory=list)


async def reveal(
    session: AsyncSession,
    *,
    suggestions: list[ContactSuggestion],
    people,
    now: datetime | None = None,
) -> RevealReport:
    """Reveal accepted suggestions and write them onto contacts."""
    now = now or datetime.now(UTC)
    report = RevealReport(asked=len(suggestions))
    if not suggestions:
        return report

    # Somebody this installation already paid to reveal is never sent to Apollo
    # again. Their contact row carries the Apollo person id and what the reveal
    # returned, so the suggestion is settled from that, for nothing.
    paid = {
        c.apollo_person_id: c
        for c in (
            await session.execute(
                select(Contact).where(
                    Contact.apollo_person_id.in_([s.apollo_person_id for s in suggestions]),
                    (Contact.email.is_not(None)) | (Contact.linkedin_url.is_not(None)),
                )
            )
        ).scalars()
    }
    to_buy = []
    for suggestion in suggestions:
        known = paid.get(suggestion.apollo_person_id)
        if known is None:
            to_buy.append(suggestion)
            continue
        suggestion.contact_id = known.id
        suggestion.status = "revealed"
        suggestion.revealed_at = suggestion.revealed_at or now
        suggestion.note = "already revealed — stored details used, no credit spent"
        report.revealed += 1
        report.reused += 1
        report.linkedin += bool(known.linkedin_url)
        report.verified += known.email_status == "verified"
        report.risky += known.email_status == "risky"
        report.no_email += not known.email
    # Then people saved as contacts in the Apollo account: Apollo keeps their
    # data accessible at no cost, where a lookup of an unsaved person is charged
    # again. One free search per company.
    to_buy = await _settle_from_saved_contacts(session, to_buy, people, report, now)
    matches: dict[str, dict] = {}
    answered = to_buy
    if to_buy:
        try:
            matches, report.credits = await people.reveal([s.apollo_person_id for s in to_buy])
        except OutOfCredits as exc:
            # Keep what was bought before the credits ran out. Everyone Apollo
            # did not answer stays accepted — not "not found" — for next time.
            if not exc.revealed and not report.reused:
                raise
            matches, report.credits = exc.revealed, exc.credits
            report.stopped = str(exc)
            answered = [s for s in to_buy if s.apollo_person_id in matches]
    for suggestion in answered:
        person = matches.get(suggestion.apollo_person_id)
        if not person or not _apollo_recognised(person):
            suggestion.status = "not_found"
            suggestion.note = "Apollo returned no record for this person"
            report.not_found += 1
            continue
        account = await session.get(Account, suggestion.account_id)
        applied = await apply_person(session, suggestion, person, account)
        suggestion.contact_id = applied.contact.id
        suggestion.status = "revealed"
        suggestion.revealed_at = now
        suggestion.note = applied.note or None
        report.revealed += 1
        report.created += applied.created
        report.updated += not applied.created
        report.verified += applied.email_status == "verified"
        report.risky += applied.email_status == "risky"
        report.no_email += applied.email_status is None
        report.linkedin += applied.linkedin_added
        report.company_country += applied.company_country
        report.company_linkedin += applied.company_linkedin
        if applied.note:
            report.notes.append(f"{applied.contact.full_name}: {applied.note}")

    # Everyone revealed is saved to the Apollo account, so looking them up again
    # costs nothing. A refusal is reported; the reveal stands.
    await _save_revealed(session, suggestions, people, report, now)
    return report


async def _settle_from_saved_contacts(
    session: AsyncSession, suggestions: list[ContactSuggestion], people, report: RevealReport,
    now: datetime,
) -> list[ContactSuggestion]:
    """Settle suggestions already saved in the Apollo account. Returns the rest."""
    remaining: list[ContactSuggestion] = []
    by_account: dict = {}
    for suggestion in suggestions:
        by_account.setdefault(suggestion.account_id, []).append(suggestion)
    for account_id, group in by_account.items():
        account = await session.get(Account, account_id)
        try:
            saved = await apollo_contacts.saved_by_person(people, account.name if account else "")
        except ProviderError as exc:
            report.notes.append(f"saved Apollo contacts could not be searched: {exc}")
            saved = {}
        for suggestion in group:
            match = saved.get(suggestion.apollo_person_id)
            if match is None or not (match.email or match.linkedin_url):
                remaining.append(suggestion)
                continue
            applied = await apply_person(session, suggestion, apollo_contacts.as_person(match), account)
            applied.contact.apollo_contact_id = applied.contact.apollo_contact_id or match.id
            applied.contact.apollo_saved_at = applied.contact.apollo_saved_at or now
            suggestion.contact_id = applied.contact.id
            suggestion.status = "revealed"
            suggestion.revealed_at = suggestion.revealed_at or now
            suggestion.note = "saved in the Apollo account — no credit spent"
            report.reused += 1
            report.revealed += 1
            report.created += applied.created
            report.updated += not applied.created
            report.verified += applied.email_status == "verified"
            report.risky += applied.email_status == "risky"
            report.no_email += applied.email_status is None
            report.linkedin += applied.linkedin_added
            report.company_country += applied.company_country
            report.company_linkedin += applied.company_linkedin
    return remaining


async def _save_revealed(
    session: AsyncSession, suggestions: list[ContactSuggestion], people, report: RevealReport,
    now: datetime,
) -> None:
    ids = {s.contact_id for s in suggestions if s.status == "revealed" and s.contact_id}
    if not ids:
        return
    contacts = list((await session.execute(select(Contact).where(Contact.id.in_(ids)))).scalars())
    report.saved_to_apollo, report.save_error = await apollo_contacts.save(
        session, people, contacts, now=now
    )
