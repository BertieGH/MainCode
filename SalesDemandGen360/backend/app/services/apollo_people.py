"""Apollo's people search, person reveal and organisation record.

Three routes, read off Apollo's reference and confirmed against the live key:

* **`POST /mixed_people/api_search`** — who works at a domain, filtered by
  title and seniority. **Costs no credits.** It reveals nothing: a first name,
  an obfuscated surname (`Pe***d`), a title, and flags for whether Apollo holds
  an email, a location and a direct phone. The organisation in a result carries
  a name and flags only — no domain and no id — so a result cannot be mapped
  back to one of several domains, and the search is made **one domain at a
  time**.
* **`POST /people/bulk_match`** — the reveal, by Apollo person id, ten per
  call. **One credit per person Apollo has data for.** Personal emails and
  phone numbers are never asked for: a personal address is the wrong channel
  for cold B2B outreach, and Apollo delivers phones only to a webhook this
  build does not have.
* **`POST /organizations/enrich?domain=`** — the company record: country,
  state, LinkedIn page, primary domain. One credit.

The key travels in the `x-api-key` header, is never logged, and never reaches
a prompt — `docs/01` invariant 9.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.enrichment_clients import APOLLO_BASE, _client
from app.services.providers import ProviderError

log = logging.getLogger(__name__)

SEARCH_PATH = "/mixed_people/api_search"
REVEAL_PATH = "/people/bulk_match"
ORG_PATH = "/organizations/enrich"
#: Saved contacts in the Apollo account. Both free.
CONTACTS_BULK_PATH = "/contacts/bulk_create"
CONTACTS_SEARCH_PATH = "/contacts/search"
#: `contacts/bulk_create` takes at most a hundred per call.
SAVE_BATCH = 100
#: The label on every contact this app saves, so the Apollo team can find them.
LABEL = "Gen360"

#: `people/bulk_match` takes at most ten people per call.
REVEAL_BATCH = 10
#: Apollo's page ceiling.
MAX_PER_PAGE = 100

#: Apollo's seniority vocabulary for a buying role, used only when a persona
#: names no titles. With titles, the titles decide — adding a seniority filter
#: on top is an AND, and an "IT head" at a forty-person company is as often
#: filed `manager` as `head`.
ROLE_SENIORITIES: dict[str, tuple[str, ...]] = {
    "economic_buyer": ("owner", "founder", "c_suite", "partner"),
    "technical_buyer": ("c_suite", "vp", "head", "director"),
    "champion": ("vp", "head", "director", "manager"),
    "influencer": ("head", "director", "manager", "senior"),
}


class OutOfCredits(ProviderError):
    """Apollo refused for lack of credits — with whatever was revealed before it did."""

    def __init__(self, message: str, *, revealed: dict | None = None, credits: int = 0):
        super().__init__(message)
        self.revealed = revealed or {}
        self.credits = credits


@dataclass(frozen=True)
class Found:
    """One person the search returned. Nothing here identifies them fully."""

    apollo_id: str
    first_name: str | None
    last_name_hint: str | None
    title: str | None
    has_email: bool
    has_location: bool
    has_direct_phone: bool
    refreshed_at: datetime | None


@dataclass(frozen=True)
class SavedContact:
    """A contact saved in the Apollo account. Reading one costs nothing."""

    id: str
    person_id: str | None
    first_name: str | None
    last_name: str | None
    name: str | None
    email: str | None
    email_status: str | None
    linkedin_url: str | None
    title: str | None
    organization_name: str | None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_search(payload: Any) -> list[Found]:
    """The people in a search response, in Apollo's order."""
    if not isinstance(payload, dict):
        return []
    people = payload.get("people")
    if not isinstance(people, list):
        return []
    found: list[Found] = []
    for person in people:
        if not isinstance(person, dict) or not _text(person.get("id")):
            continue
        found.append(
            Found(
                apollo_id=person["id"].strip(),
                first_name=_text(person.get("first_name")),
                last_name_hint=_text(person.get("last_name_obfuscated")),
                title=_text(person.get("title")),
                has_email=bool(person.get("has_email")),
                has_location=bool(
                    person.get("has_country") or person.get("has_state") or person.get("has_city")
                ),
                has_direct_phone=person.get("has_direct_phone") in (True, "Yes", "yes"),
                refreshed_at=_when(person.get("last_refreshed_at")),
            )
        )
    return found


def parse_reveal(asked: list[str], payload: Any) -> tuple[dict[str, dict], int | None]:
    """Revealed people by the Apollo id asked about, and the credits Apollo says it used.

    `matches` lines up with the ids in the request, with `null` for a person
    Apollo had nothing on. Read by position, and checked against the returned
    id where there is one — a match filed under the wrong id would reveal one
    person's address onto another's suggestion.
    """
    if not isinstance(payload, dict):
        return {}, None
    matches = payload.get("matches")
    out: dict[str, dict] = {}
    if isinstance(matches, list):
        for index, match in enumerate(matches):
            if not isinstance(match, dict):
                continue
            returned = _text(match.get("id"))
            if returned in asked:
                out[returned] = match
            elif returned is None and index < len(asked):
                out[asked[index]] = match
    credits = payload.get("credits_consumed")
    return out, credits if isinstance(credits, int) else None


def parse_saved(item: Any) -> SavedContact | None:
    """One contact from `contacts/search` or `contacts/bulk_create`."""
    if not isinstance(item, dict) or not _text(item.get("id")):
        return None
    org = item.get("organization") if isinstance(item.get("organization"), dict) else {}
    return SavedContact(
        id=item["id"].strip(),
        person_id=_text(item.get("person_id")),
        first_name=_text(item.get("first_name")),
        last_name=_text(item.get("last_name")),
        name=_text(item.get("name")),
        email=_text(item.get("email")),
        email_status=_text(item.get("email_status")),
        linkedin_url=_text(item.get("linkedin_url")),
        title=_text(item.get("title")),
        organization_name=_text(item.get("organization_name")) or _text(org.get("name")),
    )


class ApolloPeople:
    def __init__(self, api_key: str, base_url: str = APOLLO_BASE, *, client_factory=_client):
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._client = client_factory

    async def search(
        self,
        *,
        domain: str,
        titles: tuple[str, ...] = (),
        seniorities: tuple[str, ...] = (),
        per_page: int = 25,
    ) -> list[Found]:
        """People at one domain in these titles or seniorities. Free."""
        body: dict[str, Any] = {
            "q_organization_domains_list": [domain],
            "page": 1,
            "per_page": max(1, min(MAX_PER_PAGE, per_page)),
        }
        if titles:
            body["person_titles"] = list(titles)
            body["include_similar_titles"] = True
        if seniorities:
            body["person_seniorities"] = list(seniorities)
        return parse_search(await self._post(SEARCH_PATH, body=body))

    async def reveal(self, ids: list[str]) -> tuple[dict[str, dict], int]:
        """Full records for these Apollo people. One credit per person found.

        Apollo refuses a whole batch when the account holds fewer credits than
        the batch asks for — live, ten people against seven credits revealed
        nobody. So a batch refused for credits is retried one person at a time,
        and the credits that are left are spent on someone. The first single
        refusal raises `OutOfCredits` carrying everyone revealed before it.
        """
        log.info("apollo.reveal people=%d", len(ids))
        revealed: dict[str, dict] = {}
        credits = 0
        for start in range(0, len(ids), REVEAL_BATCH):
            batch = ids[start:start + REVEAL_BATCH]
            try:
                found, used = await self._reveal_batch(batch)
            except OutOfCredits as exc:
                if len(batch) == 1:
                    raise OutOfCredits(str(exc), revealed=revealed, credits=credits) from exc
                for one in batch:
                    try:
                        found, used = await self._reveal_batch([one])
                    except OutOfCredits as inner:
                        raise OutOfCredits(str(inner), revealed=revealed, credits=credits) from inner
                    revealed.update(found)
                    credits += used
                continue
            revealed.update(found)
            credits += used
        return revealed, credits

    async def _reveal_batch(self, batch: list[str]) -> tuple[dict[str, dict], int]:
        payload = await self._post(
            REVEAL_PATH,
            body={
                "details": [{"id": i} for i in batch],
                "reveal_personal_emails": False,
                "reveal_phone_number": False,
            },
        )
        found, used = parse_reveal(batch, payload)
        return found, used if used is not None else len(found)

    async def save_contacts(self, contacts: list[dict]) -> list[SavedContact]:
        """Save people as contacts in the Apollo account. Free, de-duplicated, labelled.

        `run_dedupe` makes Apollo return a person already saved instead of
        creating them twice; both the created and the existing come back.
        """
        saved: list[SavedContact] = []
        for start in range(0, len(contacts), SAVE_BATCH):
            payload = await self._post(
                CONTACTS_BULK_PATH,
                body={
                    "contacts": contacts[start:start + SAVE_BATCH],
                    "run_dedupe": True,
                    "append_label_names": [LABEL],
                },
            )
            if isinstance(payload, dict):
                for key in ("created_contacts", "existing_contacts"):
                    for item in payload.get(key) or []:
                        parsed = parse_saved(item)
                        if parsed is not None:
                            saved.append(parsed)
        return saved

    async def find_saved(self, *, keywords: str, per_page: int = 25) -> list[SavedContact]:
        """Saved contacts matching a name, company or email. Free."""
        payload = await self._post(
            CONTACTS_SEARCH_PATH,
            body={"q_keywords": keywords, "page": 1, "per_page": max(1, min(MAX_PER_PAGE, per_page))},
        )
        if not isinstance(payload, dict):
            return []
        return [p for p in (parse_saved(c) for c in payload.get("contacts") or []) if p is not None]

    async def organization(self, domain: str) -> dict | None:
        """Apollo's record for the company at this domain. One credit."""
        payload = await self._post(ORG_PATH, params={"domain": domain})
        org = (payload or {}).get("organization") if isinstance(payload, dict) else None
        return org if isinstance(org, dict) and org else None

    async def _post(
        self, path: str, *, body: dict[str, Any] | None = None, params: dict | None = None
    ) -> Any:
        async with self._client() as client:
            try:
                response = await client.post(
                    f"{self._base}{path}",
                    headers={
                        "x-api-key": self._key,
                        "accept": "application/json",
                        "content-type": "application/json",
                    },
                    json=body,
                    params=params,
                )
            except Exception as exc:  # noqa: BLE001 — one error type upward
                raise ProviderError(f"could not reach Apollo: {type(exc).__name__}") from exc

        if response.status_code in (401, 403):
            # Never the body: a rejection can quote the key that was sent.
            raise ProviderError("Apollo rejected this key, or this plan cannot use " + path)
        if response.status_code == 429:
            raise ProviderError("Apollo rate limit reached — try again in a few minutes")
        if response.status_code in (404, 422) and path == ORG_PATH:
            return None
        if response.status_code >= 400:
            said = _apollo_message(response, self._key)
            if said and "insufficient credits" in said.lower():
                # Live: a reveal of 66 accepted people answered 422 with this,
                # and the screen said only "HTTP 422 for /people/bulk_match".
                raise OutOfCredits(
                    "Apollo has no credits left on this plan, so nothing was revealed or charged. "
                    "Add credits or upgrade the plan in Apollo, then reveal again."
                )
            raise ProviderError(
                f"Apollo returned HTTP {response.status_code} for {path}"
                + (f": {said}" if said else "")
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("Apollo returned a non-JSON response") from exc


_MARKUP = re.compile(r"<[^>]+>")


def _apollo_message(response, key: str | None) -> str | None:
    """Apollo's own reason for a refusal, as plain words.

    Only the `error` / `message` field, markup stripped, trimmed, and with the
    key removed should Apollo ever echo it. Never used for 401/403, which are
    answered before this is reached.
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("error") or payload.get("message")
    if not isinstance(raw, str):
        return None
    text = " ".join(html.unescape(_MARKUP.sub("", raw)).split())
    if key:
        text = text.replace(key, "***")
    return text[:200] or None


async def from_credentials(session: AsyncSession) -> ApolloPeople | None:
    """A client built from the stored Apollo key, or None when there is none."""
    from app.models.config import IntegrationCredential
    from app.services import crypto

    row = (
        await session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.provider == "apollo",
                IntegrationCredential.credential_type == "api_key",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        key = crypto.decrypt(row.value_encrypted).reveal()
    except crypto.CredentialError:
        log.warning("apollo_people.undecryptable")
        return None
    return ApolloPeople(key)
