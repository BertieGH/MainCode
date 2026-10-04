"""The contact-enrichment waterfall: Apollo primary, ContactOut fallback.

A waterfall rather than a race, because these are metered per call. Asking both
and keeping the better answer doubles the bill on every contact that Apollo
already resolved — which is most of them.

The fallback trigger is **a missing field, not an error**. Apollo returning a
person with no email is a successful call with an unusable result; treating
only exceptions as failure would leave the waterfall permanently dry.

A provider also declares **what it can supply at all**, and is not asked for
anything else. Apollo cannot return a personal phone number synchronously —
`reveal_phone_number` is a 400 without a `webhook_url`, because the result is
delivered asynchronously — so with `phone` among the required fields it would
otherwise be called for every contact whose email was already resolved, billed
every time, and never able to answer.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


class Provider(StrEnum):
    APOLLO = "apollo"
    CONTACTOUT = "contactout"


@dataclass(frozen=True)
class ContactRecord:
    full_name: str
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    seniority: str | None = None
    #: The provider's own verdict on the address, in our vocabulary:
    #: `verified`, `risky`, `invalid` or `unverified`.
    #:
    #: Carried rather than assumed. Apollo returns *guessed* addresses
    #: alongside verified ones and grades them in `email_status`; storing a
    #: guess as verified is how a sending domain gets burned, and the bounce
    #: is the first thing that would notice.
    email_status: str = "verified"
    #: The same idea for the number, and the honest default is `unverified`:
    #: neither provider grades a phone the way Apollo grades an address, so a
    #: number that arrives is a number somebody published, not one anybody
    #: dialled. `verified` here would be a claim nothing supports.
    phone_status: str = "unverified"
    #: The provider's own id for this person, stored so a re-enrichment can ask
    #: about the same record instead of matching on a name again — which is how
    #: two Dana Reids at one company become one contact.
    provider_record_id: str | None = None
    #: Which provider supplied each field, so a bad source can be traced later
    #: rather than the whole record being distrusted.
    sources: dict[str, str] = field(default_factory=dict)
    #: The organisation the provider places this person at — its domain and
    #: LinkedIn company page. Carried so a company page can be filled from it,
    #: and only when that domain is the account's own.
    organization_domain: str | None = None
    organization_linkedin_url: str | None = None

    def missing(self, wanted: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(f for f in wanted if not getattr(self, f, None))


class ProviderError(RuntimeError):
    """The provider could not be reached, or refused the request."""


#: What a provider is asked for when it does not say. Permissive on purpose:
#: a provider that has not declared its coverage should be tried, not skipped.
ALL_FIELDS: frozenset[str] = frozenset(
    {"title", "email", "phone", "linkedin_url", "seniority"}
)


@runtime_checkable
class ContactProvider(Protocol):
    name: Provider
    #: Fields this provider can return at all. Not a promise it has them for
    #: any particular person — a promise that asking is capable of succeeding.
    supplies: frozenset[str]

    async def enrich(
        self, *, full_name: str, company_domain: str | None, linkedin_url: str | None
    ) -> ContactRecord | None:
        """Return what this provider knows, or None if it knows nothing."""
        ...


def _merge(base: ContactRecord, extra: ContactRecord, source: Provider) -> ContactRecord:
    """Fill gaps in `base` from `extra`. Never overwrite a value already held.

    The primary provider wins every contested field. Letting the fallback
    overwrite would make the result depend on call order in a way nobody can
    see, and the fallback is the fallback because it is trusted less.
    """
    merged = dict(base.sources)
    updates: dict[str, object] = {}
    for f in ("title", "email", "phone", "linkedin_url", "seniority"):
        if not getattr(base, f, None) and getattr(extra, f, None):
            updates[f] = getattr(extra, f)
            merged[f] = source.value
    if "email" in updates:
        # The grade belongs to the address, not to the record. Taking the
        # fallback's email while keeping the primary's `email_status` would
        # promote a guess to verified on the strength of a field nobody
        # supplied — the exact substitution this column exists to prevent.
        updates["email_status"] = extra.email_status
        # And the id is the *provider's* id, meaningless against another
        # vendor's database. It travels with whoever supplied the address.
        updates["provider_record_id"] = extra.provider_record_id
    if "phone" in updates:
        updates["phone_status"] = extra.phone_status
    for f in ("organization_domain", "organization_linkedin_url"):
        if not getattr(base, f, None) and getattr(extra, f, None):
            updates[f] = getattr(extra, f)
    return replace(base, sources=merged, **updates)  # type: ignore[arg-type]


@dataclass
class EnrichmentOutcome:
    contact: ContactRecord | None = None
    #: Providers actually called, in order. The bill is per call, so this is
    #: the number that has to be explainable.
    called: list[Provider] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    still_missing: tuple[str, ...] = ()


async def enrich(
    *,
    full_name: str,
    company_domain: str | None = None,
    linkedin_url: str | None = None,
    providers: Sequence[ContactProvider] = (),
    primary: ContactProvider | None = None,
    fallback: ContactProvider | None = None,
    required: tuple[str, ...] = ("email",),
) -> EnrichmentOutcome:
    """Ask each provider in turn; stop as soon as nothing required is missing.

    `providers` is an ordered sequence rather than a primary/fallback pair
    because the order is configuration — see `enrichment_config`. A business
    with three contracts should not need a code change to put the cheapest
    first, and a two-slot signature quietly caps the waterfall at two.

    `primary`/`fallback` are still accepted and mean exactly what they did.
    Removing them would break every existing caller for no behavioural gain,
    and a two-provider waterfall is the common case.
    """
    ordered = list(providers) or [p for p in (primary, fallback) if p is not None]
    outcome = EnrichmentOutcome()

    for provider in ordered:
        # Stop as soon as nothing required is outstanding — this is the whole
        # point of a waterfall.
        outstanding = (
            set(outcome.contact.missing(required))
            if outcome.contact is not None
            else set(required)
        )
        if not outstanding:
            break

        supplies = getattr(provider, "supplies", None) or ALL_FIELDS
        if not (outstanding & supplies):
            # Everything still missing is something this provider structurally
            # cannot return. Calling it would be billed and could not succeed.
            log.debug(
                "enrichment.provider_skipped provider=%s outstanding=%s",
                provider.name, sorted(outstanding),
            )
            continue

        outcome.called.append(provider.name)
        try:
            found = await provider.enrich(
                full_name=full_name,
                company_domain=company_domain,
                linkedin_url=linkedin_url,
            )
        except ProviderError as exc:
            # One provider being down must not lose the other's answer.
            outcome.errors[provider.name.value] = str(exc)
            log.warning("enrichment.provider_failed provider=%s err=%s", provider.name, exc)
            continue

        if found is None:
            continue
        if outcome.contact is None:
            outcome.contact = replace(
                found,
                sources={
                    f: provider.name.value
                    for f in ("title", "email", "phone", "linkedin_url", "seniority")
                    if getattr(found, f, None)
                },
            )
        else:
            outcome.contact = _merge(outcome.contact, found, provider.name)

    outcome.still_missing = (
        outcome.contact.missing(required) if outcome.contact else required
    )
    return outcome
