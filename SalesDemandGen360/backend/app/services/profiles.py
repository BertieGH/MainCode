"""Building and storing the standing descriptions.

A profile is what a company or a person *is*. A signal is what has just
happened to them. The two are stored differently because they age differently:
a signal carries `observed_at` and `expires_at` and is refused once it is past
its durability; a profile carries neither and is never refused for being old,
because "a brokerage serving contractors" does not become untrue.

That is the whole reason this is not a signal type. It was proposed as one —
`firmographic_baseline` — and a TTL on it would have meant expiring a fact that
had not changed.

**Replaced, not versioned.** A profile is the current best description, and the
previous one is of no interest: nothing cites it the way a draft cites a
signal, so there is no citation to protect. An empty result does *not* replace
a good one — a run that established nothing has not learned that the company
is nothing.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, Contact
from app.schemas.profile import CompanyProfile, ContactProfile

log = logging.getLogger(__name__)


async def build_company(
    session: AsyncSession, *, account: Account, client=None
) -> CompanyProfile | None:
    """Research the company's standing description and store it."""
    from app.services import stages

    result = await stages.company_profile(session, account=account, client=client)
    profile = result.parsed
    if profile is None or profile.is_empty():
        log.info("profiles.company_empty account=%s", account.id)
        return None
    account.profile = profile.model_dump(mode="json")
    await session.flush()
    log.info(
        "profiles.company account=%s services=%d customers=%d",
        account.id, len(profile.services), len(profile.target_customers),
    )
    return profile


async def build_contact(
    session: AsyncSession, *, account: Account, person: Contact, client=None
) -> ContactProfile | None:
    """Research one person's standing description and store it."""
    from app.services import stages

    result = await stages.contact_profile(
        session, account=account, person=person, client=client
    )
    profile = result.parsed
    if profile is None or profile.is_empty():
        log.info("profiles.contact_empty contact=%s", person.id)
        return None
    # Belt and braces against the one thing this must never carry. The prompt
    # forbids it and the contract has no field for it, but a model that puts an
    # address in `summary` would have it stored and later quoted.
    person.profile = _without_contact_details(profile).model_dump(mode="json")
    await session.flush()
    log.info(
        "profiles.contact contact=%s responsibilities=%d",
        person.id, len(profile.responsibilities),
    )
    return profile


def _without_contact_details(profile: ContactProfile) -> ContactProfile:
    """Strip anything that looks like a route to the person.

    Contact details come from a verification provider with a status attached,
    and a generated address that happens to look right is how a sending domain
    gets blacklisted. A profile is not a place one may arrive by the back door.
    """
    import re

    pattern = re.compile(
        r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s().-]{7,}\d", re.ASCII
    )

    def clean(value: str | None) -> str | None:
        if value is None:
            return None
        scrubbed = pattern.sub("[removed]", value)
        if scrubbed != value:
            log.warning("profiles.contact_detail_stripped")
        return scrubbed

    return profile.model_copy(
        update={
            "summary": clean(profile.summary),
            "decision_scope": clean(profile.decision_scope),
            "responsibilities": [clean(r) or "" for r in profile.responsibilities],
            "background": [clean(b) or "" for b in profile.background],
            "focus_areas": [clean(f) or "" for f in profile.focus_areas],
            # Verbatim passages are free text quoted from a page, so they are
            # the **most** likely field to carry an address — a profile page
            # often prints one. Scrubbed like every other string here: the rule
            # is about the data, not about which field it arrived in.
            "verbatim": [
                passage.model_copy(update={"text": clean(passage.text) or ""})
                for passage in profile.verbatim
            ],
        }
    )
