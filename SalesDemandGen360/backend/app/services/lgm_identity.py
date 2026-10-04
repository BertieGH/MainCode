"""Resolving a contact to the LGM lead it would become.

LGM deduplicates on a **priority cascade**, not a single field:

    1. LinkedIn URL — same profile, same lead, whatever the email
    2. Email — used when no LinkedIn. Same email, same lead, even across companies
    3. First + last + company — only when neither of the above exists

A single computed key cannot express that, and assuming it could was the
original mistake. Contact A (LinkedIn X, email E) and contact B (no LinkedIn,
email E) coalesce to *different* keys — so a unique index admits both — while
LGM matches B against A's stored email and merges them into one lead. Their two
sequences then overwrite each other's attributes, which is exactly the state the
lock exists to prevent.

So resolution matches on **any** identifier, in LGM's order, and a contact that
matches two different identities on different fields is marked `conflict`
rather than guessed at. LGM's own behaviour in that case is undocumented, and
guessing which record it merges into risks corrupting whichever sequence
guessed wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import LgmIdentity

_LINKEDIN = re.compile(
    r"^(?:https?://)?(?:[a-z0-9-]+\.)?linkedin\.com/(?:in|pub)/", re.IGNORECASE
)


def normalise_linkedin(url: str | None) -> str | None:
    """Strip host, casing and trailing slash so one profile has one key.

    `https://www.linkedin.com/in/Dana-Reyes/` and `linkedin.com/in/dana-reyes`
    are the same person to LGM, and would be two identities to us without this.
    """
    if not url or not url.strip():
        return None
    trimmed = url.strip()
    if not _LINKEDIN.match(trimmed):
        return None
    slug = _LINKEDIN.sub("", trimmed).split("?")[0].split("#")[0].strip("/")
    return slug.lower() or None


def normalise_email(email: str | None) -> str | None:
    if not email or not email.strip():
        return None
    cleaned = email.strip().lower()
    return cleaned if "@" in cleaned else None


def name_company_key(
    full_name: str | None, company: str | None
) -> str | None:
    """The fallback only. Weak on purpose — it is what LGM falls back to."""
    if not full_name or not company:
        return None
    name = re.sub(r"[^a-z0-9]+", "", full_name.lower())
    org = re.sub(r"[^a-z0-9]+", "", company.lower())
    return f"{name}|{org}" if name and org else None


@dataclass(frozen=True)
class IdentityKeys:
    linkedin_slug: str | None = None
    email: str | None = None
    name_company_key: str | None = None

    @property
    def any(self) -> bool:
        return bool(self.linkedin_slug or self.email or self.name_company_key)


def keys_for(
    *, linkedin_url: str | None, email: str | None, full_name: str | None, company: str | None
) -> IdentityKeys:
    linkedin = normalise_linkedin(linkedin_url)
    mail = normalise_email(email)
    # The name fallback is only meaningful when neither stronger identifier
    # exists — computing it always would let a weak match cluster two people
    # who share a name at one company.
    fallback = None if (linkedin or mail) else name_company_key(full_name, company)
    return IdentityKeys(linkedin_slug=linkedin, email=mail, name_company_key=fallback)


class UnresolvableContactError(ValueError):
    """No identifier at all. LGM could not place this person either."""


async def resolve(session: AsyncSession, keys: IdentityKeys) -> LgmIdentity:
    """Find the identity this contact belongs to, or create it.

    Matches on *any* identifier rather than the strongest one present, because
    that is what LGM does. A contact matching two different identities is
    marked `conflict` and both are left intact — merging them here would make
    an irreversible guess about a documented unknown.
    """
    if not keys.any:
        raise UnresolvableContactError(
            "contact has no LinkedIn URL, no email and no name+company; "
            "it cannot be matched to an LGM lead"
        )

    clauses = []
    if keys.linkedin_slug:
        clauses.append(LgmIdentity.linkedin_slug == keys.linkedin_slug)
    if keys.email:
        clauses.append(LgmIdentity.email == keys.email)
    if keys.name_company_key:
        clauses.append(LgmIdentity.name_company_key == keys.name_company_key)

    matches = list(
        (await session.execute(select(LgmIdentity).where(or_(*clauses)))).scalars()
    )

    if not matches:
        row = LgmIdentity(
            linkedin_slug=keys.linkedin_slug,
            email=keys.email,
            name_company_key=keys.name_company_key,
            resolution_state="resolved",
        )
        session.add(row)
        await session.flush()
        return row

    if len(matches) > 1:
        detail = (
            "matches "
            + ", ".join(sorted(str(m.id) for m in matches))
            + " on different identifiers; LGM's merge behaviour here is undocumented"
        )
        for m in matches:
            m.resolution_state = "conflict"
            m.conflict_detail = detail
        await session.flush()
        return matches[0]

    found = matches[0]
    # Fill in identifiers we now know and the identity did not. This is how a
    # contact discovered by email later becomes matchable by LinkedIn — and it
    # is why a second contact sharing either one resolves to this same row.
    if keys.linkedin_slug and not found.linkedin_slug:
        found.linkedin_slug = keys.linkedin_slug
    if keys.email and not found.email:
        found.email = keys.email
    if keys.name_company_key and not found.name_company_key:
        found.name_company_key = keys.name_company_key
    await session.flush()
    return found
