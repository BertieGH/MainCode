"""CSV import — parse, map, dry-run, commit.

The dry run is the point of this module. An import that writes first and reports
afterwards leaves someone reconciling a half-merged list by hand; one that
reports first lets them cancel.

Both paths run **the same resolution logic**, so the preview is not an estimate
of what would happen — it is the same decision, taken twice.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountList, AccountListMember, Contact
from app.services import sizing

Outcome = Literal[
    # account-grain outcomes
    "created", "merged", "duplicate_in_file", "already_in_list", "skipped_no_name",
    # contact-grain outcomes
    "contact_created", "contact_updated", "duplicate_contact_in_file", "skipped_no_contact",
]

#: Company columns. A file does not have to be edited before it can be imported.
ACCOUNT_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "company", "company name", "account", "account name", "organisation",
             "organization"),
    "domain": ("domain", "website", "url", "company domain", "web"),
    "industry": ("industry", "sector", "vertical"),
    # `# employees`, `company country` and `company state` are what an **Apollo
    # account export** calls these, and matching is exact on the lowered
    # header — so a real export of 57 accounts imported with no headcount at
    # all, no country and no region, in silence. Resolution then paid Apollo
    # per account for numbers that were already in the file.
    #
    # Silent is the problem. A dropped column reads downstream as a company
    # nobody could size, which is indistinguishable from one Apollo has never
    # heard of — and `sizing.band_for` deliberately refuses to guess, so the
    # whole book scored on base weights and looked like a data desert.
    "employee_count": ("employees", "employee count", "headcount", "size", "employee_count",
                       "# employees", "number of employees", "num employees",
                       "employee range", "company size"),
    # **Company-qualified names first.** `suggest_mapping` takes the first
    # alias that matches, and an Apollo *contacts* export carries both
    # `Country` (the person's) and `Company Country`. With the bare name
    # first, importing one stamped the contact's own location onto the
    # company — the same shape as the `linkedin` bug this module already
    # guards, and just as silent.
    "hq_country": ("company country", "hq country", "location country", "country"),
    "hq_region": ("company state", "company region", "hq region", "region",
                  "province", "state"),
    # Deliberately company-scoped. A bare "linkedin" column is claimed by the
    # contact mapping below — see `classify_linkedin`.
    "linkedin_url": ("company linkedin", "company linkedin url", "organization linkedin"),
    "funding_stage": ("funding", "funding stage", "stage", "latest funding"),
}

#: Person columns. Their presence is what makes a file contact-grain.
CONTACT_ALIASES: dict[str, tuple[str, ...]] = {
    "full_name": ("full name", "contact", "contact name", "person", "name"),
    "first_name": ("first name", "first", "firstname", "given name"),
    "last_name": ("last name", "last", "lastname", "surname", "family name"),
    "title": ("title", "job title", "position", "role", "designation",
              "job role", "job_title", "jobtitle"),
    "email": ("email", "email address", "work email", "e-mail"),
    # Apollo emits three, and a work number is the only one worth having:
    # a personal mobile is the wrong channel for cold B2B outreach, which
    # is why `apollo_people` never asks for one either.
    "phone": ("work direct phone", "corporate phone", "phone", "phone number",
              "direct dial", "mobile", "mobile phone"),
    # `person linkedin url` is what Apollo emits, and it was missing — so a
    # contacts export imported with no profile URL at all. That URL is what
    # `linkedin_index` queries per person, so losing it costs the contact
    # signals their best input.
    "contact_linkedin_url": ("person linkedin url", "contact linkedin url",
                             "person linkedin", "contact linkedin", "linkedin url",
                             "linkedin_url", "linkedin", "profile url"),
}

#: Columns that, once populated, mean the file has one row per *person*.
#: A mapped column that means the file describes *people*.
#:
#: `full_name` belongs here and was missing, which cost a real import: a file
#: of `Company name | website | contact Name | Designation` mapped the two
#: company columns, failed the person test — because `Designation` is not a
#: recognised title and `full_name` did not count — and then wiped every
#: contact field. It imported one company, zero contacts, and enrichment had
#: nobody to work on. A column literally called "contact name" is as clear a
#: person marker as an email address.
GRAIN_MARKERS = (
    "full_name", "email", "first_name", "last_name", "title",
    "contact_linkedin_url",
)

#: The person-name headers that mean a person and cannot mean anything else.
#:
#: `name` is deliberately absent. It is an alias for the company *and* for the
#: contact, so a company file of `Name | Website | Industry` would otherwise be
#: read as a list of people and its company names filed as person names. Only a
#: header that says so — "contact name", "full name" — settles the grain on its
#: own; a bare `name` waits for corroboration from an email, a title or a
#: LinkedIn profile.
UNAMBIGUOUS_PERSON_NAME = tuple(
    a for a in CONTACT_ALIASES["full_name"] if a != "name"
)


def classify_linkedin(url: str | None) -> str | None:
    """Whether a LinkedIn URL names a company or a person.

    Routed by the URL rather than by the column header, because the header is
    the thing that lies. A contact export's `linkedin` column holds
    `/in/<person>`, and mapping it by name onto the account writes somebody's
    personal profile onto the company record — silently, and on every row.

    Returns `"company"`, `"person"`, or `None` when it is neither.
    """
    if not url:
        return None
    lowered = url.strip().lower()
    if "linkedin.com" not in lowered:
        return None
    if "/company/" in lowered or "/showcase/" in lowered:
        return "company"
    if "/in/" in lowered or "/pub/" in lowered:
        return "person"
    return None


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """Best-guess header → field mapping. The rep confirms it before anything runs.

    Account and contact fields share one namespace, and where both could claim
    a header the contact wins: a file with a `name` column and an `email`
    column is a list of people, and reading `name` as the company would put a
    person's name in the account.
    """
    lowered = {h.strip().lower(): h for h in headers}
    mapping: dict[str, str | None] = {}

    for field_name, aliases in ACCOUNT_ALIASES.items():
        mapping[field_name] = next((lowered[a] for a in aliases if a in lowered), None)
    for field_name, aliases in CONTACT_ALIASES.items():
        mapping[field_name] = next((lowered[a] for a in aliases if a in lowered), None)

    person_columns = any(
        mapping.get(f) for f in GRAIN_MARKERS if f != "full_name"
    )
    if not person_columns and mapping.get("full_name"):
        # A person-name column decides the grain only when it is unambiguous.
        # This is what a real import needed: `contact Name` with no email and
        # an unrecognised `Designation` had nothing to corroborate it, so every
        # contact field was wiped and the file imported zero people.
        person_columns = (
            mapping["full_name"].strip().lower() in UNAMBIGUOUS_PERSON_NAME
        )
    if person_columns:
        # `name` is claimed by both. On a person file it is the person.
        if mapping.get("full_name") and mapping["full_name"] == mapping.get("name"):
            mapping["name"] = next(
                (lowered[a] for a in ACCOUNT_ALIASES["name"][1:] if a in lowered), None
            )
    else:
        # No people here, so nothing should be mapped as one.
        for field_name in CONTACT_ALIASES:
            mapping[field_name] = None

    return mapping


def detect_grain(rows: list[dict[str, str]], mapping: dict[str, str | None]) -> str:
    """`"contact"` when the file has one row per person, `"account"` otherwise.

    Detected rather than declared. Asking somebody to tell us the grain is
    asking them to get it right, and the cost of getting it wrong is silent:
    a contact file read as accounts reports "1 created, 4 duplicates" and
    discards four people.

    A mapped person column is not enough — it has to be *populated*, because a
    company export can carry an empty `title` column.
    """
    for field_name in GRAIN_MARKERS:
        header = mapping.get(field_name)
        if header and any((row.get(header) or "").strip() for row in rows):
            return "contact"
    return "account"


def normalise_domain(raw: str | None) -> str | None:
    """Reduce a website cell to a bare host.

    ``https://www.Acme.com/careers?utm=x`` and ``acme.com`` are the same company,
    and treating them as different is how one account becomes three.
    """
    if not raw:
        return None
    d = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    d = d.split("/")[0].split("?")[0]
    if d.startswith("www."):
        d = d[4:]
    return d or None


@dataclass
class RowResult:
    row_number: int
    name: str | None
    domain: str | None
    outcome: Outcome
    detail: str = ""
    account_id: str | None = None
    #: The person this row described, on a contact-grain file.
    contact_name: str | None = None


@dataclass
class ImportReport:
    total_rows: int = 0
    rows: list[RowResult] = field(default_factory=list)
    committed: bool = False
    #: `account` or `contact`. Reported so the preview can say "400 rows →
    #: 96 companies, 400 contacts" rather than leaving somebody to infer it
    #: from a wall of outcomes.
    grain: str = "account"
    accounts_touched: int = 0
    contacts_created: int = 0
    contacts_updated: int = 0
    #: Matched accounts that were dormant and came back.
    revived: int = 0

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r.outcome] = out.get(r.outcome, 0) + 1
        return out


def parse_csv(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Kept as the CSV-only entry point. Callers handling an upload should use
    `spreadsheet.parse_upload`, which also reads `.xlsx` and names what it got
    when it can read neither."""
    from app.services.spreadsheet import parse_csv as _parse

    return _parse(content)


async def run_import(
    session: AsyncSession,
    *,
    list_id,
    rows: list[dict[str, str]],
    mapping: dict[str, str | None],
    added_by: str,
    dry_run: bool,
) -> ImportReport:
    """Resolve every row against existing accounts and the target list.

    ``dry_run`` changes only whether the work is persisted. The resolution below
    is identical either way, which is what makes the preview trustworthy.
    """
    grain = detect_grain(rows, mapping)
    report = ImportReport(
        total_rows=len(rows), committed=not dry_run, grain=grain
    )
    seen_domains: dict[str, int] = {}
    seen_names: dict[str, int] = {}
    #: On a contact file the same company appears many times, which is not a
    #: duplicate — so the account is resolved once and reused, and the dedupe
    #: key becomes the person.
    accounts_by_key: dict[str, Account] = {}
    counted_accounts: set[str] = set()
    seen_people: dict[str, int] = {}

    existing_members = set(
        (
            await session.execute(
                select(AccountListMember.account_id).where(
                    AccountListMember.list_id == list_id
                )
            )
        ).scalars()
    )

    def cell(row: dict[str, str], field_name: str) -> str | None:
        header = mapping.get(field_name)
        if not header:
            return None
        value = (row.get(header) or "").strip()
        return value or None

    for i, row in enumerate(rows, start=1):
        name = cell(row, "name")
        domain = normalise_domain(cell(row, "domain"))

        if not name and not domain:
            report.rows.append(
                RowResult(i, name, domain, "skipped_no_name", "no company name or domain")
            )
            continue

        key = domain or (name or "").lower()

        # Duplicate within the file itself, before touching the database.
        # Only on an account-grain file: five rows for one company *is* the
        # shape of a contact export, and calling those duplicates is how four
        # people get discarded under a report that reads like success.
        if grain == "account":
            seen = seen_domains if domain else seen_names
            if key in seen:
                report.rows.append(
                    RowResult(i, name, domain, "duplicate_in_file",
                              f"same company as row {seen[key]}")
                )
                continue
            seen[key] = i
        elif key in accounts_by_key or (dry_run and key in counted_accounts):
            account = accounts_by_key.get(key)
            result = await _upsert_contact(
                session, account=account, row=row, cell=cell, row_number=i,
                seen_people=seen_people, dry_run=dry_run,
            )
            report.rows.append(result)
            _count_contact(report, result)
            continue

        account = None
        if domain:
            account = (
                await session.execute(
                    select(Account).where(func.lower(Account.domain) == domain)
                )
            ).scalar_one_or_none()
        if account is None and name:
            account = (
                await session.execute(
                    select(Account).where(func.lower(Account.name) == name.lower())
                )
            ).scalar_one_or_none()

        if account is None:
            outcome: Outcome = "created"
            detail = "new account"
            if not dry_run:
                account = Account(
                    name=name or domain,
                    domain=domain,
                    industry=cell(row, "industry"),
                    hq_country=cell(row, "hq_country"),
                    hq_region=cell(row, "hq_region"),
                    # Only a URL that actually names a company. A person's
                    # profile in this column would otherwise be stamped onto
                    # the company record on every row of a contact export.
                    linkedin_url=_company_linkedin(cell(row, "linkedin_url")),
                    funding_stage=cell(row, "funding_stage"),
                )
                # Recorded rather than assigned, so the count carries the
                # date we learned it. A spreadsheet has no as-of column, so
                # the honest timestamp is when it was imported — and
                # without one there is no window a later change can be
                # measured over.
                sizing.record_headcount(
                    account, _as_int(cell(row, "employee_count"))
                )
                session.add(account)
                await session.flush()
        else:
            # **Re-importing refreshes the headcount, whichever branch the row
            # takes.** This is the cheapest growth signal available: an Apollo
            # export costs no credits, so importing a fresh one each month
            # turns `record_headcount` into a delta without a single API call.
            #
            # Recorded *before* the membership branches on purpose. The first
            # version put it under `merged` only, and a monthly re-import of
            # the same file into the same list takes `already_in_list` — which
            # is exactly the case this exists for, and it refreshed nothing.
            moved = None
            if not dry_run:
                moved = sizing.record_headcount(
                    account, _as_int(cell(row, "employee_count"))
                )

            if account.id in existing_members:
                outcome = "already_in_list"
                detail = "already a member of this list"
            else:
                outcome = "merged"
                detail = f"matched existing account {account.name!r}"

            if moved is not None and moved.outcome == "changed":
                detail += (
                    f" — headcount {moved.before} → {moved.after}"
                    + (f" over {moved.over_days} days" if moved.over_days else "")
                )
            if account.dormant_at is not None:
                # Its research, signals and contacts were kept for exactly this.
                detail = (
                    f"brought back dormant account {account.name!r} "
                    f"(dormant since {account.dormant_at.date().isoformat()}) — "
                    "its research and contacts are kept"
                )
                report.revived += 1
                if not dry_run:
                    account.dormant_at = None
                    account.dormant_reason = None

        if not dry_run and account is not None and account.id not in existing_members:
            session.add(
                AccountListMember(
                    list_id=list_id,
                    account_id=account.id,
                    added_by=added_by,
                    import_row_reason=outcome,
                )
            )

        # Counted on the key, not on the row object. A dry run never creates
        # an account, so counting rows that produced one reports zero companies
        # for a file that plainly has them — and a preview that under-reports
        # is not a preview, it is a second thing to double-check.
        if key not in counted_accounts:
            counted_accounts.add(key)
            report.accounts_touched += 1

        if account is not None:
            existing_members.add(account.id)
            accounts_by_key[key] = account

        # On a contact file the row's real subject is the person; the account
        # above was resolved on the way to them.
        if grain == "contact":
            result = await _upsert_contact(
                session, account=account, row=row, cell=cell, row_number=i,
                seen_people=seen_people, dry_run=dry_run,
            )
            result.name = name
            result.domain = domain
            report.rows.append(result)
            _count_contact(report, result)
            continue
            existing_members.add(account.id)

        report.rows.append(
            RowResult(
                i, name, domain, outcome, detail,
                str(account.id) if account is not None else None,
            )
        )

    if not dry_run:
        await session.commit()
    else:
        # Discard anything the resolution touched. A preview must leave no trace.
        await session.rollback()

    return report


def _as_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(c for c in value if c.isdigit())
    return int(digits) if digits else None


async def ensure_list(
    session: AsyncSession, *, label: str, source: str, created_by: str
) -> AccountList:
    row = AccountList(label=label, source=source, created_by=created_by)
    session.add(row)
    await session.flush()
    return row


def _company_linkedin(url: str | None) -> str | None:
    """Keep a LinkedIn URL only if it names a company."""
    return url if classify_linkedin(url) == "company" else None


def _person_linkedin(url: str | None) -> str | None:
    """Keep a LinkedIn URL only if it names a person."""
    return url if classify_linkedin(url) == "person" else None


def _count_contact(report: ImportReport, result: RowResult) -> None:
    if result.outcome == "contact_created":
        report.contacts_created += 1
    elif result.outcome == "contact_updated":
        report.contacts_updated += 1


def _full_name(cell, row: dict[str, str]) -> str | None:
    """A person's name, however the file spells it.

    Exports split it as often as they join it, and a contact row with neither
    a name nor an email is not a person — it is a company row that happened to
    arrive in a person file.
    """
    whole = cell(row, "full_name")
    if whole:
        return whole
    parts = [cell(row, "first_name"), cell(row, "last_name")]
    joined = " ".join(p for p in parts if p).strip()
    return joined or None


async def _upsert_contact(
    session: AsyncSession,
    *,
    account,
    row: dict[str, str],
    cell,
    row_number: int,
    seen_people: dict[str, int],
    dry_run: bool,
) -> RowResult:
    """Write one person against an already-resolved account.

    Everything here is marked **rep-supplied and unverified**. A CSV contact
    must not look like provider output: the enrichment waterfall skips a
    contact that already has a verified email, so mislabelling one here means
    a wrong address is never checked and the first thing that notices is a
    bounce.
    """
    name = _full_name(cell, row)
    email = (cell(row, "email") or "").lower() or None

    if not name and not email:
        return RowResult(
            row_number, None, None, "skipped_no_contact",
            "no contact name or email in this row",
        )

    # Email first: it is the identity the database enforces uniqueness on.
    key = email or f"{account.id if account else ''}:{(name or '').lower()}"
    if key in seen_people:
        return RowResult(
            row_number, None, None, "duplicate_contact_in_file",
            f"same person as row {seen_people[key]}", contact_name=name,
        )
    seen_people[key] = row_number

    if dry_run or account is None:
        return RowResult(
            row_number, None, None, "contact_created",
            "new contact" if account is not None else "new contact (account pending)",
            contact_name=name,
        )

    existing = None
    if email:
        existing = (
            await session.execute(
                select(Contact).where(
                    Contact.account_id == account.id,
                    func.lower(Contact.email) == email,
                )
            )
        ).scalar_one_or_none()
    if existing is None and name:
        existing = (
            await session.execute(
                select(Contact).where(
                    Contact.account_id == account.id,
                    func.lower(Contact.full_name) == name.lower(),
                )
            )
        ).scalar_one_or_none()

    title = cell(row, "title")
    linkedin = _person_linkedin(cell(row, "contact_linkedin_url"))
    phone = cell(row, "phone")

    if existing is None:
        session.add(
            Contact(
                account_id=account.id,
                full_name=name or email,
                title=title,
                email=email,
                phone=phone,
                linkedin_url=linkedin,
                # Rep-supplied, and unproven until a provider says otherwise.
                email_status="unverified" if email else "unverified",
                email_provider="manual" if email else None,
                phone_status="unverified",
                phone_provider="manual" if phone else None,
            )
        )
        await session.flush()
        return RowResult(
            row_number, None, None, "contact_created", "new contact",
            contact_name=name,
        )

    # Fill gaps only. Overwriting a verified email with a spreadsheet cell is
    # how a checked address becomes an unchecked one.
    filled: list[str] = []
    if title and not existing.title:
        existing.title = title
        filled.append("title")
    if linkedin and not existing.linkedin_url:
        existing.linkedin_url = linkedin
        filled.append("linkedin")
    if phone and not existing.phone:
        existing.phone = phone
        existing.phone_provider = "manual"
        filled.append("phone")
    if email and not existing.email:
        existing.email = email
        existing.email_status = "unverified"
        existing.email_provider = "manual"
        filled.append("email")

    return RowResult(
        row_number, None, None, "contact_updated",
        f"filled {', '.join(filled)}" if filled else "already on file, nothing new",
        contact_name=name,
    )
