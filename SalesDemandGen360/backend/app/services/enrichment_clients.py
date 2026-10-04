"""Concrete enrichment providers, behind the `ContactProvider` protocol.

What is verified here and what is not, stated up front because the difference
decides how a failure should be read. **Apollo and ContactOut are not in the
same state**, and the two clients below are written differently because of it.

Apollo, confirmed against a live key:

* `POST /api/v1/people/match` with an `x-api-key` header answers 200 and
  returns `{"person": {...}}` — `email`, `email_status`, `title`, `seniority`,
  `linkedin_url`, `departments`, and a nested `organization`. Those field names
  were read off a real response, so that parser reads them directly rather than
  hunting through candidate paths.
* **It has no way of saying "no".** An invented name at a real domain returns
  200 and a full `person` object with a new `id` and the organisation attached.
  `APOLLO_SIGNS_OF_LIFE` is how a match is told from an echo, and without it
  every contact enriches successfully into nothing.
* `GET /api/v1/auth/health` returns `is_logged_in`, which is what the probe
  checks. Apollo answers 200 to a junk key, so the status code alone says
  nothing about whether the key is real.

ContactOut, confirmed only as far as the routes:

* **The routes are confirmed.** Probed live with a deliberately invalid key:
  `GET /v1/people/linkedin` and `POST /v1/people/enrich` answer 401, so they
  exist and require auth. `/v1/people/email`, `/v1/email/decode` and
  `/v1/verify/email` answer 404 — all three were plausible guesses, and all
  three are wrong. The auth header is confirmed the same way.
* **The response shape is not.** Reading a body needs a working key, and there
  was none when this was written.

That second gap is the dangerous one. A wrong route fails loudly with a 404; a
wrong *field name* succeeds and returns nothing, or worse, returns the wrong
address — and a wrong address is a bounce against a sending domain. So the
parser below does not assume one shape. It looks through a small set of
candidate paths, and when none of them match it logs the keys the provider
actually sent. The first real call therefore reports what the shape is instead
of failing silently, and the mapping is corrected from evidence.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any

from app.services.providers import ContactRecord, Provider, ProviderError

log = logging.getLogger(__name__)

CONTACTOUT_BASE = "https://api.contactout.com/v1"
APOLLO_BASE = "https://api.apollo.io/api/v1"

#: Enrichment is slower than an auth check and worth waiting for, but not
#: worth stalling a batch of two hundred contacts on.
TIMEOUT_SECONDS = 25.0


def _client(timeout: float = TIMEOUT_SECONDS):
    """An httpx client trusting the OS certificate store.

    Same reason as `probes.py` and `gemini.py`: certifi does not contain a
    corporate proxy's root, and the resulting handshake failure reads as "the
    provider is down".
    """
    import httpx

    try:
        import truststore

        verify: Any = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 — fall back to the bundled roots
        verify = True
    return httpx.AsyncClient(timeout=timeout, verify=verify)


#: Where an email might live in a response body, best first. Several rather
#: than one because the shape is unconfirmed — see the module docstring.
EMAIL_PATHS: tuple[tuple[str, ...], ...] = (
    ("profile", "work_email"),
    ("profile", "email"),
    ("work_email",),
    ("email",),
    ("data", "work_email"),
    ("data", "email"),
)
PHONE_PATHS: tuple[tuple[str, ...], ...] = (
    ("profile", "phone"),
    ("phone",),
    ("data", "phone"),
)
TITLE_PATHS: tuple[tuple[str, ...], ...] = (
    ("profile", "title"),
    ("profile", "headline"),
    ("title",),
)


def _dig(payload: Any, path: tuple[str, ...]) -> Any:
    node = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _first_value(payload: Any, paths: tuple[tuple[str, ...], ...]) -> str | None:
    """The first path that yields something usable.

    Lists are flattened to their first entry: these APIs return `emails` as an
    array as often as `email` as a string, and both mean one address here.
    """
    for path in paths:
        value = _dig(payload, path)
        if isinstance(value, list):
            value = next((v for v in value if isinstance(v, str) and v.strip()), None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class ContactOutProvider:
    """ContactOut, primary in the default waterfall.

    Two routes, chosen by what we already know about the person. A LinkedIn URL
    is a far stronger key than a name and a domain — it identifies one person
    rather than everyone at a company who shares a name — so it is used when
    the contact has one, which after a CSV import is most of them.
    """

    name = Provider.CONTACTOUT
    #: Phone is ContactOut's product as much as email is, which is why it sits
    #: in the waterfall at all once phone becomes a required field.
    supplies = frozenset({"email", "phone", "title"})

    def __init__(self, api_key: str, base_url: str = CONTACTOUT_BASE):
        self._key = api_key
        self._base = base_url.rstrip("/")

    async def enrich(
        self, *, full_name: str, company_domain: str | None, linkedin_url: str | None
    ) -> ContactRecord | None:
        if linkedin_url:
            payload = await self._get(
                "/people/linkedin", params={"profile": linkedin_url}
            )
        elif company_domain:
            payload = await self._post(
                "/people/enrich", body={"name": full_name, "domain": company_domain}
            )
        else:
            # A bare name identifies nobody, and asking anyway spends a metered
            # call to be told so.
            return None

        return self._to_record(full_name, payload)

    # --- transport ---

    def _headers(self) -> dict[str, str]:
        # Confirmed by probe: the bare key in `authorization`, not a bearer
        # token. A bearer prefix returns 401 for a perfectly good key.
        return {
            "authorization": self._key,
            "accept": "application/json",
            "content-type": "application/json",
        }

    async def _get(self, path: str, *, params: dict[str, str]) -> Any:
        async with _client() as client:
            try:
                response = await client.get(
                    f"{self._base}{path}", headers=self._headers(), params=params
                )
            except Exception as exc:  # noqa: BLE001 — one error type upward
                raise ProviderError(f"could not reach ContactOut: {type(exc).__name__}") from exc
        return self._body(response, path)

    async def _post(self, path: str, *, body: dict[str, Any]) -> Any:
        async with _client() as client:
            try:
                response = await client.post(
                    f"{self._base}{path}", headers=self._headers(), json=body
                )
            except Exception as exc:  # noqa: BLE001 — one error type upward
                raise ProviderError(f"could not reach ContactOut: {type(exc).__name__}") from exc
        return self._body(response, path)

    def _body(self, response: Any, path: str) -> Any:
        """Turn a response into a payload, or into the right kind of failure.

        A 404 on an *enrichment* route means this person is not in their
        database — a finding, not a fault. Raising there would mark the whole
        pass unavailable and stop the waterfall trying the next provider for
        somebody it might actually have.
        """
        if response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            # Never the body: a rejection can quote the key that was sent.
            raise ProviderError("ContactOut rejected this key")
        if response.status_code == 429:
            raise ProviderError("ContactOut rate limit reached")
        if response.status_code >= 400:
            raise ProviderError(f"ContactOut returned HTTP {response.status_code} for {path}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("ContactOut returned a non-JSON response") from exc

    # --- reading the body ---

    def _to_record(self, full_name: str, payload: Any) -> ContactRecord | None:
        if not payload:
            return None

        email = _first_value(payload, EMAIL_PATHS)
        if not email:
            # The shape is unconfirmed, so an unrecognised body is reported
            # rather than silently read as "nobody found". Without this the
            # first sign of a wrong mapping is a list that enriches to nothing.
            log.warning(
                "contactout.unrecognised_response keys=%s — no email found at any known "
                "path; the response mapping in enrichment_clients.py needs updating",
                sorted(payload)[:12] if isinstance(payload, dict) else type(payload).__name__,
            )
            return None

        return ContactRecord(
            full_name=full_name,
            email=email,
            phone=_first_value(payload, PHONE_PATHS),
            title=_first_value(payload, TITLE_PATHS),
            # ContactOut's product is verified addresses, and no grading field
            # has been observed in a live response. Revisit the moment one is:
            # this is the assumption that costs a bounce if it is wrong.
            email_status="verified",
            sources={"email": Provider.CONTACTOUT.value},
        )


#: Apollo's own verdict on an address, mapped to ours.
#:
#: `guessed` is the one that matters. Apollo pattern-matches a company's known
#: address format onto a name and hands back the result next to addresses it
#: has actually confirmed. It is often right, and when it is wrong the cost
#: lands on the sending domain's reputation rather than on Apollo. So a guess
#: becomes `risky`, does not satisfy the verification gate, and stays visible
#: for a rep to decide about.
APOLLO_EMAIL_STATUS: dict[str, str] = {
    "verified": "verified",
    "guessed": "risky",
    "likely_to_engage": "risky",
    "unavailable": "invalid",
    "bounced": "invalid",
    "pending_manual_fulfillment": "unverified",
}

#: Fields Apollo can only fill in from its own data. One of them present means
#: it recognised the person; all of them empty means it did not.
#:
#: This exists because `people/match` does not answer "no". Asked about an
#: invented name at a real domain it returns HTTP 200 and a complete `person`
#: object — 27 fields, a freshly minted `id`, and the organisation resolved
#: from the domain — identical in shape to a real hit. Reading a present
#: `person` as a match therefore made every contact enrich successfully with
#: nothing, and a list of invented names would have come back looking clean.
#:
#: Confirmed from both sides against a live key: `Nobody Whoisnotreal` at a
#: real domain comes back hollow, while `Satya Nadella` at microsoft.com comes
#: back with title, seniority and a verified address. The organisation block is
#: *not* a discriminator — the hollow record carried one too.
APOLLO_SIGNS_OF_LIFE: tuple[str, ...] = (
    "title",
    "seniority",
    "email",
    "linkedin_url",
    "photo_url",
    "headline",
    "city",
)


def _apollo_recognised(person: dict[str, Any]) -> bool:
    """Did Apollo know this person, or is it echoing the question back?"""
    return any(person.get(f) for f in APOLLO_SIGNS_OF_LIFE)


#: What Apollo puts in the `email` field when it holds an address this plan has
#: not paid to see. It is a literal string, not an address — written to contact
#: rows unchecked it would produce a list of people who all share one fake
#: address, and the import would look like it had worked.
APOLLO_LOCKED_EMAIL = "email_not_unlocked@domain.com"


def _split_name(full_name: str) -> tuple[str, str]:
    """Apollo matches on first and last name; a contact holds one string.

    Split at the last space, so "Maria del Carmen Ruiz" yields "Ruiz" as the
    surname — what a surname index expects — and the remainder goes in front
    rather than being discarded.
    """
    parts = full_name.strip().split()
    if len(parts) < 2:
        return (full_name.strip(), "")
    return (" ".join(parts[:-1]), parts[-1])


class ApolloProvider:
    """Apollo, primary in the default waterfall.

    One route — `people/match` — given whatever identifiers are on hand. A
    LinkedIn URL is sent when the contact has one, for the reason ContactOut
    gets one too: it identifies a person, where a name and a domain identify
    everyone at that company who shares the name.
    """

    name = Provider.APOLLO
    #: No phone. Confirmed live: `reveal_phone_number` returns HTTP 400
    #: (`SEARCH.VALIDATION.WEBHOOK_URL_REQUIRED`) because Apollo delivers phone
    #: results asynchronously to a webhook, and this build has no receiver. The
    #: only number in a plain response is `organization.phone` — the company
    #: switchboard, identical for every contact at the account, and emphatically
    #: not the person's number. Declaring the gap keeps Apollo from being billed
    #: for a call that cannot answer.
    supplies = frozenset({"email", "title", "seniority", "linkedin_url"})

    def __init__(
        self,
        api_key: str,
        base_url: str = APOLLO_BASE,
        *,
        reveal_personal_emails: bool = False,
    ):
        self._key = api_key
        self._base = base_url.rstrip("/")
        # Off by default, deliberately. Revealing spends a credit per call
        # whether or not the address turns out to be usable, and a personal
        # address is the wrong channel for cold B2B outreach in most of the
        # jurisdictions this will run in. A caller who wants it can ask for it.
        self._reveal = reveal_personal_emails

    async def enrich(
        self, *, full_name: str, company_domain: str | None, linkedin_url: str | None
    ) -> ContactRecord | None:
        if not linkedin_url and not company_domain:
            # A bare name matches the wrong person as readily as the right one,
            # and Apollo returns that wrong person without hedging. Not asking
            # is the safe answer, and it is also the free one.
            return None

        first, last = _split_name(full_name)
        body: dict[str, Any] = {"reveal_personal_emails": self._reveal}
        if first:
            body["first_name"] = first
        if last:
            body["last_name"] = last
        if company_domain:
            body["domain"] = company_domain
        if linkedin_url:
            body["linkedin_url"] = linkedin_url

        payload = await self._post("/people/match", body=body)
        return self._to_record(full_name, payload)

    # --- transport ---

    def _headers(self) -> dict[str, str]:
        # Confirmed live: `x-api-key`, not a bearer token and not a query
        # parameter. Apollo's older documentation shows `api_key` in the body;
        # that form is rejected.
        return {
            "x-api-key": self._key,
            "accept": "application/json",
            "content-type": "application/json",
        }

    async def _post(self, path: str, *, body: dict[str, Any]) -> Any:
        async with _client() as client:
            try:
                response = await client.post(
                    f"{self._base}{path}", headers=self._headers(), json=body
                )
            except Exception as exc:  # noqa: BLE001 — one error type upward
                raise ProviderError(
                    f"could not reach Apollo: {type(exc).__name__}"
                ) from exc

        if response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            # Never the body: a rejection can quote the key that was sent.
            raise ProviderError("Apollo rejected this key")
        if response.status_code == 422:
            # Apollo's way of saying the identifiers were not enough to match
            # on. A finding about this contact, not a fault in the integration,
            # so the waterfall moves on instead of marking itself unavailable.
            return None
        if response.status_code == 429:
            raise ProviderError("Apollo rate limit reached")
        if response.status_code >= 400:
            raise ProviderError(
                f"Apollo returned HTTP {response.status_code} for {path}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("Apollo returned a non-JSON response") from exc

    # --- reading the body ---

    def _to_record(self, full_name: str, payload: Any) -> ContactRecord | None:
        if not isinstance(payload, dict):
            return None
        person = payload.get("person")
        if not isinstance(person, dict):
            return None

        if not _apollo_recognised(person):
            # An echo, not a match. See `APOLLO_SIGNS_OF_LIFE`: Apollo mints a
            # person object for a name it has never seen, so the presence of
            # `person` proves nothing. Returning None here is what lets the
            # waterfall fall through to the next provider instead of recording
            # a contact whose every field came from our own request.
            log.info(
                "apollo.no_match — a person object came back with nothing Apollo "
                "could only know; treated as not found"
            )
            return None

        email = person.get("email")
        if not isinstance(email, str) or not email.strip():
            email = None
        elif email.strip().lower() == APOLLO_LOCKED_EMAIL:
            log.info(
                "apollo.email_locked — matched a person whose address is not "
                "unlocked on this plan; the contact stays unverified"
            )
            email = None

        raw_status = person.get("email_status")
        status = APOLLO_EMAIL_STATUS.get(raw_status or "", "unverified")
        if raw_status and raw_status not in APOLLO_EMAIL_STATUS:
            # An unmapped grade falls to `unverified` — the cautious side — and
            # says so, rather than being quietly read as good.
            log.warning(
                "apollo.unmapped_email_status=%r — treated as unverified; add it "
                "to APOLLO_EMAIL_STATUS in enrichment_clients.py",
                raw_status,
            )

        if email is None:
            status = "unverified"

        return ContactRecord(
            full_name=person.get("name") or full_name,
            email=email,
            email_status=status,
            phone=_apollo_phone(person),
            title=person.get("title") or None,
            linkedin_url=person.get("linkedin_url") or None,
            seniority=person.get("seniority") or None,
            provider_record_id=person.get("id") or None,
            sources={"email": Provider.APOLLO.value},
            organization_domain=_organization(person).get("domain"),
            organization_linkedin_url=_organization(person).get("linkedin_url"),
        )


def _organization(person: dict[str, Any]) -> dict[str, str | None]:
    """The organisation Apollo places a recognised person at.

    Read only for a person `_apollo_recognised` accepted: a hollow record also
    carries an organisation, resolved from the domain we sent, so there it would
    only be our own question answered back.
    """
    org = person.get("organization")
    if not isinstance(org, dict):
        return {"domain": None, "linkedin_url": None}
    return {
        "domain": org.get("primary_domain") or org.get("website_url") or None,
        "linkedin_url": org.get("linkedin_url") or None,
    }


def _apollo_phone(person: dict[str, Any]) -> str | None:
    """The first usable number out of Apollo's `phone_numbers`.

    Never seen populated in a live response — see `ApolloProvider.supplies` —
    so both the documented list-of-objects shape and a plain string are
    accepted rather than either being assumed.

    Deliberately reads only `person`. The response does carry a number, at
    `organization.phone`, and it is the company switchboard: reaching for it
    here would give every contact at an account the same main line and label it
    that person's direct number.
    """
    numbers = person.get("phone_numbers")
    if isinstance(numbers, list):
        for entry in numbers:
            if isinstance(entry, str) and entry.strip():
                return entry.strip()
            if isinstance(entry, dict):
                for key in ("sanitized_number", "raw_number", "number"):
                    value = entry.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    direct = person.get("phone")
    return direct.strip() if isinstance(direct, str) and direct.strip() else None


def build(provider: str, api_key: str) -> ContactProviderLike | None:
    """The client for a provider, or None where none is written yet."""
    if provider == "contactout":
        return ContactOutProvider(api_key)
    if provider == "apollo":
        return ApolloProvider(api_key)
    return None


#: Structural alias — `ContactProvider` is a Protocol, and naming it here keeps
#: the return type readable without importing it at runtime.
ContactProviderLike = ContactOutProvider | ApolloProvider
