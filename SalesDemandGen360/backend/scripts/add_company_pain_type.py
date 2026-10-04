"""Give a company-level pain statement somewhere to go.

`public_pain_statement` is contact-scoped: a person saying, in public, that they
have a problem. When the company itself says it — in its own announcement, or an
executive speaking for it — extraction had no company-scoped type to use, filed
it under the contact type, and the guard dropped it for having no person.

This adds `company_pain_statement` and names it in the Default ICP as a new
version. It also gives `public_pain_statement` a description if it has none: the
description is what extraction reads to choose between types, and an empty one
is part of why the wrong type was chosen.

Idempotent: run it twice and the second run changes nothing.

    python scripts/add_company_pain_type.py            # show what would change
    python scripts/add_company_pain_type.py --apply    # write it
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.config import IcpProfile, IcpProfileVersion, SignalType  # noqa: E402

KEY = "company_pain_statement"

#: Sources, not a guess: a company's own words appear on its own site and in
#: press about it. Both are already in the Default ICP's accepted sources, so
#: adding this type causes no source drift.
NEW_TYPE = dict(
    key=KEY,
    label="Company pain statement",
    description=(
        "A problem the company says it has itself — in its own announcements, a filing, or "
        "an executive speaking for the company: a system being replaced, a target missed, a "
        "capability it is struggling to build. Not a problem it sells a solution to: a vendor "
        "describing its customers' pain is marketing, not its own need."
    ),
    scope="company",
    default_ttl_days=150,
    weight=1.50,
    produced_by=["company_site", "news"],
    status="active",
)

CONTACT_DESCRIPTION = (
    "A problem this person has said in public that they or their team are dealing with — "
    "in a post, a talk or an interview. Their own words about their own work; commentary "
    "on the industry at large is not pain."
)


async def main(apply: bool) -> None:
    async with SessionLocal() as session:
        types = {row.key: row for row in (await session.execute(select(SignalType))).scalars()}

        type_note = "already present"
        if KEY not in types:
            type_note = "added"
            if apply:
                session.add(SignalType(**NEW_TYPE))

        contact = types.get("public_pain_statement")
        described = "public_pain_statement not found"
        if contact is not None:
            if (contact.description or "").strip():
                described = "public_pain_statement already has a description — left alone"
            else:
                described = "public_pain_statement: description added"
                if apply:
                    contact.description = CONTACT_DESCRIPTION

        profile = (
            await session.execute(select(IcpProfile).where(IcpProfile.name == "Default"))
        ).scalar_one_or_none()
        icp_note = "no ICP named 'Default' — nothing to update"
        if profile is not None:
            active = (
                await session.execute(
                    select(IcpProfileVersion).where(
                        IcpProfileVersion.icp_profile_id == profile.id,
                        IcpProfileVersion.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            current = list((active.definition if active else {}).get("signals_that_matter") or [])
            if KEY in current:
                icp_note = f"ICP already names {KEY}"
            else:
                icp_note = f"ICP v{(active.version if active else 0) + 1}: {KEY} added"
                if apply:
                    # Copied whole — sources, personas, regions and all — so the
                    # new version differs from the last by exactly this one key.
                    definition = dict(active.definition if active else {})
                    definition["signals_that_matter"] = current + [KEY]
                    if active is not None:
                        # Versioned, never edited: a run records the version it
                        # read, and rewriting one would make that record a lie.
                        active.is_active = False
                        await session.flush()
                    session.add(
                        IcpProfileVersion(
                            icp_profile_id=profile.id,
                            definition=definition,
                            version=(active.version if active else 0) + 1,
                            is_active=True,
                        )
                    )

        print(f"{KEY}:", type_note)
        print(described)
        print("ICP:", icp_note)
        if apply:
            await session.commit()
            print("\nwritten.")
        else:
            print("\ndry run — pass --apply to write")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
