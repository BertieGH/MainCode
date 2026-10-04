"""Keeping what we paid Apollo for inside the Apollo account, so it is never paid for twice.

Apollo's rule, from its own documentation: a person enriched through the API
and never saved as a contact is a new request next time, and charged again; a
person saved as a contact "becomes permanently accessible to your
organization". Both contact endpoints are free.

* **Save** — everyone revealed or enriched is saved with
  `contacts/bulk_create`, de-duplicated by Apollo (`run_dedupe`) and labelled
  `Gen360` so the team can find them. Saving creates contacts every member of
  the Apollo account can see; that was agreed before this was built.
* **Look before paying** — the account's saved contacts are searched first:
  once per company before a reveal (matched on Apollo's person id), and by
  email before the 90-day re-check of a verified address.

A failure here never undoes a reveal that was already paid for: it is reported,
and the person is simply not marked as saved.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import UTC, datetime

from app.services.apollo_people import SavedContact
from app.services.enrichment_clients import _split_name
from app.services.providers import ProviderError

log = logging.getLogger(__name__)


def _fold(text: str | None) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().casefold().strip()


def payload(contact, account) -> dict:
    """The contact as Apollo's `contacts/bulk_create` takes one. Empty fields left out."""
    first, last = _split_name(contact.full_name or "")
    body = {
        "first_name": first,
        "last_name": last,
        "title": contact.title,
        "email": contact.email,
        "organization_name": getattr(account, "name", None),
        "linkedin_url": contact.linkedin_url,
    }
    return {k: v for k, v in body.items() if v}


def _name_key(first, last, organization) -> tuple[str, str, str]:
    return (_fold(first), _fold(last), _fold(organization))


async def save(session, people, contacts, *, now: datetime | None = None) -> tuple[int, str | None]:
    """Save contacts not yet saved. Returns how many were, and Apollo's refusal if any."""
    from app.models.account import Account

    now = now or datetime.now(UTC)
    todo = [c for c in contacts if not c.apollo_contact_id and (c.email or c.linkedin_url)]
    if not todo:
        return 0, None

    accounts: dict = {}
    for contact in todo:
        if contact.account_id not in accounts:
            accounts[contact.account_id] = await session.get(Account, contact.account_id)
    bodies = [payload(c, accounts[c.account_id]) for c in todo]

    try:
        saved = await people.save_contacts(bodies)
    except ProviderError as exc:
        log.warning("apollo_contacts.save_failed count=%d err=%s", len(bodies), exc)
        return 0, str(exc)

    by_email = {_fold(s.email): s for s in saved if s.email}
    by_name = {_name_key(s.first_name, s.last_name, s.organization_name): s for s in saved}
    count = 0
    for contact, body in zip(todo, bodies):
        match = by_email.get(_fold(contact.email)) if contact.email else None
        match = match or by_name.get(
            _name_key(body.get("first_name"), body.get("last_name"), body.get("organization_name"))
        )
        if match is not None and match.id:
            contact.apollo_contact_id = match.id
            contact.apollo_saved_at = now
            count += 1
    return count, None


async def saved_by_person(people, organization_name: str) -> dict[str, SavedContact]:
    """The account's saved Apollo contacts at one company, by Apollo person id. Free."""
    if not (organization_name or "").strip():
        return {}
    found = await people.find_saved(keywords=organization_name, per_page=100)
    return {s.person_id: s for s in found if s.person_id}


def as_person(saved: SavedContact) -> dict:
    """A saved contact in the shape a reveal returns, for `apply_person`."""
    return {
        "id": saved.person_id,
        "name": saved.name or " ".join(p for p in (saved.first_name, saved.last_name) if p),
        "first_name": saved.first_name,
        "last_name": saved.last_name,
        "title": saved.title,
        "email": saved.email,
        "email_status": saved.email_status,
        "linkedin_url": saved.linkedin_url,
        "organization": {},
    }


async def reconfirm_stale(contacts, people, *, now: datetime | None = None) -> set:
    """Re-confirm stale verified addresses from saved Apollo contacts, for free.

    A saved contact Apollo still grades `verified` settles the re-check: the
    address is stamped as verified now and no credit is spent. Anything else —
    not saved, no longer verified — is left for the paid re-check. Stops at the
    first refusal from Apollo rather than repeating it for every contact.
    """
    now = now or datetime.now(UTC)
    done: set = set()
    for contact in contacts:
        if not contact.email:
            continue
        try:
            found = await people.find_saved(keywords=contact.email, per_page=5)
        except ProviderError as exc:
            log.warning("apollo_contacts.search_failed err=%s", exc)
            break
        match = next((s for s in found if _fold(s.email) == _fold(contact.email)), None)
        if match is None or (match.email_status or "").casefold() != "verified":
            continue
        contact.email_verified_at = now
        if not contact.apollo_contact_id and match.id:
            contact.apollo_contact_id = match.id
            contact.apollo_saved_at = contact.apollo_saved_at or now
        done.add(contact.id)
    return done
